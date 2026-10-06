# meanwhile

Claude Code takes a while on real tasks — often ten or fifteen minutes. During
that wait, attention drifts: a browser tab, a chat, something unrelated. When
the diff finally lands, you no longer hold the task in your head, and the
review that follows is slower and shallower than it should be. meanwhile fills
that wait with a quiz built entirely from your own repository, so that
instead of drifting away you stay warmed up on the code you're about to
review. It works the same way alongside Codex and Cursor.

## Install

### Claude Code

meanwhile is a Claude Code plugin, and this repository is also its own
marketplace (`.claude-plugin/marketplace.json`). Add it as a marketplace,
then install the plugin from it:

```
/plugin marketplace add /path/to/meanwhile
/plugin install meanwhile@meanwhile
```

(Once the repo is hosted somewhere your team can reach, add it from there
instead — for example `/plugin marketplace add owner/meanwhile` for a GitHub
repo.) Restart Claude Code afterwards so the plugin's hooks are picked up.

Installing the plugin adds two hooks and one slash command; it does not
install the `meanwhile` command itself. That's a separate, ordinary Python
package — see "Daily use" below.

### Codex and Cursor

Codex and Cursor have no plugin system, so `meanwhile` writes the hook
registration into their config file directly:

```
uvx claude-meanwhile hooks install --agent codex
uvx claude-meanwhile hooks install --agent cursor
```

(While developing against a checkout of this repo instead of the published
package, use `uv run meanwhile hooks install --agent codex` from inside it.)

Leaving off `--agent` (or passing `--agent auto` explicitly) installs for
every agent whose config directory already exists in this project — it never
creates one, so an agent you don't use is left alone. `meanwhile hooks status`
reports what's registered and where — only the registrations meanwhile itself
wrote, so a Claude Code *plugin* install is invisible to it and shows as `not
installed (the plugin registers its own hooks separately)`. `meanwhile hooks
uninstall --agent <agent>` takes a registration back out.

Cursor only supports project-scope registration. `--user` is refused for it:
Cursor runs its user-level hooks from `~/.cursor/`, while the hook keys the
state file on its working directory, so a user-level registration could
never wake the right pane.

For Claude Code, a `hooks install` registration is written to
`.claude/settings.local.json`, not `settings.json` — the entry embeds an
absolute path to this machine's copy of the hook script, and `settings.json`
is the file teams commit. A Codex or Cursor project registration has no such
gitignored sibling to move to, so `hooks install` prints a note there — every
time, whether or not git already tracks the file — saying that the path it
just wrote is specific to this machine and that committing it would leave
teammates running a script they do not have.

If you both install the plugin *and* run `meanwhile hooks install --agent
claude`, the two hooks fire twice per prompt. That's harmless — both copies
are byte-identical (`hooks/meanwhile-state.sh` for the plugin,
`~/.meanwhile/meanwhile-state.sh` for the standalone registration) and are run
with the same arguments against the same state file, so it's one redundant
run per event — but worth knowing so you don't go looking for a bug.

`hooks` is handled before the normal argument parser is built, so it never
appears in `meanwhile --help`. `build-prompt` (below) does appear there, but
only as a bare choice with no explanation of what it does — so this README
is where to learn about both.

## First run

In a project you want to play against, build a pool once, up front — nothing
regenerates it in the background.

**Claude Code**: run

```
/meanwhile-build
```

This asks Claude to read the repository — models, routes, the README,
`CHANGELOG.md`, recent commits — and write `.meanwhile/pool.json`: a set of
multiple-choice questions drawn from that project's actual code.

**Codex, Cursor, or any other agent**: `/meanwhile-build` is a Claude Code
slash command, so run this instead and paste the printed instructions to
your agent:

```
uvx claude-meanwhile build-prompt --lang en --repo .
```

It prints the exact same instructions the slash command uses, so the pool
comes out the same either way.

Commit `.meanwhile/pool.json`. It's checked into the repository on purpose, so
everyone on the team plays the same pool and nobody pays to regenerate it.

`--lang` takes a short language code — `tr` or `en` — not a language name:
`--lang Turkish` is not recognised and silently leaves the interface in
English. Those two codes are the only ones the interface itself speaks.

A pool built by the build prompt records the language it was written in, and
the playing interface follows it, with `--lang` overriding that for just your
pane. `--lang` on `build-prompt` controls what language the cards themselves
get written in — any code is allowed there, so `--lang de` writes German cards
and leaves the interface in English. `pool.json` carries the same code in a
top-level `language` field (it defaults to `en` when absent); the playing
interface's own chrome — the waiting banner, "correct"/"wrong", and so on —
follows that field, in `tr` or `en` and in English for anything else.

A pool built before 0.2.0 that still contains "spot the bug" mutant cards
fails to load — that card type is gone. The error names 0.2.0 and tells you
to regenerate the pool; run the build step again to get an all-multiple-choice
one.

## Daily use

Open a second terminal pane next to the one running your agent — a tmux
split, an iTerm pane, or just another window — sitting in the *same directory
you started it in*, and run:

```
uvx claude-meanwhile
```

(While developing against a checkout of this repo instead of the published
package, use `uv run meanwhile` from inside it.)

Open it whenever you like — before your first prompt is fine. The pane sits
waiting until your agent starts working, wakes up within about a second of
you submitting a prompt, and serves multiple-choice cards about the
codebase one at a time. Answer with the number key for the choice you want;
the footer only ever offers the keys the card on screen can actually take.
Answering shows the explanation, `space` deals the next card, and a streak
counter tracks that wait. If a wait runs long enough to reach the end of the
pool, the pane says so and sits out the rest of it rather than repeating
questions.

The moment your agent finishes, the current card freezes and the pane shows
`<Agent> is done ^` (or `the agent is done ^` if it can't tell which one),
which is your cue to switch back.

Then leave it open. It stays on that line — it does not clear itself or
return to the waiting message — until your next prompt, which deals a fresh,
re-shuffled round, so a long wait never exhausts the pool for the next one.
You only ever press `q` when you are done for the day. Each wait is scored as
its own session and added to your totals when it ends; a wait you answered
nothing in is not recorded.

The interface follows the language recorded in the pool. Override it for
just your pane with `--lang` and a short code, for example `uvx
claude-meanwhile --lang en`, regardless of what the pool says. `tr` and `en`
are the two the interface speaks; any other code leaves it in English.

## How it works

meanwhile is three independent parts that only ever talk to each other
through two files on disk — nothing imports anything else, and each part can
be tested alone:

```
/meanwhile-build          (Claude Code slash command)
build-prompt              (same instructions, any other agent)
        │  writes
        ▼
   .meanwhile/pool.json          ← committed to the repo, shared by the team
        │  reads
        ▼
   meanwhile TUI  ──watches──►  ~/.meanwhile/state/<project-hash>.json
   (uvx, separate pane)                    ▲
                                           │ writes
                    hooks: plugin (Claude Code), or `meanwhile hooks
                    install` (Claude Code, Codex, Cursor)
```

- **`/meanwhile-build`** (or `meanwhile build-prompt` for Codex and Cursor) is
  the only part that costs tokens or touches an LLM. It reads the repository
  and writes `.meanwhile/pool.json`.
- **The hooks** are a few lines of pure bash (`hooks/meanwhile-state.sh` for
  the plugin; the same script, packaged inside the wheel and copied to
  `~/.meanwhile/meanwhile-state.sh`, for `hooks install`), fired on the moment
  each agent starts and stops working — `UserPromptSubmit`/`Stop` for
  Claude Code and Codex,
  `beforeSubmitPrompt`/`stop` for Cursor. They write nothing but a
  `{"status": "busy"|"idle", "ts": ..., "agent": ...}` file under
  `~/.meanwhile/state/`, keyed by a hash of the directory the agent was
  started in (that is what `CLAUDE_PROJECT_DIR` holds for Claude Code — not
  necessarily the git root, which is why the TUI must be launched from the
  same directory). No interpreter, no network, no measurable delay added to
  your prompt.
- **The `meanwhile` TUI**, run separately as `uvx claude-meanwhile`, polls
  that state file and renders cards from the pool. It finds
  `.meanwhile/pool.json` at the git root above wherever you launched it. It makes no LLM calls and
  parses no source code at play time — it only reads the two JSON files
  above.

## Refreshing a stale pool

`pool.json` records the commit it was built from. If the repository has
moved on more than about 50 commits since then, the TUI shows a banner —
`pool is N commits behind — run the build command for fresh questions` — but
it never regenerates the pool on its own. Silent background regeneration
would spend tokens you didn't ask for, which is exactly what this design
avoids. Run `/meanwhile-build` (or `meanwhile build-prompt`) again when you see
the banner (or whenever the pool just feels stale) and commit the updated
file.

## Scores

Your running total and best streak are written to `.meanwhile/scores.json`.
That file is gitignored — scores are local to your machine and never shared
or synced between teammates.
