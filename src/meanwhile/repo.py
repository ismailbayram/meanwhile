"""How far the committed pool has drifted from the working tree."""

from __future__ import annotations

import subprocess
from pathlib import Path

STALE_THRESHOLD = 50


def commits_behind(repo_dir: str | Path, head_sha: str) -> int | None:
    """Commits added since the pool was built, or None if that cannot be known."""
    if not head_sha:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{head_sha}..HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None
