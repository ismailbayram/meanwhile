"""Scoring rules. No I/O here — the TUI renders what these functions return."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

from .pool import Pool


class GameError(Exception):
    """The caller drove the session into an impossible state."""


@dataclass(frozen=True)
class Verdict:
    correct: bool
    explanation: str


@dataclass
class Session:
    items: list
    index: int = 0
    correct: int = 0
    answered: int = 0
    streak: int = 0
    best_streak: int = 0
    # Bookkeeping, not part of the session's identity: keep it out of
    # __init__, __repr__ and __eq__.
    _answered_index: int = field(default=-1, init=False, repr=False, compare=False)


def item_key(item) -> str:
    """A stable name for a question, for remembering it was answered.

    The question text, not the item's position: a rebuilt or extended pool
    reorders items, and a question that survives a rebuild word for word is
    the same question to the player.
    """
    return hashlib.sha256(item.q.encode("utf-8")).hexdigest()[:16]


def start_session(
    pool: Pool, rng: random.Random | None = None, seen: frozenset[str] | set[str] = frozenset()
) -> Session:
    """A shuffled round over the whole pool, questions not in `seen` first."""
    rng = rng or random.Random()
    fresh = [item for item in pool.items if item_key(item) not in seen]
    repeats = [item for item in pool.items if item_key(item) in seen]
    rng.shuffle(fresh)
    rng.shuffle(repeats)
    return Session(items=fresh + repeats)


def finished(session: Session) -> bool:
    return session.index >= len(session.items)


def current(session: Session):
    if finished(session):
        return None
    return session.items[session.index]


def advance(session: Session) -> None:
    session.index += 1


def answer(session: Session, response: int) -> Verdict:
    item = current(session)
    if item is None:
        raise GameError("session is finished")
    if session._answered_index == session.index:
        raise GameError("this item has already been answered; call advance() first")

    session._answered_index = session.index
    session.answered += 1
    correct = response == item.answer
    if correct:
        session.correct += 1
        session.streak += 1
        session.best_streak = max(session.best_streak, session.streak)
    else:
        session.streak = 0
    return Verdict(correct=correct, explanation=item.why)
