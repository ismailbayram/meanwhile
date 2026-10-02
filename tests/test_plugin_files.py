"""The plugin's non-Python surface: the build prompt and the two manifests.

`src/waitgame/build_prompt.md` is what an LLM follows to write pool.json, so
its example is a contract with `waitgame.pool.load_pool`. It is also the one
place that text lives: `commands/waitgame-build.md` is a thin wrapper that
points Claude Code at it, and `waitgame build-prompt` prints it for any other
agent. Nothing else checks the example, and a mismatch would only surface in
a user's first (paid-for) build.
"""

import json
import re
import textwrap
from pathlib import Path

import pytest

import waitgame
from waitgame import cli
from waitgame.pool import QuizItem, load_pool

ROOT = Path(__file__).resolve().parents[1]
BUILD_COMMAND = ROOT / "commands" / "waitgame-build.md"
PROMPT_SOURCE = ROOT / "src" / "waitgame" / "build_prompt.md"
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = ROOT / ".claude-plugin" / "marketplace.json"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"

# The one placeholder in the example that is not a JSON string. Every other
# `<...>` is already quoted, so it survives json.loads untouched — which is
# what lets this test pin the field *names* without inventing content.
NON_STRING_PLACEHOLDERS = {"answer": "0"}


def example_pool_text() -> str:
    """The indented JSON block from the prompt source, placeholders filled in."""
    lines = PROMPT_SOURCE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "{")
    end = start
    while end + 1 < len(lines) and (lines[end + 1].startswith("    ") or not lines[end + 1].strip()):
        end += 1
    block = textwrap.dedent("\n".join(lines[start : end + 1]))
    return re.sub(
        r'"(answer)":\s*<[^>]*>',
        lambda m: f'"{m.group(1)}": {NON_STRING_PLACEHOLDERS[m.group(1)]}',
        block,
    )


@pytest.fixture
def example() -> dict:
    return json.loads(example_pool_text())


def test_the_example_pool_in_the_prompt_source_loads(tmp_path, example):
    path = tmp_path / "pool.json"
    path.write_text(json.dumps(example), encoding="utf-8")

    pool = load_pool(path)

    (quiz,) = pool.items
    assert isinstance(quiz, QuizItem)
    # Values, not just types: this pins the example's field names to the
    # loader's, so renaming one on either side fails here.
    assert quiz.q == example["items"][0]["q"]
    assert quiz.choices == example["items"][0]["choices"]
    assert quiz.why == example["items"][0]["why"]
    assert quiz.source == example["items"][0]["source"]
    assert pool.built_at == example["builtAt"]
    assert pool.head_sha == example["headSha"]
    assert pool.repo == example["repo"]
    # Pins the new `language` key the same way: the envelope must carry it,
    # and the loader must actually read it into Pool.language, not just
    # tolerate it silently defaulting to English.
    assert pool.language == example["language"]


def test_the_example_pool_carries_exactly_the_fields_the_loader_reads(example):
    assert set(example) == {"builtAt", "headSha", "repo", "language", "items"}
    assert set(example["items"][0]) == {"type", "q", "choices", "answer", "why", "source"}


def test_the_build_command_forbids_secret_and_ignored_files():
    text = PROMPT_SOURCE.read_text(encoding="utf-8")
    assert ".env" in text
    assert ".gitignore" in text


def test_the_slash_command_delegates_rather_than_duplicating():
    body = BUILD_COMMAND.read_text(encoding="utf-8")
    assert "build_prompt.md" in body
    assert '"type": "quiz"' not in body, "the JSON shape must live in one file only"


def test_build_prompt_substitutes_the_language_and_repo():
    out = cli.build_prompt(language="tr", repo_name="trumy")
    other = cli.build_prompt(language="en", repo_name="trumy")

    assert "trumy" in out
    # The bare "tr" check that used to stand here can't tell a real
    # substitution from a dropped one: build_prompt.md already contains "tr"
    # incidentally, in "files that are tracked in git". Assert the whole
    # rendered sentence instead, and that it actually differs from another
    # language's rendering — a substitution that dropped the value would
    # make both renderings identical, which the bare check could not catch.
    assert "Write the questions in tr." in out
    assert "Write the questions in tr." not in other
    assert out != other
    assert "{language}" not in out and "{repo}" not in out


def test_the_manifests_name_an_author_and_a_description():
    plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    marketplace = json.loads(MARKETPLACE_MANIFEST.read_text(encoding="utf-8"))

    assert plugin["author"]["name"]
    assert marketplace["description"]
    # The two are a stranger's first impression of the same plugin: keep them
    # saying the same thing.
    assert plugin["author"] == marketplace["owner"]
    assert plugin["description"] == marketplace["description"]


def test_the_language_is_asked_for_as_a_code_and_the_two_shipped_ones_are_named():
    """`--lang` and the pool's `language` field are matched against `tr` and
    `en`; anything else falls back to English without a word. Every place that
    asks for a language therefore has to say it wants a code, and which two the
    interface speaks — a reader told "use English unless the user asked for
    another one" writes "Turkish" and gets an English interface, silently.
    `--lang`'s own help text is pinned in tests/test_cli.py."""
    for path in (PROMPT_SOURCE, BUILD_COMMAND, README):
        body = path.read_text(encoding="utf-8")
        assert "language code" in body, path
        assert "`tr`" in body and "`en`" in body, path


def test_every_version_in_the_repository_agrees():
    """Four files carry a version and nothing pins them together. The
    marketplace one is the plugin-update signal: a missed bump there means
    everyone who installed the plugin silently never updates."""
    pyproject = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert pyproject, "pyproject.toml declares no version"
    plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    marketplace = json.loads(MARKETPLACE_MANIFEST.read_text(encoding="utf-8"))

    versions = {
        "pyproject.toml": pyproject.group(1),
        "waitgame.__version__": waitgame.__version__,
        "plugin.json": plugin["version"],
        "marketplace.json": marketplace["plugins"][0]["version"],
    }

    assert len(set(versions.values())) == 1, versions
