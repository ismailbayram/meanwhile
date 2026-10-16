from meanwhile import scores
from meanwhile.game import Session


def test_missing_file_reads_as_zeroes(tmp_path):
    assert scores.load_scores(tmp_path) == {"answered": 0, "correct": 0, "best_streak": 0}


def test_corrupt_file_reads_as_zeroes(tmp_path):
    (tmp_path / ".meanwhile").mkdir()
    (tmp_path / scores.SCORES_RELPATH).write_text("nonsense")
    assert scores.load_scores(tmp_path) == {"answered": 0, "correct": 0, "best_streak": 0}


def test_recording_a_session_accumulates(tmp_path):
    first = scores.record_session(tmp_path, Session(items=[], answered=4, correct=3, best_streak=2))
    assert first == {"answered": 4, "correct": 3, "best_streak": 2}
    second = scores.record_session(tmp_path, Session(items=[], answered=2, correct=2, best_streak=5))
    assert second == {"answered": 6, "correct": 5, "best_streak": 5}
    assert scores.load_scores(tmp_path) == second


def test_best_streak_never_regresses(tmp_path):
    scores.record_session(tmp_path, Session(items=[], answered=3, correct=3, best_streak=9))
    after = scores.record_session(tmp_path, Session(items=[], answered=1, correct=0, best_streak=1))
    assert after["best_streak"] == 9


def test_an_unplayed_session_writes_nothing_new(tmp_path):
    scores.record_session(tmp_path, Session(items=[], answered=2, correct=1, best_streak=1))
    unchanged = scores.record_session(tmp_path, Session(items=[]))
    assert unchanged == {"answered": 2, "correct": 1, "best_streak": 1}


def test_seen_questions_are_remembered_across_loads(tmp_path):
    scores.mark_seen(tmp_path, "a", {"a", "b", "c"})
    scores.mark_seen(tmp_path, "b", {"a", "b", "c"})
    assert scores.load_seen(tmp_path) == {"a", "b"}


def test_seen_starts_over_once_the_whole_pool_is_answered(tmp_path):
    scores.mark_seen(tmp_path, "a", {"a", "b"})
    assert scores.mark_seen(tmp_path, "b", {"a", "b"}) == set()
    assert scores.load_seen(tmp_path) == set()


def test_seen_drops_questions_that_left_the_pool(tmp_path):
    scores.mark_seen(tmp_path, "gone", {"gone", "x", "y"})
    assert scores.mark_seen(tmp_path, "x", {"x", "y"}) == {"x"}


def test_totals_and_seen_do_not_overwrite_each_other(tmp_path):
    scores.mark_seen(tmp_path, "a", {"a", "b"})
    scores.record_session(tmp_path, Session(items=[], answered=1, correct=1, best_streak=1))
    assert scores.load_seen(tmp_path) == {"a"}
    scores.mark_seen(tmp_path, "b", {"a", "b", "c"})
    assert scores.load_scores(tmp_path) == {"answered": 1, "correct": 1, "best_streak": 1}


def test_a_malformed_seen_list_reads_as_empty(tmp_path):
    (tmp_path / ".meanwhile").mkdir()
    (tmp_path / scores.SCORES_RELPATH).write_text('{"answered": 1, "seen": "nope"}')
    assert scores.load_seen(tmp_path) == set()
    assert scores.load_scores(tmp_path)["answered"] == 1
