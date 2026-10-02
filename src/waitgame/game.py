"""Scoring rules. No I/O here — the TUI renders what these functions return."""

from __future__ import annotations

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


def start_session(pool: Pool, rng: random.Random | None = None) -> Session:
    items = list(pool.items)
    (rng or random.Random()).shuffle(items)
    return Session(items=items)


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
