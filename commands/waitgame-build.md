---
description: Generate the waitgame question pool for this repository
---

Build `.waitgame/pool.json` for the current repository.

The instructions for this now live in `waitgame/build_prompt.md`, packaged
with the CLI, so Codex and Cursor users get the same text through
`waitgame build-prompt` — this command is a thin pointer at it, not a copy.

Run:

    uvx claude-waitgame build-prompt --lang <code> --repo .

(during development, from a checkout of this plugin: `uv run waitgame
build-prompt --lang <code> --repo .`)

`<code>` is a short language code, not a language name: pass `en` unless the
user asked for another language. `tr` and `en` are the two the playing
interface speaks; any other code (`de`, `fr`, ...) still writes the cards in
that language, but leaves the interface in English. `--repo` is a path, and
`.` — this repository — is what you want. Then follow the printed instructions
exactly — they cover what to read, the pool's JSON shape, the secret-file
rules, and how to finish — to build `.waitgame/pool.json`.
