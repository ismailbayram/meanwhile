"""Register meanwhile's busy/idle hooks with an agent, without its plugin system.

Claude Code and Codex can get these two hooks from the plugin; Cursor has no
plugin mechanism, and OpenCode's is a JavaScript file somebody has to put in
place, so the registration has to be written by hand. This module does it.

Every failure mode here is silent: a registration written to the wrong path,
naming the wrong event, or pointing at a script that has moved raises nothing
at all — the pane simply never wakes, and nothing anywhere says why. So this
module refuses rather than guesses. A config file it cannot parse is an error
instead of something to overwrite, and a scope an agent cannot honour is an
error carrying its reason.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .agents import AGENTS, MARKER, Agent, merge, plugin_source, registered_commands, unmerge

SCRIPT_NAME = "meanwhile-state.sh"

#: Agents whose project-scope config file has no gitignored sibling to move to,
#: so the registration we write there is one the user is likely to commit.
#: Claude Code is absent on purpose: its project registration goes to
#: `.claude/settings.local.json`, which is the gitignored one already.
_COMMITTED_PROJECT_CONFIG = ("codex", "cursor", "opencode")

#: What `uninstall` reads as "the file held nothing but ours": an empty
#: document, or the bare "version" key `merge` adds for Cursor.
_EMPTY_DOCUMENTS = ({}, {"version": 1})

#: Appended to an agent's "not installed" line. `status` reads the
#: registration files this module writes and nothing else, so a Claude Code
#: plugin install — which registers the same two hooks through its own
#: hooks.json — is invisible here. Detecting it would mean reading Claude
#: Code's internal install state, so the line says what it can and cannot see
#: instead, so nobody reads `not installed` and adds a redundant second copy.
_NOT_INSTALLED_NOTES = {"claude": " (the plugin registers its own hooks separately)"}


class HooksError(Exception):
    """A registration that could not work, refused with its reason."""


def packaged_script() -> Path:
    """The copy of the hook script that ships inside the wheel.

    A second copy lives at `hooks/meanwhile-state.sh` for the plugin, which can
    only name its own file through ${CLAUDE_PLUGIN_ROOT}. The two are held
    byte-identical by a test.
    """
    return Path(__file__).resolve().parent / SCRIPT_NAME


def installed_script(home: str | Path | None = None) -> Path:
    """Where the registrations point — a copy under the user's home.

    Never the packaged file itself: under `uvx` the package lives in a cache
    directory that can be reclaimed at any time, and a registration pointing
    there would quietly stop writing the state file.
    """
    base = Path.home() if home is None else Path(home)
    return base / ".meanwhile" / SCRIPT_NAME


#: The default of `installed_script`, spelled out for callers that only need
#: the one path (each function takes `home` so tests can point it elsewhere).
INSTALLED_SCRIPT = installed_script()


def install_script(dest: str | Path) -> Path:
    """Copy the packaged script to `dest`, executable. Returns `dest`."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(packaged_script(), dest)
    dest.chmod(0o755)
    return dest


def config_path(agent: Agent, repo: str | Path, home: str | Path, user: bool = False) -> Path:
    """The config file this agent reads its hooks from, in the given scope."""
    if user:
        return Path(home) / agent.user_relpath
    return Path(repo) / agent.project_relpath


def agent_dir(agent: Agent, repo: str | Path, home: str | Path, user: bool = False) -> Path:
    """The directory whose existence says this agent is in use in that scope.

    Normally the one the config file sits in. OpenCode's plugin file sits one
    level further down, in a `plugins/` directory most projects do not have
    until something is installed into it.
    """
    parent = config_path(agent, repo, home, user).parent
    return parent.parent if agent.shape == "opencode" else parent


def _is_plugin_file(agent: Agent) -> bool:
    """Whether the registration is a whole file of ours rather than entries
    merged into somebody else's JSON."""
    return agent.shape == "opencode"


def _read_plugin(path: Path) -> str | None:
    """Our plugin file's text, `None` when there is no file.

    A file at that path we did not write is a `HooksError`, for the same
    reason an unparseable config is: it is somebody's own plugin, and writing
    or deleting over it would take their work with it.
    """
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise HooksError(f"{path} cannot be read ({exc}); fix it and run this again") from exc
    if MARKER not in text:
        raise HooksError(f"{path} exists and was not written by meanwhile; move it and run this again")
    return text


def _write_text(path: Path, text: str) -> None:
    """Write `text` to `path`, atomically. See `_write_document`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.meanwhile.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _read_document(path: Path) -> dict:
    """The JSON object at `path`, `{}` when there is no file.

    A file we cannot parse is a `HooksError`: it is somebody's hand-edited
    config, and overwriting it with ours would take their settings with it.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            # A zero-byte (or whitespace-only) file has nothing to lose, so
            # leniency here costs none of the safety the strictness buys.
            return {}
        document = json.loads(text)
    except (OSError, ValueError) as exc:
        raise HooksError(f"{path} is not valid JSON ({exc}); fix it and run this again") from exc
    if not isinstance(document, dict):
        raise HooksError(f"{path} does not hold a JSON object; fix it and run this again")
    return document


def _write_document(path: Path, document: dict) -> None:
    """Write `document` to `path`, atomically.

    `write_text` truncates before it writes, so a crash or a full disk between
    the two would destroy somebody's settings file — from the one function
    whose whole job is not losing a config. Temp file beside the target (same
    filesystem, so `os.replace` is a rename) and then one atomic swap, exactly
    as the hook script next door writes the state file.
    """
    _write_text(path, json.dumps(document, indent=2) + "\n")


def _tracked_by_git(path: Path) -> bool:
    """Whether `path` is in a git index. Advice only — never a reason to fail.

    Any trouble running git at all (not installed, not a repo, a timeout) reads
    as "not tracked": the worst outcome of getting this wrong is a note the
    user does not see.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path.name],
            cwd=str(path.parent),
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _tracked_note(path: Path, agent: Agent, user: bool) -> str:
    """The warning for a registration that is about to be committed.

    The command we write carries an absolute path to this machine's copy of the
    script. Codex and Cursor have no gitignored sibling to move to, and their
    hooks.json is commonly committed, so all we can do is say so.

    Already tracked is the rare case. The dominant one is the opposite: this
    very install creates `.codex/hooks.json` from nothing and the user commits
    it afterwards, when git tracks nothing yet — so the note goes out for every
    project-scope install of theirs, tracked or not, only worded differently.
    """
    if _tracked_by_git(path):
        return (
            f"\nnote: {path} is tracked by git, and the path recorded in it is specific to "
            "this machine.\n      Teammates who commit it will run a script that does not "
            "exist for them."
        )
    if user or agent.slug not in _COMMITTED_PROJECT_CONFIG:
        return ""
    return (
        f"\nnote: the path recorded in {path} is specific to this machine.\n"
        "      Commit it and teammates will run a script that does not exist for them."
    )


def install(agent: Agent, repo: str | Path, home: str | Path, user: bool = False) -> str:
    """Register our two hooks for `agent`, and report what was written."""
    if user and not agent.supports_user_scope:
        raise HooksError(
            f"{agent.label} runs user-level hooks from ~/{Path(agent.user_relpath).parts[0]}/, "
            "but the script keys the state file on its working directory — a user-level "
            "registration would key the wrong directory and never wake the pane. "
            f"Install it per project instead: meanwhile hooks install --agent {agent.slug}"
        )
    # Read and validate before copying anything: a refused install must leave
    # no trace, and the script copy is a write like any other.
    path = config_path(agent, repo, home, user)
    if _is_plugin_file(agent):
        _read_plugin(path)
        script = install_script(installed_script(home))
        _write_text(path, plugin_source(str(script), agent))
        return f"{agent.label}: plugin written to {path}{_tracked_note(path, agent, user)}"
    document = _read_document(path)
    script = install_script(installed_script(home))
    _write_document(path, merge(document, agent, str(script)))
    return f"{agent.label}: hooks registered in {path}{_tracked_note(path, agent, user)}"


def uninstall(agent: Agent, repo: str | Path, home: str | Path, user: bool = False) -> str:
    """Take our two hooks — and only ours — back out, and report what changed."""
    path = config_path(agent, repo, home, user)
    if not path.exists():
        return f"{agent.label}: nothing to remove, {path} does not exist"
    if _is_plugin_file(agent):
        _read_plugin(path)
        path.unlink()
        return f"{agent.label}: plugin removed, {path} deleted"
    remaining = unmerge(_read_document(path), agent)
    if remaining in _EMPTY_DOCUMENTS:
        # The file held nothing but our registration, so leave no husk behind.
        path.unlink()
        return f"{agent.label}: hooks removed, {path} deleted"
    _write_document(path, remaining)
    return f"{agent.label}: hooks removed from {path}"


def _script_note(home: str | Path) -> str:
    """How the installed copy of the script compares to the packaged one.

    A registration keeps working after an upgrade only because it points at
    this copy — which also means an upgrade cannot refresh it. Nothing else
    would report the difference.
    """
    script = installed_script(home)
    if not script.exists():
        return " (stale: the script copy is missing — reinstall)"
    if script.read_bytes() != packaged_script().read_bytes():
        return " (stale: script copy differs from the packaged one — reinstall)"
    return ""


def status(repo: str | Path, home: str | Path) -> list[str]:
    """One line per agent: whether our hooks are registered, and where."""
    note = _script_note(home)
    lines = []
    for agent in AGENTS:
        scopes, unreadable = [], []
        for scope, user in (("project", False), ("user", True)):
            if user and not agent.supports_user_scope:
                continue
            path = config_path(agent, repo, home, user)
            try:
                if _is_plugin_file(agent):
                    registered = _read_plugin(path) is not None
                else:
                    registered = bool(registered_commands(_read_document(path), agent))
            except HooksError:
                unreadable.append(str(path))
                continue
            if registered:
                scopes.append(scope)
        if scopes:
            line = f"{agent.slug} ({agent.label}): installed ({', '.join(scopes)}){note}"
            if unreadable:
                line += f", unreadable config: {', '.join(unreadable)}"
        elif unreadable:
            # Not "not installed": we do not know, and saying so would be a
            # guess in the one direction the user cannot check.
            line = f"{agent.slug} ({agent.label}): unreadable config: {', '.join(unreadable)}"
        else:
            line = (
                f"{agent.slug} ({agent.label}): not installed"
                f"{_NOT_INSTALLED_NOTES.get(agent.slug, '')}"
            )
        lines.append(line)
    return lines
