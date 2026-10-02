"""`waitgame hooks`: writing the busy/idle registration into an agent's config.

Every failure mode here is silent. A registration written to the wrong path,
naming the wrong event, or pointing at a script that has moved raises nothing
at all — the pane simply never wakes, and nothing anywhere says why. So these
tests pin the things that have no other symptom: that a foreign hook survives,
that a config we cannot parse is refused rather than overwritten, that Cursor's
user scope is refused with its reason, and — last — that the command we wrote
is one the real script actually accepts.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from waitgame import agents, cli, hooks_cli

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    home.mkdir()
    return repo, home


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_install_writes_the_config_and_the_script(sandbox, slug):
    repo, home = sandbox
    agent = agents.agent_by_slug(slug)
    hooks_cli.install(agent, repo=repo, home=home)

    script = home / ".waitgame" / "waitgame-state.sh"
    assert script.read_text() == hooks_cli.packaged_script().read_text()
    assert os.stat(script).st_mode & stat.S_IXUSR

    document = json.loads(hooks_cli.config_path(agent, repo, home, user=False).read_text())
    commands = agents.registered_commands(document, agent)
    assert len(commands) == 2
    assert all(str(script) in c for c in commands)


def test_install_is_idempotent(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    hooks_cli.install(agent, repo=repo, home=home)
    hooks_cli.install(agent, repo=repo, home=home)
    document = json.loads(hooks_cli.config_path(agent, repo, home, user=False).read_text())
    assert len(agents.registered_commands(document, agent)) == 2


def test_install_keeps_unrelated_settings(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("claude")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"model": "opus", "hooks": {"Stop": [{"hooks": [{"command": "theirs.sh"}]}]}}))
    hooks_cli.install(agent, repo=repo, home=home)
    document = json.loads(path.read_text())
    assert document["model"] == "opus"
    assert "theirs.sh" in json.dumps(document)


def test_cursor_refuses_user_scope(sandbox):
    repo, home = sandbox
    with pytest.raises(hooks_cli.HooksError) as excinfo:
        hooks_cli.install(agents.agent_by_slug("cursor"), repo=repo, home=home, user=True)
    assert "project" in str(excinfo.value).lower()
    assert not (home / ".waitgame").exists()


def test_uninstall_removes_only_ours(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "theirs.sh"}]}]}}))
    hooks_cli.install(agent, repo=repo, home=home)
    hooks_cli.uninstall(agent, repo=repo, home=home)
    document = json.loads(path.read_text())
    assert agents.registered_commands(document, agent) == []
    assert "theirs.sh" in json.dumps(document)


def test_uninstall_deletes_a_file_it_emptied(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    hooks_cli.install(agent, repo=repo, home=home)
    hooks_cli.uninstall(agent, repo=repo, home=home)
    assert not hooks_cli.config_path(agent, repo, home, user=False).exists()


def test_status_reports_each_agent(sandbox):
    repo, home = sandbox
    hooks_cli.install(agents.agent_by_slug("codex"), repo=repo, home=home)
    lines = hooks_cli.status(repo=repo, home=home)
    assert any("codex" in line and "installed" in line for line in lines)
    assert any("cursor" in line and "not installed" in line for line in lines)


def test_status_says_it_cannot_see_a_claude_code_plugin_install(sandbox):
    """`status` reads the registration files this module writes and nothing
    else, so a plugin install — which registers the same two hooks through its
    own hooks.json — reads as `not installed` here. Left bare, that invites a
    plugin user to add a redundant second copy, so the line says what it can
    and cannot see. Only Claude Code has a plugin, so only its line says it.
    """
    repo, home = sandbox
    lines = {line.split(" ")[0]: line for line in hooks_cli.status(repo=repo, home=home)}

    assert lines["claude"] == (
        "claude (Claude Code): not installed (the plugin registers its own hooks separately)"
    )
    assert lines["codex"] == "codex (Codex): not installed"
    assert lines["cursor"] == "cursor (Cursor): not installed"


def test_the_plugin_note_is_only_on_the_not_installed_line(sandbox):
    """Once our own registration is there, `installed` is the whole story."""
    repo, home = sandbox
    hooks_cli.install(agents.agent_by_slug("claude"), repo=repo, home=home)
    line = next(l for l in hooks_cli.status(repo=repo, home=home) if l.startswith("claude"))
    assert "installed (project)" in line
    assert "separately" not in line


def test_status_reports_a_stale_script_copy(sandbox):
    repo, home = sandbox
    hooks_cli.install(agents.agent_by_slug("codex"), repo=repo, home=home)
    (home / ".waitgame" / "waitgame-state.sh").write_text("#!/bin/sh\n# an old copy\n")
    assert any("stale" in line for line in hooks_cli.status(repo=repo, home=home))


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_the_registered_command_is_one_the_hook_accepts(sandbox, slug):
    """Runs the real hook with exactly the arguments we registered.

    What it proves: the command we wrote names a script that exists, is
    executable, is accepted by the script's own argument validation (the
    busy/idle word and the agent slug), drains its stdin and exits 0 — the
    whole chain from `install` to a working hook, with no symptom of its own if
    any link is wrong. What it does not prove: the event name. The commands
    come back through `registered_commands`, which looks the events up by the
    same constants `merge` wrote them under, so a wrong event name is invisible
    here; only `agents.AGENTS` itself pins those.
    """
    import shlex
    import subprocess

    repo, home = sandbox
    agent = agents.agent_by_slug(slug)
    hooks_cli.install(agent, repo=repo, home=home)
    document = json.loads(hooks_cli.config_path(agent, repo, home, user=False).read_text())

    for command in agents.registered_commands(document, agent):
        argv = shlex.split(command)
        result = subprocess.run(
            argv,
            input=b"{}",
            env={"HOME": str(home), "CLAUDE_PROJECT_DIR": str(repo), "PATH": os.environ["PATH"]},
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr


# --- the packaged copy of the script -----------------------------------------


def test_the_packaged_script_matches_the_plugin_copy():
    """Two copies ship: the plugin runs `hooks/waitgame-state.sh`, `hooks
    install` copies the packaged one. If they ever drift, a Codex user runs one
    version of the hook and a Claude Code user another, and nothing else
    anywhere would say so."""
    assert hooks_cli.packaged_script().read_bytes() == (ROOT / "hooks" / "waitgame-state.sh").read_bytes()


def test_the_plugin_registration_still_points_at_the_plugin_copy():
    """The packaged copy is for `hooks install`; the plugin keeps using its own,
    because ${CLAUDE_PLUGIN_ROOT} is the only path it can name."""
    text = (ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/waitgame-state.sh" in text


def test_the_default_installed_script_is_the_copy_under_the_home_directory():
    """Not the packaged file: under `uvx` the package lives in a cache
    directory that can be reclaimed, and a registration pointing there would
    quietly stop writing."""
    assert hooks_cli.INSTALLED_SCRIPT == Path.home() / ".waitgame" / "waitgame-state.sh"
    assert hooks_cli.installed_script("/somewhere") == Path("/somewhere/.waitgame/waitgame-state.sh")


# --- refusals -----------------------------------------------------------------


def test_a_malformed_config_is_refused_not_overwritten(sandbox):
    """Somebody's hand-edited settings.json with a stray comma must not be
    silently replaced with ours."""
    repo, home = sandbox
    agent = agents.agent_by_slug("claude")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text('{"model": "opus",}')

    with pytest.raises(hooks_cli.HooksError) as excinfo:
        hooks_cli.install(agent, repo=repo, home=home)

    assert str(path) in str(excinfo.value)
    assert path.read_text() == '{"model": "opus",}'
    # And nothing at all was written: the script copy is a write like any other.
    assert not (home / ".waitgame").exists()


def test_a_config_that_is_not_an_object_is_refused(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2, 3]")

    with pytest.raises(hooks_cli.HooksError):
        hooks_cli.install(agent, repo=repo, home=home)


def test_status_reports_a_missing_script_copy(sandbox):
    repo, home = sandbox
    hooks_cli.install(agents.agent_by_slug("codex"), repo=repo, home=home)
    (home / ".waitgame" / "waitgame-state.sh").unlink()
    assert any("stale" in line for line in hooks_cli.status(repo=repo, home=home))


def test_status_survives_a_config_it_cannot_parse(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("cursor")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text("{oops")
    lines = hooks_cli.status(repo=repo, home=home)
    assert any("cursor" in line and "unreadable" in line for line in lines)


def test_uninstall_on_a_config_that_was_never_installed(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    message = hooks_cli.uninstall(agent, repo=repo, home=home)
    assert "nothing" in message.lower()


# --- the command line ---------------------------------------------------------


@pytest.fixture
def home_env(sandbox, monkeypatch):
    repo, home = sandbox
    monkeypatch.setenv("HOME", str(home))
    return repo, home


def test_cli_installs_for_the_named_agent(home_env, capsys):
    repo, home = home_env
    assert cli.main(["hooks", "install", "--agent", "codex", "--repo", str(repo)]) == 0
    assert hooks_cli.config_path(agents.agent_by_slug("codex"), repo, home, user=False).exists()
    assert "Codex" in capsys.readouterr().out


def test_cli_reports_a_refusal_and_fails(home_env, capsys):
    repo, _ = home_env
    code = cli.main(["hooks", "install", "--agent", "cursor", "--user", "--repo", str(repo)])
    assert code == 1
    assert "Cursor" in capsys.readouterr().err


def test_cli_auto_only_touches_agents_that_already_have_a_directory(home_env, capsys):
    repo, home = home_env
    (repo / ".codex").mkdir()
    assert cli.main(["hooks", "install", "--agent", "auto", "--repo", str(repo)]) == 0

    assert (repo / ".codex" / "hooks.json").exists()
    assert not (repo / ".cursor").exists()
    assert not (repo / ".claude").exists()
    assert "Codex" in capsys.readouterr().out


def test_cli_auto_says_so_when_it_finds_no_agent(home_env, capsys):
    repo, _ = home_env
    assert cli.main(["hooks", "install", "--repo", str(repo)]) == 1
    assert "--agent" in capsys.readouterr().err


def test_cli_status_prints_a_line_per_agent(home_env, capsys):
    repo, _ = home_env
    assert cli.main(["hooks", "status", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert all(agent.slug in out for agent in agents.AGENTS)


def test_cli_uninstall_removes_the_registration(home_env, capsys):
    repo, home = home_env
    cli.main(["hooks", "install", "--agent", "cursor", "--repo", str(repo)])
    assert cli.main(["hooks", "uninstall", "--agent", "cursor", "--repo", str(repo)]) == 0
    assert not hooks_cli.config_path(agents.agent_by_slug("cursor"), repo, home, user=False).exists()


# --- what a refused or interrupted write must not cost --------------------------


def test_an_empty_config_file_is_not_a_malformed_one(sandbox):
    """A zero-byte file has nothing to lose, so it is a starting point, not a
    refusal. A file with actual non-JSON content stays refused."""
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text("   \n")

    hooks_cli.install(agent, repo=repo, home=home)

    assert len(agents.registered_commands(json.loads(path.read_text()), agent)) == 2


def test_the_config_is_never_truncated_before_it_is_written(sandbox, monkeypatch):
    """`write_text` truncates first: a crash between truncate and write would
    destroy the settings we were asked to preserve. Nothing else would notice —
    the file is simply shorter afterwards."""
    repo, home = sandbox
    agent = agents.agent_by_slug("claude")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    original = json.dumps({"model": "opus"})
    path.write_text(original)

    def boom(*_args, **_kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(hooks_cli.os, "replace", boom)
    with pytest.raises(OSError):
        hooks_cli.install(agent, repo=repo, home=home)

    assert path.read_text() == original
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_install_leaves_no_temporary_file_behind(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    hooks_cli.install(agent, repo=repo, home=home)
    path = hooks_cli.config_path(agent, repo, home, user=False)
    assert [p.name for p in path.parent.iterdir()] == [path.name]


# --- a registration that must not be committed ----------------------------------


def _git(repo, *args):
    import subprocess

    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def test_install_says_so_when_the_file_it_wrote_is_tracked_by_git(sandbox):
    """The command carries an absolute path to this machine. Codex and Cursor
    have no gitignored sibling to move to, so all we can do is say so."""
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    _git(repo, "init", "-q")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    _git(repo, "add", str(path))

    message = hooks_cli.install(agent, repo=repo, home=home)

    assert "tracked by git" in message
    assert "does not exist for them" in message


@pytest.mark.parametrize("slug", ["codex", "cursor"])
@pytest.mark.parametrize("in_a_repo", [True, False])
def test_install_warns_before_the_file_is_ever_tracked(sandbox, slug, in_a_repo):
    """Already-tracked is the rare case; this is the common one.

    `hooks install --agent codex` creates `.codex/hooks.json` from nothing and
    the user commits it afterwards — at which point git tracks nothing yet, so
    warning only about a tracked file means never warning at all on the flow
    that actually happens.
    """
    repo, home = sandbox
    if in_a_repo:
        _git(repo, "init", "-q")

    message = hooks_cli.install(agents.agent_by_slug(slug), repo=repo, home=home)

    assert "specific to this machine" in message
    assert "does not exist for them" in message


def test_install_is_quiet_about_the_gitignored_sibling(sandbox):
    """Claude Code's project registration goes to settings.local.json, which is
    the gitignored file — there is nothing to warn about."""
    repo, home = sandbox
    _git(repo, "init", "-q")
    message = hooks_cli.install(agents.agent_by_slug("claude"), repo=repo, home=home)
    assert "specific to this machine" not in message


def test_install_is_quiet_at_the_user_scope(sandbox):
    """A registration under the home directory is this machine's by definition
    and is not in anybody's repository to commit."""
    repo, home = sandbox
    message = hooks_cli.install(agents.agent_by_slug("codex"), repo=repo, home=home, user=True)
    assert "specific to this machine" not in message


def test_the_claude_project_registration_goes_to_the_gitignored_sibling(sandbox):
    """settings.json is the committed file; the absolute script path we write
    is this machine's. A teammate who checked it out would have Claude Code run
    a nonexistent script on every prompt submit."""
    repo, home = sandbox
    agent = agents.agent_by_slug("claude")
    assert hooks_cli.config_path(agent, repo, home, user=False).name == "settings.local.json"
    assert hooks_cli.config_path(agent, repo, home, user=True).name == "settings.json"


# --- neighbours we do not understand --------------------------------------------


def test_a_neighbour_that_is_not_a_hook_entry_survives_both_ways(sandbox):
    """"Never destroys a foreign hook" must not quietly mean "never destroys a
    well-formed one": a bare string in the event array is somebody's content
    too, and dropping it would be silent."""
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"hooks": {"Stop": ["a bare string", {"hooks": [{"command": "theirs.sh"}]}]}}))

    hooks_cli.install(agent, repo=repo, home=home)
    assert "a bare string" in json.loads(path.read_text())["hooks"]["Stop"]

    hooks_cli.uninstall(agent, repo=repo, home=home)
    document = json.loads(path.read_text())
    assert "a bare string" in document["hooks"]["Stop"]
    assert "theirs.sh" in json.dumps(document)


def test_the_cli_reports_a_config_it_cannot_write_instead_of_a_traceback(home_env, capsys):
    repo, _ = home_env
    (repo / ".codex").mkdir()
    (repo / ".codex").chmod(0o500)
    try:
        code = cli.main(["hooks", "install", "--agent", "codex", "--repo", str(repo)])
    finally:
        (repo / ".codex").chmod(0o700)

    assert code == 1
    assert "hooks.json" in capsys.readouterr().err
