import json
import shlex
import subprocess
from pathlib import Path

import pytest

from meanwhile import state


def run_hook(home, project, status, agent=None, check=True):
    """Helper to run the bash hook with optional agent slug."""
    cmd = ["bash", str(HOOK), status]
    if agent is not None:
        cmd.append(agent)
    return subprocess.run(
        cmd,
        input=b"{}",
        env={**HOOK_ENV, "HOME": str(home), "CLAUDE_PROJECT_DIR": str(project)},
        capture_output=True,
        check=check,
    )

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "meanwhile-state.sh"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
HOOK_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin"}


def test_project_key_is_16_hex_chars_and_stable(tmp_path):
    key = state.project_key(tmp_path)
    assert len(key) == 16
    assert all(c in "0123456789abcdef" for c in key)
    assert key == state.project_key(tmp_path)


def test_project_key_differs_per_directory(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert state.project_key(a) != state.project_key(b)


def test_write_then_read_round_trip(tmp_path):
    root = tmp_path / "state"
    state.write_state(tmp_path, "busy", root=root, now=1234.0)
    assert state.read_state(tmp_path, root=root) == {"status": "busy", "ts": 1234.0, "agent": None}


def test_read_state_defaults_to_idle_when_missing(tmp_path):
    assert state.read_state(tmp_path, root=tmp_path / "nope") == {"status": "idle", "ts": 0.0, "agent": None}


def test_read_state_defaults_to_idle_on_corrupt_file(tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    state.state_path(tmp_path, root=root).write_text("{ not json")
    assert state.read_state(tmp_path, root=root) == {"status": "idle", "ts": 0.0, "agent": None}


def test_write_state_rejects_unknown_status(tmp_path):
    with pytest.raises(ValueError):
        state.write_state(tmp_path, "thinking", root=tmp_path / "state")


def test_bash_hook_and_python_agree_on_the_key(tmp_path, monkeypatch):
    """The contract that makes the whole tool work. If this fails, the TUI never wakes."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()

    subprocess.run(
        ["bash", str(HOOK), "busy"],
        input=b"{}",
        env={"HOME": str(home), "CLAUDE_PROJECT_DIR": str(project), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        check=True,
    )

    written = home / ".meanwhile" / "state" / f"{state.project_key(project)}.json"
    assert written.exists(), f"hook wrote a different key; found {list((home / '.meanwhile' / 'state').iterdir())}"
    assert json.loads(written.read_text())["status"] == "busy"


def test_hook_and_cli_agree_when_claude_starts_below_the_git_root(tmp_path):
    """The monorepo case: Claude Code launched in `backend/`, not at the git root.

    The hook keys on CLAUDE_PROJECT_DIR (the launch directory); the TUI must
    key on the same directory, not on `git rev-parse --show-toplevel`.
    test_bash_hook_and_python_agree_on_the_key hands both sides the same path,
    so it cannot see this divergence.
    """
    from meanwhile import cli

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    subdir = project / "backend"
    subdir.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True, capture_output=True)

    subprocess.run(
        ["bash", str(HOOK), "busy"],
        input=b"{}",
        env={
            "HOME": str(home),
            "CLAUDE_PROJECT_DIR": str(subdir),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
        check=True,
    )

    state_root = home / ".meanwhile" / "state"
    polled = state.state_path(cli.launch_dir(subdir), root=state_root)
    assert polled.exists(), f"CLI polls {polled.name}; hook wrote {[p.name for p in state_root.iterdir()]}"
    assert state.read_state(cli.launch_dir(subdir), root=state_root)["status"] == "busy"

    # And the git root really is a different directory, so the old behaviour
    # (keying the TUI on repo_root) would have missed the file entirely.
    root = cli.repo_root(subdir)
    assert root.resolve() == project.resolve()
    assert not state.state_path(root, root=state_root).exists()


def test_the_hook_keys_on_its_working_directory_when_the_env_var_is_unset(tmp_path):
    """The `$PWD` half of `${CLAUDE_PROJECT_DIR:-$PWD}`.

    Only Claude Code sets CLAUDE_PROJECT_DIR, so this is the branch every
    single Codex and Cursor run takes — and every other hook test sets the
    variable, so nothing else here ever exercises it. If it keyed a different
    directory than `state.project_key` does, those users' panes would never
    wake and nothing would say why.
    """
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()

    subprocess.run(
        ["bash", str(HOOK), "busy", "codex"],
        input=b"{}",
        cwd=str(project),
        env={**HOOK_ENV, "HOME": str(home)},  # no CLAUDE_PROJECT_DIR at all
        check=True,
    )

    state_root = home / ".meanwhile" / "state"
    written = state.state_path(project, root=state_root)
    assert written.exists(), (
        f"python keys {project} as {written.name}; hook wrote "
        f"{[p.name for p in state_root.iterdir()]}"
    )
    read = state.read_state(project, root=state_root)
    assert read["status"] == "busy"
    assert read["agent"] == "codex"


@pytest.mark.parametrize("shape", ["plain", "trailing-slash", "dot-dot"])
def test_bash_hook_and_python_agree_on_a_directory_that_does_not_exist(tmp_path, shape):
    """`Path.resolve()` normalizes a path whether or not it exists, so the hook
    has to as well. The project directory is reached through a symlink here —
    the everyday macOS case, where /tmp and /var are symlinks — so a hook that
    gave up and hashed the raw string would key on a different path.
    """
    home = tmp_path / "home"
    home.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    missing = f"{link}/gone/deeper"
    if shape == "trailing-slash":
        missing += "/"
    elif shape == "dot-dot":
        missing = f"{link}/gone/elsewhere/../deeper"
    assert not Path(missing).exists()

    subprocess.run(
        ["bash", str(HOOK), "busy"],
        input=b"{}",
        env={**HOOK_ENV, "HOME": str(home), "CLAUDE_PROJECT_DIR": missing},
        check=True,
    )

    state_root = home / ".meanwhile" / "state"
    written = state.state_path(missing, root=state_root)
    assert written.exists(), (
        f"python keys {missing!r} as {written.name}; hook wrote "
        f"{[p.name for p in state_root.iterdir()]}"
    )
    assert state.read_state(missing, root=state_root)["status"] == "busy"


@pytest.mark.parametrize("argv", [[], [""], ["BUSY"], ["busy idle"], ["thinking"], ["--help"]])
def test_hook_refuses_a_status_it_does_not_understand(tmp_path, argv):
    """A typo would otherwise be written verbatim and read back as "idle", and
    the TUI would sit there for the rest of the day with nothing to show why."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()

    result = subprocess.run(
        ["bash", str(HOOK), *argv],
        input=b"{}",
        env={**HOOK_ENV, "HOME": str(home), "CLAUDE_PROJECT_DIR": str(project)},
        capture_output=True,
    )

    assert result.returncode != 0
    # A UserPromptSubmit hook's stdout is injected into Claude's context.
    assert result.stdout == b""
    assert b"busy" in result.stderr and b"idle" in result.stderr
    assert not (home / ".meanwhile").exists()  # and nothing was written


def test_every_hook_registration_passes_a_status_the_hook_accepts(tmp_path):
    """The test that would have caught a typo in the registration itself: run
    the hook with exactly the arguments hooks.json gives it."""
    events = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    commands = [
        entry["command"]
        for matchers in events.values()
        for matcher in matchers
        for entry in matcher["hooks"]
    ]
    assert commands, "hooks.json registers no commands at all"

    for index, command in enumerate(commands):
        script, *args = shlex.split(command)
        assert script.endswith("/hooks/meanwhile-state.sh"), f"unexpected script: {script}"
        assert len(args) == 2, f"{command!r} passes {len(args)} arguments, not status and agent"

        home = tmp_path / f"home{index}"
        home.mkdir()
        result = subprocess.run(
            ["bash", str(HOOK), *args],
            input=b"{}",
            env={**HOOK_ENV, "HOME": str(home), "CLAUDE_PROJECT_DIR": str(tmp_path)},
            capture_output=True,
        )

        assert result.returncode == 0, f"{command!r} -> {result.stderr.decode()}"
        # Not `in ("busy", "idle")`: read_state answers "idle" for a missing
        # file too, so that would have passed the Stop registration even if the
        # hook had written nothing at all.
        root = home / ".meanwhile" / "state"
        assert state.state_path(tmp_path, root=root).exists(), f"{command!r} wrote no state file"
        read = state.read_state(tmp_path, root=root)
        assert read["status"] == args[0]
        assert read["agent"] == args[1]


@pytest.mark.parametrize("tail", ["", "/gone", "/gone/deeper"])
def test_bash_hook_and_python_agree_on_dot_dot_after_a_symlink(tmp_path, tail):
    """The one shape where `cd` alone is not enough.

    Bash's `cd` defaults to -L, which folds a ".." that follows a symlinked
    component lexically. `Path.resolve()` follows the link first and pops from
    the link's *target*, so the two land in different directories unless the
    hook uses `cd -P`. `tail=""` is the everything-exists form; the others send
    the hook down the resolve-a-prefix-and-re-append path as well.
    """
    home = tmp_path / "home"
    home.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "deep").mkdir(parents=True)
    (real / "tolink").symlink_to(elsewhere / "deep")

    project = f"{real}/tolink/..{tail}"
    # The lexical answer and the physical one are genuinely different
    # directories here, so this test can tell them apart.
    assert Path(project).resolve() == Path(f"{elsewhere}{tail}").resolve()
    assert Path(project).resolve() != real.resolve()

    subprocess.run(
        ["bash", str(HOOK), "busy"],
        input=b"{}",
        env={**HOOK_ENV, "HOME": str(home), "CLAUDE_PROJECT_DIR": project},
        check=True,
    )

    state_root = home / ".meanwhile" / "state"
    written = state.state_path(project, root=state_root)
    assert written.exists(), (
        f"python keys {project!r} as {written.name}; hook wrote "
        f"{[p.name for p in state_root.iterdir()]}"
    )
    assert state.read_state(project, root=state_root)["status"] == "busy"


def test_write_and_read_round_trip_the_agent(tmp_path):
    root = tmp_path / "state"
    state.write_state(tmp_path, "busy", root=root, now=1.0, agent="codex")
    assert state.read_state(tmp_path, root=root) == {"status": "busy", "ts": 1.0, "agent": "codex"}


def test_agent_is_none_when_not_written(tmp_path):
    root = tmp_path / "state"
    state.write_state(tmp_path, "busy", root=root, now=1.0)
    assert state.read_state(tmp_path, root=root)["agent"] is None


def test_a_state_file_written_before_agents_existed_reads_as_none(tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    state.state_path(tmp_path, root=root).write_text('{"status":"busy","ts":1}', encoding="utf-8")
    assert state.read_state(tmp_path, root=root)["agent"] is None


def test_write_state_rejects_a_malformed_agent(tmp_path):
    with pytest.raises(ValueError):
        state.write_state(tmp_path, "busy", root=tmp_path / "state", agent="Not A Slug")


def test_read_state_ignores_a_malformed_agent_on_disk(tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    state.state_path(tmp_path, root=root).write_text(
        '{"status":"busy","ts":1,"agent":"../etc"}', encoding="utf-8"
    )
    assert state.read_state(tmp_path, root=root)["agent"] is None


def test_the_hook_writes_the_agent_slug(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    run_hook(home, project, "busy", "cursor")
    written = home / ".meanwhile" / "state" / f"{state.project_key(project)}.json"
    assert json.loads(written.read_text())["agent"] == "cursor"


def test_the_hook_refuses_a_malformed_agent_slug(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    result = run_hook(home, project, "busy", "Not A Slug", check=False)
    assert result.returncode != 0
    assert not (home / ".meanwhile" / "state").exists()


def test_the_hook_rejects_agent_with_embedded_newline(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    result = run_hook(home, project, "busy", "cursor\nbad", check=False)
    assert result.returncode != 0
    assert not (home / ".meanwhile" / "state").exists()


def test_the_hook_rejects_agent_with_json_injection(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    result = run_hook(home, project, "busy", 'cursor\n","injected":"pwned', check=False)
    assert result.returncode != 0
    assert not (home / ".meanwhile" / "state").exists()


def test_write_state_rejects_agent_with_trailing_newline(tmp_path):
    with pytest.raises(ValueError):
        state.write_state(tmp_path, "busy", root=tmp_path / "state", agent="cursor\n")


def test_hook_refusal_does_not_clobber_existing_state(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()

    # Write a good state file first
    run_hook(home, project, "busy", "claude")
    written = home / ".meanwhile" / "state" / f"{state.project_key(project)}.json"
    good_content = written.read_text()
    good_data = json.loads(good_content)
    assert good_data["status"] == "busy"
    assert good_data["agent"] == "claude"

    # Try to write with malformed agent (should fail)
    result = run_hook(home, project, "idle", "bad\nagent", check=False)
    assert result.returncode != 0

    # File should still contain the good data, not be clobbered
    assert written.read_text() == good_content
    assert json.loads(written.read_text()) == good_data
