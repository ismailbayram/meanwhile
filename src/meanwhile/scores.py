"""Per-developer running totals, and which questions this developer has
answered. Gitignored: both are local, never shared."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .game import Session

SCORES_RELPATH = ".meanwhile/scores.json"
_ZERO = {"answered": 0, "correct": 0, "best_streak": 0}


def _path(repo_dir: str | Path) -> Path:
    return Path(repo_dir) / SCORES_RELPATH


def _read(repo_dir: str | Path) -> dict:
    try:
        data = json.loads(_path(repo_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(repo_dir: str | Path, totals: dict, seen: set[str]) -> None:
    path = _path(repo_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps({**totals, "seen": sorted(seen)}, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_scores(repo_dir: str | Path) -> dict:
    data = _read(repo_dir)
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
    _write(repo_dir, totals, load_seen(repo_dir))
    return totals


def load_seen(repo_dir: str | Path) -> set[str]:
    """The keys (see `game.item_key`) of the questions answered so far."""
    seen = _read(repo_dir).get("seen", [])
    if not isinstance(seen, list):
        return set()
    return {key for key in seen if isinstance(key, str)}


def mark_seen(repo_dir: str | Path, key: str, pool_keys: set[str]) -> set[str]:
    """Remember one answered question, and return what is remembered now.

    Written on every answer rather than at the end of a round: a pane closed
    with its terminal never reaches the end of a round. Once every question in
    the pool has been answered the list starts over, so the next rounds go
    back to a plain shuffle instead of ordering by a list that covers it all.
    Keys of questions no longer in the pool are dropped on the way.
    """
    seen = (load_seen(repo_dir) & pool_keys) | {key}
    if pool_keys <= seen:
        seen = set()
    _write(repo_dir, load_scores(repo_dir), seen)
    return seen
