import pytest

from meanwhile import strings


@pytest.mark.parametrize("language", ["en", "tr"])
def test_every_key_exists_in_every_shipped_language(language):
    for key in strings.KEYS:
        assert strings.text(language, key, agent="Codex", behind=60)


def test_an_unknown_language_falls_back_to_english():
    assert strings.text("de", "done", agent="Codex") == strings.text("en", "done", agent="Codex")


def test_turkish_and_english_differ():
    assert strings.text("tr", "waiting", agent="Codex") != strings.text("en", "waiting", agent="Codex")


def test_the_agent_name_is_substituted():
    assert "Codex" in strings.text("en", "done", agent="Codex")
    assert "Codex" in strings.text("tr", "done", agent="Codex")


def test_an_unknown_key_is_a_programming_error():
    with pytest.raises(KeyError):
        strings.text("en", "no-such-key")
