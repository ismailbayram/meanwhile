import json
import sys

import pytest

from meanwhile import cli, strings

POOL = {
    "builtAt": "2026-08-28",
    "headSha": "abc123",
    "repo": "demo",
    "items": [
        {
            "type": "quiz",
            "q": "Q?",
            "choices": ["a", "b"],
            "answer": 0,
            "why": "because",
            "source": "real.py",
        }
    ],
}


def seed(tmp_path, pool=POOL, source_exists=True):
    (tmp_path / ".meanwhile").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".meanwhile" / "pool.json").write_text(json.dumps(pool), encoding="utf-8")
    if source_exists:
        (tmp_path / "real.py").write_text("x = 1", encoding="utf-8")
    return tmp_path


def test_banner_is_empty_when_staleness_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.repo, "commits_behind", lambda *_: None)
    assert cli.staleness_banner(tmp_path, "abc123") == ""


def test_banner_is_empty_below_the_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.repo, "commits_behind", lambda *_: 3)
    assert cli.staleness_banner(tmp_path, "abc123") == ""


def test_banner_names_the_drift_and_the_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.repo, "commits_behind", lambda *_: 120)
    banner = cli.staleness_banner(tmp_path, "abc123")
    assert banner == strings.text(strings.DEFAULT_LANGUAGE, "stale", behind=120)


def test_banner_follows_the_language_argument(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.repo, "commits_behind", lambda *_: 120)
    banner = cli.staleness_banner(tmp_path, "abc123", language="tr")
    assert banner == strings.text("tr", "stale", behind=120)


def test_validate_accepts_a_good_pool(tmp_path):
    code, messages = cli.validate(seed(tmp_path))
    assert code == 0
    assert messages == ["pool is valid: 1 item(s)"]


def test_validate_reports_a_missing_source_file(tmp_path):
    code, messages = cli.validate(seed(tmp_path, source_exists=False))
    assert code == 1
    assert any("real.py" in m for m in messages)


def test_validate_reports_a_structurally_broken_pool(tmp_path):
    broken = json.loads(json.dumps(POOL))
    broken["items"][0]["answer"] = 9
    code, messages = cli.validate(seed(tmp_path, pool=broken))
    assert code == 1
    assert any("answer" in m for m in messages)


def test_main_reports_a_missing_pool_without_launching_the_ui(tmp_path, capsys):
    code = cli.main(["--repo", str(tmp_path)])
    assert code == 1
    assert "/meanwhile-build" in capsys.readouterr().out


def test_the_missing_pool_message_names_a_route_for_every_agent(tmp_path, capsys):
    """`/meanwhile-build` is a Claude Code slash command and does not exist for
    a Codex or Cursor user — who is the likeliest person to hit this message,
    since opening the pane before building a pool is the obvious first-run
    mistake on those paths."""
    cli.main(["--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert "/meanwhile-build" in out
    assert "build-prompt" in out


def test_the_lang_help_asks_for_a_code_and_names_the_two_that_ship(monkeypatch, capsys):
    """Nothing on the documented path used to spell `tr` or `en` out, so a user
    reading "interface language" passed a language *name* and got an English
    interface with no complaint."""
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/meanwhile", "--help"])
    with pytest.raises(SystemExit):
        cli.main(["--help"])

    # Whitespace-normalized: argparse wraps the help text to the terminal.
    help_text = " ".join(capsys.readouterr().out.split())
    assert "short language code, e.g. tr or en" in help_text


def test_pool_is_found_at_the_git_root_when_run_from_a_subdirectory(tmp_path, capsys):
    """The other half of the launch-dir/repo-root split: the pool still lives
    at the git root, even when the pane is opened in a subdirectory."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    seed(tmp_path)
    subdir = tmp_path / "backend"
    subdir.mkdir()

    assert cli.main(["validate", "--repo", str(subdir)]) == 0
    assert "pool is valid" in capsys.readouterr().out


def test_launch_dir_is_the_directory_given_not_the_git_root(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subdir = tmp_path / "backend"
    subdir.mkdir()

    assert cli.launch_dir(subdir) == subdir.resolve()
    assert cli.repo_root(subdir).resolve() == tmp_path.resolve()


def test_validate_reports_every_missing_source_not_just_the_first(tmp_path):
    """`validate` collects the whole set before reporting. With a single-item
    pool "reports all" and "reports the first" look identical, so this is the
    only test that can tell them apart."""
    two = json.loads(json.dumps(POOL))
    second = json.loads(json.dumps(POOL["items"][0]))
    second["source"] = "also_gone.py"
    two["items"][0]["source"] = "gone.py"
    two["items"].append(second)

    code, messages = cli.validate(seed(tmp_path, pool=two, source_exists=False))

    assert code == 1
    assert any("gone.py" in m for m in messages)
    assert any("also_gone.py" in m for m in messages)


def test_lang_overrides_the_pool_language(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "_run_app", lambda **kwargs: captured.update(kwargs) or 0)
    seed(tmp_path, pool={**POOL, "language": "tr"})
    cli.main(["--repo", str(tmp_path), "--lang", "en"])
    assert captured["language"] == "en"


def test_without_lang_the_pool_language_is_used(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "_run_app", lambda **kwargs: captured.update(kwargs) or 0)
    seed(tmp_path, pool={**POOL, "language": "tr"})
    cli.main(["--repo", str(tmp_path)])
    assert captured["language"] == "tr"


@pytest.mark.parametrize("invoked_as", ["meanwhile", "claude-meanwhile"])
def test_help_names_the_command_it_was_invoked_as(invoked_as, monkeypatch, capsys):
    """Both console scripts point at cli.main, so a hardcoded prog= would make
    one of them advertise the other's name."""
    monkeypatch.setattr(sys, "argv", [f"/usr/local/bin/{invoked_as}", "--help"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--help"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith(f"usage: {invoked_as} ")
