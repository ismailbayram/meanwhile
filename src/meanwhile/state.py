"""Machine-local busy/idle state shared between an agent's hooks and the TUI."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .agents import SLUG_PATTERN

STATE_ROOT = Path.home() / ".meanwhile" / "state"

_VALID = ("busy", "idle")
_IDLE = {"status": "idle", "ts": 0.0, "agent": None}


def project_key(project_dir: str | Path) -> str:
    """Short, stable id for a project directory.

    Must stay byte-for-byte compatible with hooks/meanwhile-state.sh:
    sha256 of the resolved path, no trailing newline, first 16 hex chars.
    """
    resolved = str(Path(project_dir).resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def state_path(project_dir: str | Path, root: Path = STATE_ROOT) -> Path:
    return Path(root) / f"{project_key(project_dir)}.json"


def write_state(
    project_dir: str | Path,
    status: str,
    root: Path = STATE_ROOT,
    now: float | None = None,
    agent: str | None = None,
) -> Path:
    if status not in _VALID:
        raise ValueError(f"status must be one of {_VALID}, got {status!r}")
    if agent is not None and not SLUG_PATTERN.match(agent):
        raise ValueError(f"agent must match {SLUG_PATTERN.pattern}, got {agent!r}")
    path = state_path(project_dir, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload_data = {"status": status, "ts": now if now is not None else time.time()}
    if agent is not None:
        payload_data["agent"] = agent
    payload = json.dumps(payload_data)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)  # atomic: the TUI polls this file and must never see a half-write
    return path


def read_state(project_dir: str | Path, root: Path = STATE_ROOT) -> dict:
    try:
        data = json.loads(state_path(project_dir, root=root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_IDLE)
    if not isinstance(data, dict) or data.get("status") not in _VALID:
        return dict(_IDLE)
    agent = data.get("agent")
    if not isinstance(agent, str) or not SLUG_PATTERN.match(agent):
        agent = None
    return {"status": data["status"], "ts": float(data.get("ts", 0.0)), "agent": agent}
