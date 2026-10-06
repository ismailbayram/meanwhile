"""Command line entry point: `meanwhile` plays, `meanwhile validate` checks a pool."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import repo, state, strings
from .pool import POOL_RELPATH, PoolError, load_pool


def launch_dir(start: str | Path) -> Path:
    """The directory the pane was launched in.

    This — not the git root — is the state-file key: hooks/meanwhile-state.sh
    keys on CLAUDE_PROJECT_DIR, which Claude Code sets to the directory the
    session was started in. Keying the TUI on the git root instead would
    silently never meet the hook whenever Claude Code is launched below it
    (a monorepo package, `backend/`, ...).
    """
    return Path(start).resolve()


def repo_root(start: str | Path) -> Path:
    """The git root of `start`, or `start` itself when it is not a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return Path(start)
    if result.returncode != 0:
        return Path(start)
    return Path(result.stdout.strip())


def staleness_banner(
    repo_dir: str | Path, head_sha: str, language: str = strings.DEFAULT_LANGUAGE
) -> str:
    behind = repo.commits_behind(repo_dir, head_sha)
    if behind is None or behind < repo.STALE_THRESHOLD:
        return ""
    return strings.text(language, "stale", behind=behind)


def build_prompt(language: str, repo_name: str) -> str:
    """The packaged build instructions, with `{language}` and `{repo}` filled in.

    Plain `str.replace`, not `str.format`: the file is a worked JSON example
    full of braces that `.format` would try (and fail) to parse as fields.
    This is the one copy — `commands/meanwhile-build.md` points at it instead
    of duplicating it, and `tests/test_plugin_files.py` pins its example to
    `meanwhile.pool.load_pool`.
    """
    source = Path(__file__).with_name("build_prompt.md").read_text(encoding="utf-8")
    return source.replace("{language}", language).replace("{repo}", repo_name)


def validate(repo_dir: str | Path) -> tuple[int, list[str]]:
    root = Path(repo_dir)
    try:
        pool = load_pool(root / POOL_RELPATH)
    except PoolError as exc:
        return 1, [str(exc)]

    missing = sorted({item.source for item in pool.items if not (root / item.source).exists()})
    if missing:
        return 1, [f"source file does not exist: {path}" for path in missing]
    return 0, [f"pool is valid: {len(pool.items)} item(s)"]


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # `hooks` takes the rest of the line for its own parser, so `meanwhile
    # hooks install --agent codex` does not have to share flags with `play`.
    if argv and argv[0] == "hooks":
        return run_hooks(argv[1:])

    # No prog=: argparse takes it from sys.argv[0], so `meanwhile --help` and
    # `claude-meanwhile --help` each print the name they were invoked by.
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", nargs="?", default="play", choices=["play", "validate", "build-prompt"]
    )
    parser.add_argument("--repo", default=".", help="project directory (default: current)")
    parser.add_argument(
        "--lang",
        default=None,
        # Spells out that this is a code and names the two, because nothing
        # else on the documented path does: a user who reads "language" and
        # passes "Turkish" gets an English interface and no complaint.
        help=(
            "short language code, e.g. tr or en (default: the pool's own). "
            "tr and en are the two the interface speaks; any other code leaves "
            "the interface in English, and on build-prompt still writes the "
            "cards in it"
        ),
    )
    args = parser.parse_args(argv)

    launch = launch_dir(args.repo)  # keys the busy/idle state file
    root = repo_root(launch)  # holds .meanwhile/pool.json and scores.json

    if args.command == "build-prompt":
        # No pool exists yet — the point of this command is to build one —
        # so there is no pool.language to fall back to, unlike `play`.
        language = args.lang or strings.DEFAULT_LANGUAGE
        print(build_prompt(language=language, repo_name=root.name), end="")
        return 0

    if args.command == "validate":
        code, messages = validate(root)
        for message in messages:
            print(message)
        return code

    try:
        pool = load_pool(root / POOL_RELPATH)
    except PoolError as exc:
        # Both routes, not just the slash command: a Codex or Cursor user who
        # opens the pane before building a pool is the likeliest first run on
        # the new paths, and /meanwhile-build does not exist for them.
        print(
            f"{exc}\n\nRun /meanwhile-build inside Claude Code, or "
            "`meanwhile build-prompt` with any other agent, to create one."
        )
        return 1

    language = args.lang or pool.language
    return _run_app(
        pool=pool,
        repo_dir=root,
        status_source=lambda: state.read_state(launch)["status"],
        banner=staleness_banner(root, pool.head_sha, language=language),
        language=language,
        agent_source=lambda: state.read_state(launch)["agent"],
    )


def _run_app(**kwargs) -> int:
    from .app import MeanwhileApp  # imported late so `validate` needs no terminal

    MeanwhileApp(**kwargs).run()
    return 0


def run_hooks(argv: list[str]) -> int:
    """`meanwhile hooks install|status|uninstall` — register the busy/idle hooks.

    Claude Code users get these from the plugin; this is for Codex, Cursor and
    a standalone Claude Code.
    """
    from . import hooks_cli
    from .agents import AGENTS, agent_by_slug

    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} hooks",
        description="register meanwhile's busy/idle hooks with a coding agent",
    )
    parser.add_argument("action", choices=["install", "status", "uninstall"])
    parser.add_argument(
        "--agent",
        default="auto",
        choices=[agent.slug for agent in AGENTS] + ["auto"],
        help="which agent (default: auto — every agent already configured here)",
    )
    parser.add_argument(
        "--user",
        action="store_true",
        help="register for every project of this user, not just this one",
    )
    parser.add_argument("--repo", default=".", help="project directory (default: current)")
    args = parser.parse_args(argv)

    home = Path.home()
    repo_dir = Path(args.repo).resolve()

    if args.action == "status":
        for line in hooks_cli.status(repo=repo_dir, home=home):
            print(line)
        return 0

    if args.agent == "auto":
        targets = []
        for agent in AGENTS:
            # An agent's own directory is the only evidence that it is in use
            # here; `auto` never conjures one up from nothing.
            if not hooks_cli.config_path(agent, repo_dir, home, args.user).parent.is_dir():
                continue
            if args.user and not agent.supports_user_scope:
                print(f"{agent.label}: skipped, it cannot be hooked at the user level")
                continue
            targets.append(agent)
        if not targets:
            scope = "under your home directory" if args.user else f"in {repo_dir}"
            print(
                f"no agent config directory found {scope} — name one with --agent",
                file=sys.stderr,
            )
            return 1
    else:
        targets = [agent_by_slug(args.agent)]

    act = hooks_cli.install if args.action == "install" else hooks_cli.uninstall
    failed = False
    for agent in targets:
        try:
            print(act(agent, repo=repo_dir, home=home, user=args.user))
        except (hooks_cli.HooksError, OSError) as exc:
            # OSError too: a read-only .codex/hooks.json is a thing that
            # happens, and it is a message, not a traceback out of main().
            # Not prefixed with the label: every HooksError already names the
            # agent, by label or by the path it refused to touch.
            print(str(exc), file=sys.stderr)
            failed = True
    return 1 if failed else 0
