import subprocess

import pytest

from waitgame import repo


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def tiny_repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("one")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "first")
    first = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    return tmp_path, first


def test_zero_when_pool_matches_head(tiny_repo):
    path, first = tiny_repo
    assert repo.commits_behind(path, first) == 0


def test_counts_commits_made_after_the_pool(tiny_repo):
    path, first = tiny_repo
    for n in range(3):
        (path / f"b{n}.txt").write_text(str(n))
        git(path, "add", ".")
        git(path, "commit", "-qm", f"more {n}")
    assert repo.commits_behind(path, first) == 3


def test_none_for_unknown_sha(tiny_repo):
    path, _ = tiny_repo
    assert repo.commits_behind(path, "deadbeef") is None


def test_none_outside_a_git_repo(tmp_path):
    assert repo.commits_behind(tmp_path, "deadbeef") is None


def test_none_for_empty_sha(tiny_repo):
    path, _ = tiny_repo
    assert repo.commits_behind(path, "") is None
