# Multi-Agent Support, Language, and Mutant Removal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop the mutant card type, make waitgame work with Codex and Cursor as well as Claude Code, and let a pool declare the language its cards are written in.

**Architecture:** The busy/idle signal was never Claude-specific — Codex and Cursor expose the same two moments — so nothing about the state file or the bash hook changes shape. What is new is a small adapter registry that knows each agent's registration file and its JSON shape, a `waitgame hooks` command that merges our entries into that file without disturbing anyone else's, and an agent slug carried through the state file so the pane can name the agent that is actually running. The mutant type is deleted outright, and a six-string table gives the interface a Turkish reading.

**Tech Stack:** Python 3.10+, Textual 8.2.8, pytest, bash (hooks), `uv`.

**Spec:** `docs/superpowers/specs/2026-09-02-multi-agent-and-language-design.md`

## Global Constraints

- Python floor: `3.10`. No syntax or stdlib APIs newer than 3.10.
- Runtime dependencies: `textual>=0.80` only. No new runtime dependency. `pytest` and `pytest-asyncio` are dev-only.
- The hook stays **pure bash** — no Python, no interpreter, no network. It runs on every prompt submit.
- Agent slugs: `claude`, `codex`, `cursor`. Labels: `Claude Code`, `Codex`, `Cursor`.
- Slug validation, in bash and Python alike: `^[a-z][a-z-]{0,15}$`.
- State file: `~/.waitgame/state/<key>.json`, key = first 16 hex chars of the SHA-256 of the resolved launch directory. Payload gains `"agent"`; `"status"` and `"ts"` keep their meaning.
- Pool: `.waitgame/pool.json`, gains top-level `"language"`, defaults to `"en"` when absent.
- Languages shipped: `tr` and `en`. An unknown language falls back to English.
- Installed hook script path: `~/.waitgame/waitgame-state.sh`, mode `0755`.
- Cursor is project-scope only; `--user` for Cursor is an error, not a silent no-op.
- Package version becomes `0.2.0` (the pool format changes incompatibly).
- **Agents must not run `git commit`.** Each task's commit step gives the message; stage the files, print the message, and let the repo owner commit.

---

### Task 1: Remove mutant cards

The mechanic goes entirely: the item type, its loader branch, its scoring branch, its keys and its rendering. A committed pool that still contains mutants must fail with a message that says what to do, because that pool is out there.

**Files:**
- Modify: `src/waitgame/pool.py` (delete `MutantItem` and `_mutant`, change the unknown-type branch)
- Modify: `src/waitgame/game.py` (delete `CLEAN_EXPLANATION` and the `MutantItem` branch; `answer` takes `int`)
- Modify: `src/waitgame/app.py` (delete `c`/`b` bindings, `action_clean`, `action_bugged`, `_mutant_answer`, the mutant branch of `check_action`, the mutant branch of `_render`)
- Modify: `commands/waitgame-build.md` (delete the mutant template entry and the mutant rules)
- Test: `tests/test_pool.py`, `tests/test_game.py`, `tests/test_app.py`, `tests/test_plugin_files.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `waitgame.pool.QuizItem`, `Pool(built_at, head_sha, repo, items: list[QuizItem])`
  - `waitgame.game.answer(session: Session, response: int) -> Verdict`
  - `MutantItem`, `CLEAN_EXPLANATION`, `WaitgameApp.action_clean`, `action_bugged` no longer exist

- [ ] **Step 1: Write the failing test for the migration message**

Add to `tests/test_pool.py`:

```python
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
```

- [ ] **Step 2: Run it and verify it fails**

Run: `uv run python -m pytest tests/test_pool.py::test_a_pool_containing_mutants_says_how_to_fix_it -v`
Expected: FAIL — the pool loads the mutant instead of raising.

- [ ] **Step 3: Delete the mutant type from the loader**

In `src/waitgame/pool.py`: remove the `MutantItem` dataclass and the whole `_mutant` function, change `Pool.items` to `list[QuizItem]`, and replace the type dispatch at the end of `load_pool` with:

```python
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
```

- [ ] **Step 4: Delete the mutant branch from the scoring rules**

In `src/waitgame/game.py`: remove the `CLEAN_EXPLANATION` constant and the `MutantItem` import, and reduce `answer` to:

```python
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
```

- [ ] **Step 5: Delete the mutant surface from the app**

In `src/waitgame/app.py`: drop `("c", ...)` and `("b", ...)` from `BINDINGS`; narrow `CARD_ACTIONS` to `("choose",)`; delete `action_clean`, `action_bugged` and `_mutant_answer`; drop the `MutantItem` import. `check_action`'s card branch becomes:

```python
        if self.phase != PLAYING:
            return False
        item = game.current(self.session)
        return isinstance(item, QuizItem) and 1 <= int(parameters[0]) <= len(item.choices)
```

and `_render`'s `else:` branch (the "Is this code correct?" card) goes, leaving the `item is None` and `QuizItem` branches.

- [ ] **Step 6: Strip the mutant half out of the build command**

In `commands/waitgame-build.md`: delete the `mutant` object from the JSON template and the entire "Rules for mutants" section, keeping the secrets rule (it applies to quiz sources too — move it under a "Rules" heading). Change the item guidance to ask for 30-50 quiz items.

- [ ] **Step 7: Update the tests that referenced mutants**

Delete every mutant fixture and test from `tests/test_pool.py`, `tests/test_game.py`, `tests/test_app.py` and `tests/test_plugin_files.py` — including `test_a_mutant_card_offers_c_and_b_and_no_digits`, `test_number_key_does_not_score_a_mutant_card`, `test_clean_and_bugged_keys_do_not_score_a_quiz_card`, and the `MutantItem` half of the build-command contract test. Where a deleted test also proved something still true (a quiz card offers exactly its own digits; the handler guard refuses an out-of-range choice), keep that half rather than deleting the whole test.

- [ ] **Step 8: Run the full suite**

Run: `uv run python -m pytest -v`
Expected: PASS. The count drops — record the new number in your report.

- [ ] **Step 9: Stage and report the commit message**

```bash
git add -A
# feat!: remove mutant cards, leaving one card type
```

---

### Task 2: The agent registry

Pure data and pure functions: which agents exist, where each one registers hooks, and how to fold our entries into that file without touching anyone else's. No CLI, no filesystem writes — those are Task 5.

**Files:**
- Create: `src/waitgame/agents.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `waitgame.agents.Agent` — frozen dataclass with `slug`, `label`, `busy_event`, `idle_event`, `shape`, `project_relpath`, `user_relpath`, `supports_user_scope`
  - `waitgame.agents.AGENTS: tuple[Agent, ...]`
  - `waitgame.agents.agent_by_slug(slug: str) -> Agent | None`
  - `waitgame.agents.label_for(slug: str | None) -> str | None`
  - `waitgame.agents.SLUG_PATTERN: re.Pattern`
  - `waitgame.agents.merge(document: dict, agent: Agent, script: str) -> dict`
  - `waitgame.agents.unmerge(document: dict, agent: Agent) -> dict`
  - `waitgame.agents.registered_commands(document: dict, agent: Agent) -> list[str]`
  - `waitgame.agents.MARKER: str` — `"waitgame-state.sh"`, how our entries are recognised

- [ ] **Step 1: Write the failing tests**

`tests/test_agents.py`:

```python
import copy
import re

import pytest

from waitgame import agents

SCRIPT = "/home/x/.waitgame/waitgame-state.sh"


def test_every_agent_has_a_distinct_slug_and_a_label():
    slugs = [a.slug for a in agents.AGENTS]
    assert sorted(slugs) == ["claude", "codex", "cursor"]
    assert len(set(slugs)) == len(slugs)
    assert all(a.label and agents.SLUG_PATTERN.match(a.slug) for a in agents.AGENTS)


def test_cursor_refuses_user_scope_and_the_others_allow_it():
    scopes = {a.slug: a.supports_user_scope for a in agents.AGENTS}
    assert scopes == {"claude": True, "codex": True, "cursor": False}


def test_label_for_known_and_unknown_slugs():
    assert agents.label_for("codex") == "Codex"
    assert agents.label_for("nope") is None
    assert agents.label_for(None) is None


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_merge_into_an_empty_document_registers_both_events(slug):
    agent = agents.agent_by_slug(slug)
    document = agents.merge({}, agent, SCRIPT)
    commands = agents.registered_commands(document, agent)
    assert len(commands) == 2
    assert any(c.endswith(f"busy {slug}") for c in commands)
    assert any(c.endswith(f"idle {slug}") for c in commands)
    assert all(SCRIPT in c for c in commands)


def test_cursor_documents_carry_the_version_field():
    document = agents.merge({}, agents.agent_by_slug("cursor"), SCRIPT)
    assert document["version"] == 1


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_merge_preserves_another_tools_hooks(slug):
    agent = agents.agent_by_slug(slug)
    theirs = {
        "hooks": {agent.busy_event: [{"command": "their-script.sh"}]},
        "somethingElse": {"keep": True},
    }
    before = copy.deepcopy(theirs)
    document = agents.merge(theirs, agent, SCRIPT)
    assert document["somethingElse"] == {"keep": True}
    assert json_contains(document, "their-script.sh")
    assert theirs == before, "merge must not mutate its argument"


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_merging_twice_does_not_duplicate(slug):
    agent = agents.agent_by_slug(slug)
    once = agents.merge({}, agent, SCRIPT)
    twice = agents.merge(once, agent, SCRIPT)
    assert agents.registered_commands(twice, agent) == agents.registered_commands(once, agent)


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_merging_a_new_script_path_replaces_the_old_entry(slug):
    agent = agents.agent_by_slug(slug)
    old = agents.merge({}, agent, "/old/waitgame-state.sh")
    new = agents.merge(old, agent, SCRIPT)
    commands = agents.registered_commands(new, agent)
    assert len(commands) == 2
    assert all(SCRIPT in c for c in commands)


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_unmerge_removes_only_our_entries(slug):
    agent = agents.agent_by_slug(slug)
    theirs = {"hooks": {agent.busy_event: [{"command": "their-script.sh"}]}}
    document = agents.unmerge(agents.merge(theirs, agent, SCRIPT), agent)
    assert agents.registered_commands(document, agent) == []
    assert json_contains(document, "their-script.sh")


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_unmerge_leaves_no_empty_event_behind(slug):
    agent = agents.agent_by_slug(slug)
    document = agents.unmerge(agents.merge({}, agent, SCRIPT), agent)
    assert not document.get("hooks")


def json_contains(document, needle: str) -> bool:
    import json

    return needle in json.dumps(document)
```

- [ ] **Step 2: Run them and verify they fail**

Run: `uv run python -m pytest tests/test_agents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'waitgame.agents'`

- [ ] **Step 3: Implement `agents.py`**

```python
"""Which agents waitgame can hook into, and how each one registers hooks.

The busy/idle signal is not Claude-specific: Codex and Cursor expose the same
two moments under different names, and the same bash script serves all three.
Only the registration file and its JSON shape differ, so that is all this
module knows about.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

#: How our entries are recognised inside somebody else's config file. Matching
#: on the script name rather than on an exact command string is what lets
#: `merge` replace an entry that points at an older copy of the script.
MARKER = "waitgame-state.sh"

SLUG_PATTERN = re.compile(r"^[a-z][a-z-]{0,15}$")


@dataclass(frozen=True)
class Agent:
    slug: str
    label: str
    busy_event: str
    idle_event: str
    #: Which config shape this agent's file uses: "claude" (a "hooks" map of
    #: event -> [{"hooks": [{"type": "command", ...}]}], shared with Codex) or
    #: "cursor" (a versioned "hooks" map of event -> [{"command": ...}]).
    shape: str
    project_relpath: str
    user_relpath: str
    supports_user_scope: bool


AGENTS: tuple[Agent, ...] = (
    Agent(
        slug="claude",
        label="Claude Code",
        busy_event="UserPromptSubmit",
        idle_event="Stop",
        shape="claude",
        # Not hooks.json: a standalone (non-plugin) Claude Code registration
        # lives in settings.json alongside unrelated settings, which is why
        # the merge only ever touches document["hooks"].
        project_relpath=".claude/settings.json",
        user_relpath=".claude/settings.json",
        supports_user_scope=True,
    ),
    Agent(
        slug="codex",
        label="Codex",
        busy_event="UserPromptSubmit",
        idle_event="Stop",
        shape="claude",
        project_relpath=".codex/hooks.json",
        user_relpath=".codex/hooks.json",
        supports_user_scope=True,
    ),
    Agent(
        slug="cursor",
        label="Cursor",
        busy_event="beforeSubmitPrompt",
        idle_event="stop",
        shape="cursor",
        project_relpath=".cursor/hooks.json",
        user_relpath=".cursor/hooks.json",
        # Cursor runs user-level hooks from ~/.cursor/ rather than from the
        # project root, and the script keys the state file on its working
        # directory — so a user-level registration would key the wrong
        # directory and the pane would simply never wake.
        supports_user_scope=False,
    ),
)


def agent_by_slug(slug: str) -> Agent | None:
    for agent in AGENTS:
        if agent.slug == slug:
            return agent
    return None


def label_for(slug: str | None) -> str | None:
    agent = agent_by_slug(slug) if slug else None
    return agent.label if agent else None


def command_for(script: str, agent: Agent, status: str) -> str:
    return f'"{script}" {status} {agent.slug}'


def _entry(command: str, shape: str) -> dict:
    if shape == "cursor":
        return {"command": command}
    return {"hooks": [{"type": "command", "command": command, "timeout": 5}]}


def _commands_in(entry: dict) -> list[str]:
    if "command" in entry:
        return [entry["command"]]
    return [h.get("command", "") for h in entry.get("hooks", []) if isinstance(h, dict)]


def _is_ours(entry: dict) -> bool:
    return any(MARKER in command for command in _commands_in(entry))


def merge(document: dict, agent: Agent, script: str) -> dict:
    """Our two entries, folded into a copy of `document`.

    Idempotent, and safe on a file that already holds other tools' hooks:
    every entry that is not ours is carried through untouched, and ours are
    rewritten rather than appended so a changed script path replaces the old
    registration instead of doubling it.
    """
    out = copy.deepcopy(document)
    if agent.shape == "cursor":
        out.setdefault("version", 1)
    hooks = out.setdefault("hooks", {})
    for status, event in (("busy", agent.busy_event), ("idle", agent.idle_event)):
        kept = [e for e in hooks.get(event, []) if not (isinstance(e, dict) and _is_ours(e))]
        hooks[event] = kept + [_entry(command_for(script, agent, status), agent.shape)]
    return out


def unmerge(document: dict, agent: Agent) -> dict:
    """A copy of `document` with our entries — and only ours — taken out."""
    out = copy.deepcopy(document)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event in (agent.busy_event, agent.idle_event):
        kept = [e for e in hooks.get(event, []) if not (isinstance(e, dict) and _is_ours(e))]
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        out.pop("hooks", None)
    return out


def registered_commands(document: dict, agent: Agent) -> list[str]:
    """Every command string of ours in `document`, in busy-then-idle order."""
    found = []
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return found
    for event in (agent.busy_event, agent.idle_event):
        for entry in hooks.get(event, []):
            if isinstance(entry, dict) and _is_ours(entry):
                found.extend(c for c in _commands_in(entry) if MARKER in c)
    return found
```

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_agents.py -v`
Expected: PASS, 13 tests (the parametrized ones count once per agent).

- [ ] **Step 5: Stage and report the commit message**

```bash
git add src/waitgame/agents.py tests/test_agents.py
# feat: add the agent registry and hook-file merging
```

---

### Task 3: The state file names the agent

`Claude is done ^` is false for a Codex user. The hook takes the slug as a second argument and the state file carries it.

**Files:**
- Modify: `hooks/waitgame-state.sh` (accept and validate an optional second argument, write it)
- Modify: `hooks/hooks.json` (pass `claude`)
- Modify: `src/waitgame/state.py` (`write_state` takes `agent`; `read_state` returns it)
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `waitgame.agents.SLUG_PATTERN` (Task 2)
- Produces:
  - `waitgame.state.write_state(project_dir, status, root=STATE_ROOT, now=None, agent=None) -> Path`
  - `waitgame.state.read_state(...) -> dict` with keys `status`, `ts`, `agent` (`str | None`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_state.py`:

```python
def test_write_and_read_round_trip_the_agent(tmp_path):
    root = tmp_path / "state"
    state.write_state(tmp_path, "busy", root=root, now=1.0, agent="codex")
    assert state.read_state(tmp_path, root=root) == {"status": "busy", "ts": 1.0, "agent": "codex"}


def test_agent_is_none_when_not_written(tmp_path):
    root = tmp_path / "state"
    state.write_state(tmp_path, "busy", root=root, now=1.0)
    assert state.read_state(tmp_path, root=root)["agent"] is None


def test_a_state_file_written_before_agents_existed_reads_as_none(tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    state.state_path(tmp_path, root=root).write_text('{"status":"busy","ts":1}', encoding="utf-8")
    assert state.read_state(tmp_path, root=root)["agent"] is None


def test_write_state_rejects_a_malformed_agent(tmp_path):
    with pytest.raises(ValueError):
        state.write_state(tmp_path, "busy", root=tmp_path / "state", agent="Not A Slug")


def test_read_state_ignores_a_malformed_agent_on_disk(tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    state.state_path(tmp_path, root=root).write_text(
        '{"status":"busy","ts":1,"agent":"../etc"}', encoding="utf-8"
    )
    assert state.read_state(tmp_path, root=root)["agent"] is None


def test_the_hook_writes_the_agent_slug(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    run_hook(home, project, "busy", "cursor")
    written = home / ".waitgame" / "state" / f"{state.project_key(project)}.json"
    assert json.loads(written.read_text())["agent"] == "cursor"


def test_the_hook_refuses_a_malformed_agent_slug(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    result = run_hook(home, project, "busy", "Not A Slug", check=False)
    assert result.returncode != 0
    assert not (home / ".waitgame" / "state").exists()
```

`run_hook` is the existing helper in this file; extend it to take optional extra arguments and a `check` flag rather than writing a second one.

- [ ] **Step 2: Run them and verify they fail**

Run: `uv run python -m pytest tests/test_state.py -v`
Expected: FAIL — `write_state() got an unexpected keyword argument 'agent'`.

- [ ] **Step 3: Teach the bash hook the second argument**

In `hooks/waitgame-state.sh`, after the status `case`:

```bash
# Optional second argument: which agent is running. Validated rather than
# interpolated blind — this string ends up inside a JSON document.
agent="${2:-}"
if [ -n "$agent" ] && ! printf '%s' "$agent" | grep -Eq '^[a-z][a-z-]{0,15}$'; then
  printf 'waitgame-state.sh: agent must match ^[a-z][a-z-]{0,15}$, got %s\n' "$agent" >&2
  exit 1
fi
```

and replace the write with:

```bash
if [ -n "$agent" ]; then
  printf '{"status":"%s","ts":%s,"agent":"%s"}' "$status" "$(date +%s)" "$agent" > "$tmp"
else
  printf '{"status":"%s","ts":%s}' "$status" "$(date +%s)" > "$tmp"
fi
```

- [ ] **Step 4: Pass `claude` from the plugin's registration**

In `hooks/hooks.json`, both commands gain the slug: `"\"${CLAUDE_PLUGIN_ROOT}/hooks/waitgame-state.sh\" busy claude"` and `... idle claude`.

- [ ] **Step 5: Carry the agent through `state.py`**

```python
from .agents import SLUG_PATTERN

_IDLE = {"status": "idle", "ts": 0.0, "agent": None}


def write_state(project_dir, status, root=STATE_ROOT, now=None, agent=None):
    if status not in _VALID:
        raise ValueError(f"status must be one of {_VALID}, got {status!r}")
    if agent is not None and not SLUG_PATTERN.match(agent):
        raise ValueError(f"agent must match {SLUG_PATTERN.pattern}, got {agent!r}")
    ...
    payload_data = {"status": status, "ts": now if now is not None else time.time()}
    if agent is not None:
        payload_data["agent"] = agent
    payload = json.dumps(payload_data)
```

and in `read_state`, after the existing validation:

```python
    agent = data.get("agent")
    if not isinstance(agent, str) or not SLUG_PATTERN.match(agent):
        agent = None
    return {"status": data["status"], "ts": float(data.get("ts", 0.0)), "agent": agent}
```

- [ ] **Step 6: Run the suite**

Run: `uv run python -m pytest -v`
Expected: PASS. The existing hooks.json registration test must still pass — it parses the command and runs the hook with exactly those arguments, so it now exercises the slug too.

- [ ] **Step 7: Stage and report the commit message**

```bash
git add -A
# feat: carry the agent slug through the state file
```

---

### Task 4: Language

**Files:**
- Create: `src/waitgame/strings.py`
- Modify: `src/waitgame/pool.py` (`Pool.language`)
- Modify: `src/waitgame/app.py` (use the table; take `language`)
- Modify: `src/waitgame/cli.py` (`--lang`, pass the language and the banner through the table)
- Test: `tests/test_strings.py`, `tests/test_pool.py`, `tests/test_app.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `waitgame.agents.label_for` (Task 2), `waitgame.state.read_state(...)["agent"]` (Task 3)
- Produces:
  - `waitgame.strings.DEFAULT_LANGUAGE = "en"`
  - `waitgame.strings.text(language: str, key: str, **fields) -> str`
  - `waitgame.strings.KEYS: tuple[str, ...]` — `("waiting", "done", "exhausted", "stale", "correct", "wrong", "agent")`
  - `waitgame.pool.Pool.language: str`
  - `WaitgameApp(..., language: str = "en", agent_source: Callable[[], str | None] = lambda: None)`

- [ ] **Step 1: Write the failing tests**

`tests/test_strings.py`:

```python
import pytest

from waitgame import strings


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
```

Add to `tests/test_pool.py`:

```python
def test_language_defaults_to_english_when_absent(tmp_path):
    assert pool_mod.load_pool(write(tmp_path, GOOD)).language == "en"


def test_language_is_read_from_the_pool(tmp_path):
    data = json.loads(json.dumps(GOOD))
    data["language"] = "tr"
    assert pool_mod.load_pool(write(tmp_path, data)).language == "tr"
```

Add to `tests/test_app.py` (using the file's existing `app_for` / `poll` helpers):

```python
async def test_the_waiting_line_is_turkish_when_the_pool_is(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path, language="tr")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert text_of(app, "#status") == strings.text("tr", "waiting", agent=strings.text("tr", "agent"))


async def test_the_done_line_names_the_agent_from_the_state_file(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path, agent_source=lambda: "codex")
    async with app.run_test() as pilot:
        await drive_to_done(app, pilot)
        assert "Codex" in text_of(app, "#status")


async def test_an_unknown_agent_falls_back_to_neutral_wording(tmp_path):
    app = app_for([QUIZ], tmp_path=tmp_path, agent_source=lambda: None)
    async with app.run_test() as pilot:
        await drive_to_done(app, pilot)
        status = text_of(app, "#status")
        assert "Claude" not in status and "Codex" not in status
```

Two helper notes for `tests/test_app.py`: extend the existing `app_for` helper to forward `language` and `agent_source` to `WaitgameApp` rather than writing a second helper, and add a small `drive_to_done(app, pilot)` that flips the fixture's status to busy, polls, then flips it to idle and polls again — the file's existing lifecycle tests already do exactly that inline, so lift it rather than reinventing it.

Add to `tests/test_cli.py`:

```python
def test_lang_overrides_the_pool_language(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "_run_app", lambda **kwargs: captured.update(kwargs) or 0)
    seed(tmp_path, pool={**POOL, "language": "tr"})
    cli.main(["--repo", str(tmp_path), "--lang", "en"])
    assert captured["language"] == "en"


def test_without_lang_the_pool_language_is_used(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "_run_app", lambda **kwargs: captured.update(kwargs) or 0)
    seed(tmp_path, pool={**POOL, "language": "tr"})
    cli.main(["--repo", str(tmp_path)])
    assert captured["language"] == "tr"
```

- [ ] **Step 2: Run them and verify they fail**

Run: `uv run python -m pytest tests/test_strings.py tests/test_pool.py tests/test_app.py tests/test_cli.py -v`
Expected: FAIL — no `waitgame.strings`, no `Pool.language`, no `--lang`.

- [ ] **Step 3: Write the string table**

`src/waitgame/strings.py`:

```python
"""The interface's six strings, in the languages waitgame ships.

A dictionary, deliberately, and not an i18n framework: there is no catalog to
extract, no compilation step and no locale negotiation. The cards themselves
are written in whatever language the pool was built in; this is only the
chrome around them.
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "en"

KEYS = ("waiting", "done", "exhausted", "stale", "correct", "wrong", "agent")

_TABLE = {
    "en": {
        "agent": "the agent",
        "waiting": "Waiting for {agent} to start working — submit a prompt and the game begins.",
        "done": "{agent} is done ^ — switch back to the diff; this pane keeps running.",
        "exhausted": "Pool exhausted for this wait — the next one deals a fresh round.",
        "stale": "pool is {behind} commits behind — run the build command for fresh questions",
        "correct": "correct",
        "wrong": "wrong",
    },
    "tr": {
        "agent": "ajan",
        "waiting": "{agent} çalışmaya başlayınca oyun başlıyor — bir istem gönder.",
        "done": "{agent} bitirdi ^ — diff'e dön; bu pencere açık kalıyor.",
        "exhausted": "Bu bekleme için havuz bitti — sonraki bekleme yeni bir tur dağıtıyor.",
        "stale": "havuz {behind} commit geride — tazelemek için build komutunu çalıştır",
        "correct": "doğru",
        "wrong": "yanlış",
    },
}


def text(language: str, key: str, **fields) -> str:
    """One string, in `language` if it is shipped and in English otherwise."""
    table = _TABLE.get(language, _TABLE[DEFAULT_LANGUAGE])
    if key not in KEYS:
        raise KeyError(key)
    return table[key].format(**fields) if fields else table[key]
```

- [ ] **Step 4: Read the language from the pool**

In `src/waitgame/pool.py`, add `language: str` to `Pool` and read it in `load_pool`:

```python
        language=str(raw.get("language", "en")) or "en",
```

- [ ] **Step 5: Use the table in the app**

`WaitgameApp.__init__` takes `language: str = "en"` and `agent_source: Callable[[], str | None] = lambda: None`. Replace the `WAITING_TEXT` / `DONE_TEXT` constants and the two literal markers:

```python
    def _agent_name(self) -> str:
        return agents.label_for(self.agent_source()) or strings.text(self.language, "agent")

    # in _finish_playing:
        self.query_one("#status").update(strings.text(self.language, "done", agent=self._agent_name()))

    # in _render, the WAITING branch:
        self.query_one("#status").update(strings.text(self.language, "waiting", agent=self._agent_name()))

    # the exhausted card:
        card.update(strings.text(self.language, "exhausted"))

    # in _resolve:
        mark = strings.text(self.language, "correct" if verdict.correct else "wrong")
```

- [ ] **Step 6: Wire the CLI**

Add `--lang` (choices are free-form: any string, since unknown languages fall back), extract the app launch into `_run_app(**kwargs) -> int` so the tests above can substitute it, and pass `language=args.lang or pool.language`, `agent_source=lambda: state.read_state(launch)["agent"]`. Move `staleness_banner` onto the table too:

```python
def staleness_banner(repo_dir, head_sha, language=strings.DEFAULT_LANGUAGE) -> str:
    behind = repo.commits_behind(repo_dir, head_sha)
    if behind is None or behind < repo.STALE_THRESHOLD:
        return ""
    return strings.text(language, "stale", behind=behind)
```

Update the existing banner tests to assert on `strings.text(...)` rather than on the old English literal.

- [ ] **Step 7: Run the suite**

Run: `uv run python -m pytest -v`
Expected: PASS.

- [ ] **Step 8: Stage and report the commit message**

```bash
git add -A
# feat: let a pool declare its language and the interface follow it
```

---

### Task 5: `waitgame hooks install / status / uninstall`

**Files:**
- Create: `src/waitgame/hooks_cli.py`
- Modify: `src/waitgame/cli.py` (route the `hooks` command)
- Test: `tests/test_hooks_cli.py`

**Interfaces:**
- Consumes: `waitgame.agents` (Task 2)
- Produces:
  - `waitgame.hooks_cli.INSTALLED_SCRIPT = Path.home() / ".waitgame" / "waitgame-state.sh"` (overridable per call)
  - `waitgame.hooks_cli.packaged_script() -> Path`
  - `waitgame.hooks_cli.install_script(dest: Path) -> Path`
  - `waitgame.hooks_cli.config_path(agent, repo: Path, home: Path, user: bool) -> Path`
  - `waitgame.hooks_cli.install(agent, repo, home, user=False) -> str`
  - `waitgame.hooks_cli.uninstall(agent, repo, home, user=False) -> str`
  - `waitgame.hooks_cli.status(repo, home) -> list[str]`
  - `waitgame.hooks_cli.HooksError(Exception)`

- [ ] **Step 1: Write the failing tests**

`tests/test_hooks_cli.py`:

```python
import json
import os
import stat

import pytest

from waitgame import agents, hooks_cli


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    home.mkdir()
    return repo, home


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_install_writes_the_config_and_the_script(sandbox, slug):
    repo, home = sandbox
    agent = agents.agent_by_slug(slug)
    hooks_cli.install(agent, repo=repo, home=home)

    script = home / ".waitgame" / "waitgame-state.sh"
    assert script.read_text() == hooks_cli.packaged_script().read_text()
    assert os.stat(script).st_mode & stat.S_IXUSR

    document = json.loads(hooks_cli.config_path(agent, repo, home, user=False).read_text())
    commands = agents.registered_commands(document, agent)
    assert len(commands) == 2
    assert all(str(script) in c for c in commands)


def test_install_is_idempotent(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    hooks_cli.install(agent, repo=repo, home=home)
    hooks_cli.install(agent, repo=repo, home=home)
    document = json.loads(hooks_cli.config_path(agent, repo, home, user=False).read_text())
    assert len(agents.registered_commands(document, agent)) == 2


def test_install_keeps_unrelated_settings(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("claude")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"model": "opus", "hooks": {"Stop": [{"hooks": [{"command": "theirs.sh"}]}]}}))
    hooks_cli.install(agent, repo=repo, home=home)
    document = json.loads(path.read_text())
    assert document["model"] == "opus"
    assert "theirs.sh" in json.dumps(document)


def test_cursor_refuses_user_scope(sandbox):
    repo, home = sandbox
    with pytest.raises(hooks_cli.HooksError) as excinfo:
        hooks_cli.install(agents.agent_by_slug("cursor"), repo=repo, home=home, user=True)
    assert "project" in str(excinfo.value).lower()


def test_uninstall_removes_only_ours(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    path = hooks_cli.config_path(agent, repo, home, user=False)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "theirs.sh"}]}]}}))
    hooks_cli.install(agent, repo=repo, home=home)
    hooks_cli.uninstall(agent, repo=repo, home=home)
    document = json.loads(path.read_text())
    assert agents.registered_commands(document, agent) == []
    assert "theirs.sh" in json.dumps(document)


def test_uninstall_deletes_a_file_it_emptied(sandbox):
    repo, home = sandbox
    agent = agents.agent_by_slug("codex")
    hooks_cli.install(agent, repo=repo, home=home)
    hooks_cli.uninstall(agent, repo=repo, home=home)
    assert not hooks_cli.config_path(agent, repo, home, user=False).exists()


def test_status_reports_each_agent(sandbox):
    repo, home = sandbox
    hooks_cli.install(agents.agent_by_slug("codex"), repo=repo, home=home)
    lines = hooks_cli.status(repo=repo, home=home)
    assert any("codex" in line and "installed" in line for line in lines)
    assert any("cursor" in line and "not installed" in line for line in lines)


def test_status_reports_a_stale_script_copy(sandbox):
    repo, home = sandbox
    hooks_cli.install(agents.agent_by_slug("codex"), repo=repo, home=home)
    (home / ".waitgame" / "waitgame-state.sh").write_text("#!/bin/sh\n# an old copy\n")
    assert any("stale" in line for line in hooks_cli.status(repo=repo, home=home))


@pytest.mark.parametrize("slug", ["claude", "codex", "cursor"])
def test_the_registered_command_is_one_the_hook_accepts(sandbox, slug):
    """The check with no other symptom: a wrong event, argument or slug just
    means the pane never wakes."""
    import shlex
    import subprocess

    repo, home = sandbox
    agent = agents.agent_by_slug(slug)
    hooks_cli.install(agent, repo=repo, home=home)
    document = json.loads(hooks_cli.config_path(agent, repo, home, user=False).read_text())

    for command in agents.registered_commands(document, agent):
        argv = shlex.split(command)
        result = subprocess.run(
            argv,
            input=b"{}",
            env={"HOME": str(home), "CLAUDE_PROJECT_DIR": str(repo), "PATH": os.environ["PATH"]},
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run them and verify they fail**

Run: `uv run python -m pytest tests/test_hooks_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'waitgame.hooks_cli'`

- [ ] **Step 3: Implement `hooks_cli.py`**

Key points, all exercised by the tests above:

- `packaged_script()` returns the `waitgame-state.sh` shipped with the package. Add it to the wheel by putting the file in `src/waitgame/waitgame-state.sh` and declaring `[tool.hatch.build.targets.wheel] artifacts` / `force-include` for it, keeping `hooks/waitgame-state.sh` as the plugin's copy. **The two must not drift**: add a test asserting the two files are byte-identical, and have the plugin path keep using its own copy.
- `install_script(dest)` copies it and `chmod 0o755`.
- `config_path(agent, repo, home, user)` = `home / agent.user_relpath` when `user` else `repo / agent.project_relpath`.
- `install` raises `HooksError` when `user and not agent.supports_user_scope`, with the reason: Cursor runs user hooks from `~/.cursor/`, so the state key would name the wrong directory.
- `install` reads the existing JSON (a malformed file is a `HooksError`, never silently overwritten), merges, and writes with `indent=2`.
- `uninstall` unmerges and deletes the file when nothing but `{}` (or `{"version": 1}`) remains.
- `status` returns one line per agent: `not installed`, `installed`, or `installed (stale: script copy differs from the packaged one)`.

- [ ] **Step 4: Route the command from `cli.py`**

`main` grows `hooks` as a command with a nested parser: `waitgame hooks install|status|uninstall [--agent claude|codex|cursor|auto] [--user] [--repo DIR]`. `auto` installs for every agent whose config directory already exists under the target, and reports what it did; it never creates an agent's directory from nothing.

- [ ] **Step 5: Run the suite**

Run: `uv run python -m pytest -v`
Expected: PASS.

- [ ] **Step 6: Stage and report the commit message**

```bash
git add -A
# feat: add `waitgame hooks` for Codex, Cursor and standalone Claude Code
```

---

### Task 6: `waitgame build-prompt`

**Files:**
- Create: `src/waitgame/build_prompt.md` (moved from the body of `commands/waitgame-build.md`)
- Modify: `commands/waitgame-build.md` (becomes a thin wrapper)
- Modify: `src/waitgame/cli.py` (`build-prompt` command)
- Test: `tests/test_plugin_files.py` (repoint the contract test at the new single source)

**Interfaces:**
- Consumes: `waitgame.pool.load_pool` (Task 1)
- Produces: `waitgame.cli.build_prompt(language: str, repo_name: str) -> str`

- [ ] **Step 1: Write the failing test**

In `tests/test_plugin_files.py`, repoint `example_pool_text()` at `waitgame/build_prompt.md` and add:

```python
def test_the_slash_command_delegates_rather_than_duplicating():
    body = BUILD_COMMAND.read_text(encoding="utf-8")
    assert "build_prompt.md" in body
    assert '"type": "quiz"' not in body, "the JSON shape must live in one file only"


def test_build_prompt_substitutes_the_language_and_repo():
    out = cli.build_prompt(language="tr", repo_name="trumy")
    assert "trumy" in out
    assert "tr" in out
    assert "{language}" not in out and "{repo}" not in out
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run python -m pytest tests/test_plugin_files.py -v`
Expected: FAIL — `build_prompt.md` does not exist.

- [ ] **Step 3: Move the instructions into the package**

Move the whole body of `commands/waitgame-build.md` to `src/waitgame/build_prompt.md`, replacing the hard-coded language and repo name with `{language}` and `{repo}` placeholders. Declare it as package data so it ships in the wheel. Leave `commands/waitgame-build.md` as a short wrapper telling Claude to read the packaged file and follow it, naming the repo and the language argument.

- [ ] **Step 4: Add the CLI command**

```python
def build_prompt(language: str, repo_name: str) -> str:
    source = Path(__file__).with_name("build_prompt.md").read_text(encoding="utf-8")
    return source.replace("{language}", language).replace("{repo}", repo_name)
```

wired as `waitgame build-prompt [--lang tr|en] [--repo DIR]`, printing to stdout so it can be piped to a clipboard.

- [ ] **Step 5: Run the suite**

Run: `uv run python -m pytest -v`
Expected: PASS.

- [ ] **Step 6: Stage and report the commit message**

```bash
git add -A
# feat: print the build prompt for agents without a slash command
```

---

### Task 7: Documentation and version

**Files:**
- Modify: `README.md`, `pyproject.toml`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

- [ ] **Step 1: Bump the version to 0.2.0**

In `pyproject.toml`, `src/waitgame/__init__.py` and both manifests.

- [ ] **Step 2: Rewrite the README's install and usage sections**

Cover, in this order: the Claude Code plugin path (unchanged); `waitgame hooks install --agent codex` and `--agent cursor` for the others, with one sentence on why Cursor is project-scope only; `waitgame build-prompt` for generating a pool without the slash command; the `language` field and `--lang`; and that mutant cards are gone in 0.2.0 and old pools must be regenerated. Remove every remaining mention of "spot the bug" and of `c` / `b`.

- [ ] **Step 3: Run the suite once more and verify the docs claims**

Run: `uv run python -m pytest -v`, then read the README against the code one claim at a time — every command it prints must exist and every key it names must be bound.

- [ ] **Step 4: Stage and report the commit message**

```bash
git add -A
# docs: document multi-agent setup, language, and 0.2.0's pool break
```

---

## Self-Review Notes

Checked against the spec:

- Mutant removal, with a migration message naming 0.2.0 → Task 1.
- Adapter registry, two shapes for three agents → Task 2.
- Cursor project-scope-only, refused with a reason → Tasks 2 and 5.
- `hooks install/status/uninstall`, merging without clobbering, idempotent → Task 5.
- The script copied to `~/.waitgame/waitgame-state.sh` and registered from there, with `status` reporting a stale copy → Task 5.
- Agent slug through the hook and the state file, neutral wording when absent → Task 3.
- `build-prompt` sharing one source with the slash command → Task 6.
- `language` in the pool, six strings in `tr`/`en`, English fallback, `--lang` override → Task 4.
- Registration-correctness test generalized to all three agents → Task 5, Step 1.
- Version `0.2.0` → Task 7.

Out of scope per the spec and therefore absent: hook-less busy/idle detection, per-agent command installation, languages beyond `tr`/`en`, reference-counting concurrent agents.

One thing the spec left implicit that this plan pins down: the packaged copy of the hook script (`src/waitgame/waitgame-state.sh`, needed so `hooks install` has something to copy) must stay byte-identical to the plugin's `hooks/waitgame-state.sh`, and Task 5 adds the test that proves it.
