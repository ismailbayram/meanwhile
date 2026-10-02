"""Reading and validating .waitgame/pool.json.

The pool is produced by an LLM at build time, so every field is treated as
untrusted input: the loader validates shape, not content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

POOL_RELPATH = ".waitgame/pool.json"


class PoolError(Exception):
    """The pool file is missing, unreadable, or structurally invalid."""


@dataclass(frozen=True)
class QuizItem:
    q: str
    choices: list[str]
    answer: int
    why: str
    source: str


@dataclass(frozen=True)
class Pool:
    built_at: str
    head_sha: str
    repo: str
    items: list[QuizItem]
    language: str = "en"


def _require(raw: dict, key: str, kind: type, where: str):
    value = raw.get(key)
    if not isinstance(value, kind):
        raise PoolError(f"{where}: field {key!r} must be {kind.__name__}, got {value!r}")
    return value


def _quiz(raw: dict, where: str) -> QuizItem:
    choices = _require(raw, "choices", list, where)
    if len(choices) < 2:
        raise PoolError(f"{where}: needs at least 2 choices, got {len(choices)}")
    if not all(isinstance(c, str) and c for c in choices):
        raise PoolError(f"{where}: every entry in choices must be a non-empty string")
    answer = _require(raw, "answer", int, where)
    if not 0 <= answer < len(choices):
        raise PoolError(f"{where}: answer {answer} is out of range for {len(choices)} choices")
    return QuizItem(
        q=_require(raw, "q", str, where),
        choices=choices,
        answer=answer,
        why=_require(raw, "why", str, where),
        source=_require(raw, "source", str, where),
    )


def load_pool(path: str | Path) -> Pool:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PoolError(f"pool not found at {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PoolError(f"pool at {path} is unreadable: {exc}") from exc

    if not isinstance(raw, dict):
        raise PoolError("pool must be a JSON object")

    raw_items = raw.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise PoolError("pool 'items' is empty or not a list")

    items = []
    for index, entry in enumerate(raw_items):
        where = f"item {index}"
        if not isinstance(entry, dict):
            raise PoolError(f"{where}: must be an object")
        kind = entry.get("type")
        if kind == "quiz":
            items.append(_quiz(entry, where))
        elif kind == "mutant":
            raise PoolError(
                f"{where}: mutant cards were removed in 0.2.0 — "
                "regenerate this pool with the build command"
            )
        else:
            raise PoolError(f"{where}: unknown type {kind!r}")

    return Pool(
        built_at=str(raw.get("builtAt", "")),
        head_sha=str(raw.get("headSha", "")),
        repo=str(raw.get("repo", "")),
        items=items,
        language=str(raw.get("language", "en")) or "en",
    )
