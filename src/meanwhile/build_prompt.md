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

## What to write

Write `.meanwhile/pool.json` with 30-50 `quiz` items, using exactly this shape:

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
2. Run `uvx claude-meanwhile validate --repo .` (during development, from a
   checkout of this plugin: `uv run meanwhile validate --repo .`) and fix
   anything it reports.
3. Tell the user the item count and that `.meanwhile/pool.json` is ready to
   commit so their team shares the pool.
