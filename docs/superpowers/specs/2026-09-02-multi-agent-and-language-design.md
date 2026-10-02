# waitgame — multi-agent support, language, and the removal of mutant cards

**Date:** 2026-09-02
**Status:** Approved design, not yet implemented
**Supersedes parts of:** `docs/superpowers/specs/2026-08-28-waitgame-design.md`
**Version:** the release carrying this work is `0.2.0` — the pool format changes incompatibly

## Why

Three things came out of the first real use of the tool against a live repository.

**Mutant cards do not earn their place.** Showing the player a snippet of real code and asking "is this correct?" reads as a quiz about diff-reading, not about the project. The questions that worked were the ones only someone who had read this repository could answer. The mutant mechanic goes.

**The tool is bound to Claude Code for no good reason.** Its busy/idle signal comes from two Claude Code hooks, but Codex and Cursor expose the same two moments. The signal was never Claude-specific; only the registration was.

**Nothing records what language a pool is written in.** A pool generated against a Turkish codebase comes out Turkish while the interface stays English, and the next person to refresh the pool may silently get a different language.

## What already exists

Unchanged by this work: the state file contract (`~/.waitgame/state/<key>.json`, key = first 16 hex chars of the SHA-256 of the resolved launch directory), the pure-bash hook that writes it, the three-phase TUI lifecycle (waiting / playing / done), score persistence, and the staleness banner.

## Part 1 — Mutant cards are removed

`MutantItem`, the loader's `_mutant` branch, `CLEAN_EXPLANATION`, the `c`/`b` bindings and their handlers, `check_action`'s mutant branch, the mutant rendering in `_render`, and the mutant half of the build command all go. `game.answer()` takes a choice index and nothing else; its `int | bool` parameter narrows to `int`.

**Existing pools break, and must say so.** A committed `pool.json` containing `"type": "mutant"` items would otherwise fail with a bare "unknown type" once this ships. `load_pool` names the situation instead:

> `item 4: mutant cards were removed in 0.2.0 — regenerate this pool with the build command`

That message is the migration path. There is no converter: a mutant card has no question text to convert into.

## Part 2 — Agents

### The three, as they actually are

| Agent | Prompt submitted | Turn ended | Registration file | Hook's working directory |
|---|---|---|---|---|
| Claude Code | `UserPromptSubmit` | `Stop` | plugin's own `hooks/hooks.json` | session dir (`CLAUDE_PROJECT_DIR`) |
| Codex | `UserPromptSubmit` | `Stop` | `<repo>/.codex/hooks.json`, or `~/.codex/hooks.json` | session dir |
| Cursor | `beforeSubmitPrompt` | `stop` | `<project>/.cursor/hooks.json`, or `~/.cursor/hooks.json` | **project root for project hooks; `~/.cursor/` for user hooks** |

Claude Code and Codex share a registration shape (`{"hooks": {"<Event>": [{"hooks": [{"type": "command", "command": "..."}]}]}}`). Cursor's differs: a top-level `"version": 1` and event arrays of plain `{"command": "..."}` objects.

**Cursor is installed at project level only.** Its user-level hooks run from `~/.cursor/`, and the hook derives the state key from its working directory — so a user-level Cursor registration would key the wrong directory and the pane would simply never wake, with nothing anywhere saying why. Refusing that installation is better than shipping a silent failure. `waitgame hooks install --agent cursor --user` therefore errors with that explanation rather than writing the file.

Codex has no such problem: its hooks run from the session's working directory either way, so `--user` is allowed there.

### The adapter registry

One module, `src/waitgame/agents.py`, holding a frozen dataclass per agent:

```python
@dataclass(frozen=True)
class Agent:
    slug: str                    # "claude" | "codex" | "cursor"
    label: str                   # "Claude Code", for the UI and for messages
    busy_event: str              # "UserPromptSubmit" | "beforeSubmitPrompt"
    idle_event: str              # "Stop" | "stop"
    supports_user_scope: bool
```

Two functions per agent shape rather than per agent: `render_entries` (what this agent's file should contain for our two events) and `merge` / `unmerge` (fold our entries into an existing document, or take only ours back out). The two shapes are the Claude/Codex one and the Cursor one; three agents, two implementations.

Adding a fourth agent is one `Agent` entry plus, only if its file shape is new, one more pair of shape functions.

### `waitgame hooks`

- `hooks install --agent claude|codex|cursor|auto [--user] [--repo DIR]` — reads the existing registration file if there is one, merges our two entries in, writes it back. **Never clobbers another tool's hooks**, and running it twice does not duplicate ours.
- `hooks status [--repo DIR]` — one line per agent: installed, not installed, or installed-but-stale (the registration points somewhere other than the installed hook script, or at a copy whose contents differ from the one this version ships).
- `hooks uninstall --agent ... [--user] [--repo DIR]` — removes only our entries, leaving everyone else's and deleting the file only if it becomes empty of hooks.

### Where the registered script lives

A registration has to name an absolute path, and the obvious one — the copy of `waitgame-state.sh` inside the installed package — is not stable. Under `uvx` the package lives in a cache directory that can be reclaimed, and the registration would then point at nothing. The hook would stop writing, and the only symptom would be a pane that never wakes.

So `hooks install` **copies the script to `~/.waitgame/waitgame-state.sh`** (mode `0755`) and registers that path. It is outside any package, survives cache eviction and upgrades, and needs no interpreter, which keeps the hook pure bash on the path that runs at every prompt.

Re-running `install` overwrites that copy, which is how a newer version's script reaches an existing registration. `hooks status` compares the copy against the one shipped in the package and reports a difference as stale, so an old copy is visible rather than silently in charge.

The Claude Code plugin path is untouched: its own `hooks/hooks.json` keeps using `${CLAUDE_PLUGIN_ROOT}`, which the plugin system already keeps valid.

`auto` installs for every agent whose configuration directory already exists in the target repo or home, and reports what it did. It never creates an agent's directory from nothing — a `.cursor/` that appears in a repo nobody uses Cursor in is noise.

Claude Code remains installable this way too, for the case where someone wants the hooks without the plugin. When the plugin is installed, its own `hooks/hooks.json` registers the same two hooks, and that registration is separate from — and invisible to — the ones `hooks install` writes: `hooks status` reports only what waitgame itself manages, so it says `not installed` for Claude Code even when the plugin is running the hooks. Reading the plugin's install state would mean depending on Claude Code's internals, so the line says so instead, rather than inviting a redundant second copy.

### The state file names the agent

The pane currently says `Claude is done ^` no matter which agent ran. For a Codex user that is simply false.

The hook takes an optional second argument, the agent slug, and writes it into the state file:

```json
{"status": "busy", "ts": 1788266931, "agent": "codex"}
```

Every registration this tool writes passes its slug. The slug is validated in bash against `^[a-z][a-z-]{0,15}$` before it reaches the file, so nothing arbitrary is interpolated into JSON. A state file with no `agent` key — an older one, or a hand-written registration — reads back as `None`, and the interface uses neutral wording.

`read_state` gains the key and keeps its existing contract: it never raises, and an unreadable file still reads as idle.

## Part 3 — `waitgame build-prompt`

The pool-generation instructions move to one file inside the package, `src/waitgame/build_prompt.md`. Two consumers read it:

- `commands/waitgame-build.md`, the Claude Code slash command, which stays a thin wrapper naming the file
- `waitgame build-prompt [--lang tr|en] [--repo DIR]`, which prints it for pasting into any other agent

The command substitutes the requested language and the repo name into the text before printing. A user of Codex or Cursor pipes it to their clipboard and pastes it; the agent then writes `.waitgame/pool.json` exactly as the slash command does today.

Keeping one source matters: the existing test that runs the build prompt's own JSON example through `load_pool` becomes the single pin for both consumers, rather than one pin and one copy that drifts.

## Part 4 — Language

`pool.json` gains a top-level `"language"` field, a short code (`"tr"`, `"en"`). `load_pool` reads it and defaults to `"en"` when absent, so pools written before this change keep working.

The interface has six strings — the waiting line, the done line, the pool-exhausted line, the stale-pool banner, the correct marker, the wrong marker. They live in a plain dict in `src/waitgame/strings.py`, keyed by language then by name, with `tr` and `en` shipped. An unknown language falls back to English rather than showing a key. This is a dictionary, not an i18n framework: no catalogs, no extraction step, no runtime locale negotiation.

The agent's label is substituted into the done and waiting lines, so Turkish reads *"Codex bitirdi ^"* and English *"Codex is done ^"*.

`waitgame --lang en` overrides the pool's language for one viewer, which is what a reader who does not speak the team's language needs.

## Testing

- **Adapters**, per agent: installing into a file that does not exist; installing into a file that already holds **someone else's** hooks, asserting theirs survive verbatim; installing twice, asserting no duplication; uninstalling, asserting only ours left and the others are untouched.
- **Registration correctness**, generalized from the existing Claude-only test to all three: parse the file each adapter writes, extract the command it registers, and run the real hook with those exact arguments — the check that would catch a wrong event name, a wrong argument, or a typo'd slug, none of which has any other symptom.
- **Cursor user scope** is refused, with the reason in the error.
- **The script copy**: `install` writes `~/.waitgame/waitgame-state.sh`, executable, byte-identical to the packaged one, and the registration names that path; `status` reports stale when the copy differs from the packaged script.
- **Language**: the six strings resolve in `tr` and `en`; an unknown language falls back to English; `--lang` overrides the pool.
- **Pool loading**: a pool with `"type": "mutant"` fails with the message naming 0.2.0 and the build command; a pool with no `language` loads as English.
- **State**: a slug round-trips through the real bash hook; an invalid slug is refused; a state file with no `agent` key reads back as `None`.

## Out of scope

Detecting busy/idle without hooks (process watching, PTY wrapping, log tailing) — every agent named here has the two events, so inference would be strictly worse. Per-agent command installation for `build-prompt` (`.codex/prompts/`, `.cursor/commands/`) — the printed prompt covers it until someone asks. Any language beyond `tr` and `en`. Concurrent agents in one directory: the last writer wins, which is correct often enough, and reference-counting two agents' turns is a design problem nobody has yet.
