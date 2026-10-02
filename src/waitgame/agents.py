"""Which agents waitgame can hook into, and how each one registers hooks.

The busy/idle signal is not Claude-specific: Codex and Cursor expose the same
two moments under their own names, and the same bash script serves all three.
Only the registration file and its JSON shape differ, so that is all this
module knows about.
"""

from __future__ import annotations

import copy
import re
import shlex
from dataclasses import dataclass

#: How our entries are recognised inside somebody else's config file. Matching
#: on the script name rather than on an exact command string is what lets
#: `merge` replace an entry that points at an older copy of the script.
MARKER = "waitgame-state.sh"

SLUG_PATTERN = re.compile(r"^[a-z][a-z-]{0,15}\Z")


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
        # lives in a settings file alongside unrelated settings, which is why
        # the merge only ever touches document["hooks"].
        #
        # settings.local.json, not settings.json, for the project scope:
        # settings.json is the committed file, and the command we register
        # carries an absolute path to this machine's copy of the script. A
        # committed registration would make every teammate's Claude Code run a
        # script that does not exist for them, on every prompt submit and every
        # Stop. settings.local.json is the gitignored per-user sibling.
        # Under $HOME there is no such split, and settings.json is personal
        # already.
        project_relpath=".claude/settings.local.json",
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
    """The shell command a registration runs.

    `shlex.quote`, not a bare pair of double quotes: the path carries the
    user's home directory, and a `"`, `$` or backtick in it would close the
    quoting or be expanded by the shell — a hook pointing at a path that does
    not exist, which is exactly the silent failure this module exists to avoid.
    """
    return f"{shlex.quote(script)} {status} {agent.slug}"


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


def _filtered_entry(entry: dict, shape: str) -> dict | None:
    """Filter out our hooks from an entry, returning the filtered entry or None if empty.

    For cursor shape (one command per entry), return the entry or None.
    For claude/codex shape (array of hooks), filter the inner hooks array and return
    the entry only if it still has hooks.
    """
    if shape == "cursor":
        # For cursor: entry has {"command": "..."}, drop it if it's ours
        if _is_ours(entry):
            return None
        return entry

    # For claude/codex: entry has {"hooks": [...], possibly "matcher": ...}
    # Filter the inner hooks array, keeping only those without our marker
    if "hooks" not in entry or not isinstance(entry["hooks"], list):
        return entry

    kept_hooks = [
        h for h in entry["hooks"]
        if isinstance(h, dict) and MARKER not in h.get("command", "")
    ]

    if not kept_hooks:
        return None

    # Reconstruct entry with filtered hooks, preserving other keys like "matcher"
    filtered = {k: v for k, v in entry.items() if k != "hooks"}
    filtered["hooks"] = kept_hooks
    return filtered


def _kept_entries(entries, shape: str) -> list:
    """Everything in `entries` except our own hooks, in order.

    A neighbour this module does not understand — a bare string in the event's
    array, a number, anything that is not a hook entry — is carried through
    untouched rather than dropped. The guarantee is "never destroys a foreign
    hook", and it must not quietly mean "never destroys a well-formed one".
    """
    if not isinstance(entries, list):
        # An event whose value is not an array is malformed for every agent we
        # know, but it is still somebody's content: keep it as the one entry it
        # is, so `merge` can append ours beside it instead of over it.
        entries = [entries]
    kept = []
    for entry in entries:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        filtered = _filtered_entry(entry, shape)
        if filtered is not None:
            kept.append(filtered)
    return kept


def merge(document: dict, agent: Agent, script: str) -> dict:
    """Our two entries, folded into a copy of `document`.

    Idempotent, and safe on a file that already holds other tools' hooks:
    every hook that is not ours is carried through untouched (even if in an
    entry with ours), and ours are rewritten rather than appended so a changed
    script path replaces the old registration instead of doubling it.
    """
    out = copy.deepcopy(document)
    if agent.shape == "cursor":
        out.setdefault("version", 1)
    hooks = out.setdefault("hooks", {})
    for status, event in (("busy", agent.busy_event), ("idle", agent.idle_event)):
        # Filter each entry: for claude/codex, this removes our inner hooks but
        # keeps the entry if foreign hooks remain; for cursor, drops the entry if it's ours
        kept = _kept_entries(hooks.get(event, []), agent.shape)
        hooks[event] = kept + [_entry(command_for(script, agent, status), agent.shape)]
    return out


def unmerge(document: dict, agent: Agent) -> dict:
    """A copy of `document` with our hooks — and only ours — taken out.

    For claude/codex shape, removes our inner hooks but keeps entries that still
    have foreign hooks. For cursor shape, removes entire entries that are ours.
    """
    out = copy.deepcopy(document)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event in (agent.busy_event, agent.idle_event):
        entries = hooks.get(event)
        if entries is not None and not isinstance(entries, list):
            # Not a list, so nothing of ours can be in it (merge only ever
            # writes a list). Leave the stranger exactly as we found it.
            continue
        # Filter each entry to remove our hooks, keeping entries if they still have foreign hooks
        kept = _kept_entries(entries or [], agent.shape)
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
