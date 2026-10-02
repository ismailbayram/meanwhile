import random

import pytest

from waitgame import game
from waitgame.pool import Pool, QuizItem

QUIZ = QuizItem(
    q="What is passport_groups for?",
    choices=["Tags", "Binds passport groups", "Images"],
    answer=1,
    why="Links passport groups to the category.",
    source="apps/products/models.py",
)
QUIZ_2 = QuizItem(
    q="What does the consent flag guard?",
    choices=["Nothing", "A newer-version check"],
    answer=1,
    why="It flags users below the current consent version.",
    source="apps/users/api/services.py",
)


def make_pool(items):
    return Pool(built_at="2026-08-28", head_sha="abc123", repo="demo", items=list(items))


def test_session_starts_at_the_first_item():
    session = game.start_session(make_pool([QUIZ]), rng=random.Random(0))
    assert game.current(session) is QUIZ
    assert session.answered == 0
    assert session.streak == 0


def test_correct_quiz_answer_scores_and_explains():
    session = game.start_session(make_pool([QUIZ]), rng=random.Random(0))
    verdict = game.answer(session, 1)
    assert verdict.correct is True
    assert verdict.explanation == "Links passport groups to the category."
    assert session.correct == 1
    assert session.answered == 1
    assert session.streak == 1


def test_wrong_quiz_answer_still_explains_and_breaks_the_streak():
    session = game.start_session(make_pool([QUIZ, QUIZ]), rng=random.Random(0))
    game.answer(session, 1)
    game.advance(session)
    verdict = game.answer(session, 0)
    assert verdict.correct is False
    assert verdict.explanation == "Links passport groups to the category."
    assert session.correct == 1
    assert session.streak == 0
    assert session.best_streak == 1


def test_answering_twice_without_advancing_is_rejected():
    session = game.start_session(make_pool([QUIZ]), rng=random.Random(0))
    game.answer(session, 1)
    with pytest.raises(game.GameError):
        game.answer(session, 1)


def test_session_finishes_after_the_last_item():
    session = game.start_session(make_pool([QUIZ]), rng=random.Random(0))
    game.answer(session, 1)
    game.advance(session)
    assert game.finished(session) is True
    assert game.current(session) is None


def test_items_are_shuffled_but_the_pool_is_untouched():
    items = [QUIZ, QUIZ_2] * 4
    pool = make_pool(items)
    session = game.start_session(pool, rng=random.Random(7))
    assert sorted(map(id, session.items)) == sorted(map(id, items))
    assert pool.items == items


def test_answering_a_finished_session_is_rejected():
    session = game.start_session(make_pool([QUIZ]), rng=random.Random(0))
    game.answer(session, 1)
    game.advance(session)
    assert game.finished(session) is True
    with pytest.raises(game.GameError):
        game.answer(session, 1)
