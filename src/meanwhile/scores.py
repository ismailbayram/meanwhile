"""Per-developer running totals. Gitignored: scores are local, never shared."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .game import Session

SCORES_RELPATH = ".meanwhile/scores.json"
_ZERO = {"answered": 0, "correct": 0, "best_streak": 0}


def _path(repo_dir: str | Path) -> Path:
    return Path(repo_dir) / SCORES_RELPATH


def load_scores(repo_dir: str | Path) -> dict:
    try:
        data = json.loads(_path(repo_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_ZERO)
    if not isinstance(data, dict):
        return dict(_ZERO)
    out = dict(_ZERO)
    for key in out:
        value = data.get(key, 0)
        out[key] = value if isinstance(value, int) and value >= 0 else 0
    return out


def record_session(repo_dir: str | Path, session: Session) -> dict:
    totals = load_scores(repo_dir)
    totals["answered"] += session.answered
    totals["correct"] += session.correct
    totals["best_streak"] = max(totals["best_streak"], session.best_streak)

    path = _path(repo_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(totals, indent=2), encoding="utf-8")
    tmp.replace(path)
    return totals
