Build `.meanwhile/pool.json` for the current repository.

## What to read

Survey the repo to understand what it does and what is distinctive about it:

- data models, schemas, and migrations
- API routes, serializers, and their validation rules
- the README, and any docs describing domain concepts
- `CHANGELOG.md` if present
- `git log --oneline -50` for recent direction

Prefer the project's own domain terms over generic programming vocabulary. A
good question could only be answered by someone who has read this repository.
Write the questions in {language}. Record that language in the pool too, so
the playing interface follows it.

The language is given as a short language code, not a language name, and the
pool's `language` field records exactly that code. `tr` and `en` are the two
the playing interface itself speaks; any other code is still fine — the cards
get written in that language and the interface stays English.

## Extending an existing pool

If `.meanwhile/pool.json` already exists, extend it rather than replacing it,
unless the user asked for a fresh pool:

- Keep every existing item exactly as it is — players' progress is keyed on
  the question text, so a reworded question counts as a new one. Only drop
  an item whose `source` file no longer exists.
- Add 30 new items. None may ask what an existing item already asks; read
  the existing questions first, and look for parts of the repository they
  do not cover yet.
- Keep the pool's own `language` — it wins over the language named above,
  which is only a default — unless the user asked for another one.
- Set `builtAt` and `headSha` to today and the current commit.

## What to write

For a new pool, write `.meanwhile/pool.json` with 30-50 `quiz` items; when
extending, keep the same envelope and append to `items`. Use exactly this
shape:

    {
      "builtAt": "<today, YYYY-MM-DD>",
      "headSha": "<output of: git rev-parse --short HEAD>",
      "repo": "{repo}",
      "language": "{language}",
      "items": [
        {
          "type": "quiz",
          "q": "<question about this project's domain or behavior>",
          "choices": ["<option>", "<option>", "<option>"],
          "answer": <0-based index of the correct choice>,
          "why": "<one sentence explaining the answer>",
          "source": "<repo-relative path the question came from>"
        }
      ]
    }

Rules:

- Never invent code. Every question must be grounded in a file that exists.
- **Never take a question or an answer from a secret file.**
  `.meanwhile/pool.json` is committed and shared with the whole team, so
  anything copied into it is published. Skip `.env` and any `.env.*`,
  credential/key/token/certificate files (`*.pem`, `*.key`, `id_rsa`,
  `credentials*`, `secrets*`), fixtures holding real keys, and **any file
  excluded by `.gitignore`** — check with `git check-ignore -q <path>`
  before using a file. Draw only on files that are tracked in git.
- Wrong quiz choices should be plausible to someone who half-remembers the
  code, not obviously absurd.

## Finish

1. Ensure `.meanwhile/scores.json` is in `.gitignore`; add it if missing.
2. Run `uvx meanwhile-cli validate --repo .` (during development, from a
   checkout of this plugin: `uv run meanwhile validate --repo .`) and fix
   anything it reports.
3. Tell the user the item count — when extending, how many were added and
   how many there are now — and that `.meanwhile/pool.json` is ready to
   commit so their team shares the pool.
4. Tell the user how to play, in {language} — building the pool starts
   nothing, and no other step says how. Give them the command itself, in a
   code block they can copy:

       uvx meanwhile-cli

   and say where it goes: a second terminal pane beside this one, opened in
   this same directory. The pane waits there, deals cards from their next
   prompt on, and `q` quits it.
