import json

import pytest

from waitgame import pool as pool_mod

GOOD = {
    "builtAt": "2026-08-28",
    "headSha": "3b7278e",
    "repo": "trumy",
    "items": [
        {
            "type": "quiz",
            "q": "What is Category.passport_groups for?",
            "choices": ["Tags a category", "Binds passport groups", "Stores images"],
            "answer": 1,
            "why": "Links passport groups to the category.",
            "source": "apps/products/models.py",
        },
    ],
}


def write(tmp_path, data):
    path = tmp_path / "pool.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_loads_a_quiz_item(tmp_path):
    loaded = pool_mod.load_pool(write(tmp_path, GOOD))
    assert loaded.head_sha == "3b7278e"
    assert loaded.repo == "trumy"
    assert isinstance(loaded.items[0], pool_mod.QuizItem)
    assert loaded.items[0].answer == 1


def test_missing_file_raises_pool_error(tmp_path):
    with pytest.raises(pool_mod.PoolError, match="not found"):
        pool_mod.load_pool(tmp_path / "absent.json")


def test_answer_index_out_of_range_raises(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["items"][0]["answer"] = 5
    with pytest.raises(pool_mod.PoolError, match="answer"):
        pool_mod.load_pool(write(tmp_path, bad))


def test_quiz_needs_at_least_two_choices(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["items"][0]["choices"] = ["only one"]
    bad["items"][0]["answer"] = 0
    with pytest.raises(pool_mod.PoolError, match="choices"):
        pool_mod.load_pool(write(tmp_path, bad))


def test_unknown_item_type_raises(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["items"].append({"type": "crossword"})
    with pytest.raises(pool_mod.PoolError, match="crossword"):
        pool_mod.load_pool(write(tmp_path, bad))


def test_empty_pool_raises(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["items"] = []
    with pytest.raises(pool_mod.PoolError, match="empty"):
        pool_mod.load_pool(write(tmp_path, bad))


def test_a_json_root_that_is_not_an_object_raises(tmp_path):
    with pytest.raises(pool_mod.PoolError, match="JSON object"):
        pool_mod.load_pool(write(tmp_path, ["not", "an", "object"]))


def test_an_item_that_is_not_an_object_raises(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["items"].append("just a string")
    with pytest.raises(pool_mod.PoolError, match="item 1: must be an object"):
        pool_mod.load_pool(write(tmp_path, bad))


def test_a_pool_containing_mutants_says_how_to_fix_it(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["items"].append(
        {"type": "mutant", "lang": "python", "snippet": "x = 1", "clean": True, "bug": "", "source": "real.py"}
    )
    with pytest.raises(pool_mod.PoolError) as excinfo:
        pool_mod.load_pool(write(tmp_path, bad))
    message = str(excinfo.value)
    assert "0.2.0" in message
    assert "regenerate" in message.lower()


def test_an_unreadable_pool_path_raises(tmp_path):
    """Anything OSError-shaped that is not a missing file — here the pool path
    is a directory — reports as unreadable rather than escaping as an OSError."""
    directory = tmp_path / "pool.json"
    directory.mkdir()
    with pytest.raises(pool_mod.PoolError, match="unreadable"):
        pool_mod.load_pool(directory)


def test_language_defaults_to_english_when_absent(tmp_path):
    assert pool_mod.load_pool(write(tmp_path, GOOD)).language == "en"


def test_language_is_read_from_the_pool(tmp_path):
    data = json.loads(json.dumps(GOOD))
    data["language"] = "tr"
    assert pool_mod.load_pool(write(tmp_path, data)).language == "tr"
