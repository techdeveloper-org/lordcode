"""Persisted chat/generation history for the web UI.

Each completed (or failed) /generate call is saved as one session -- its own
task, files, attempts, and metadata -- so the UI can show a chat-style
sidebar (like Cursor/ChatGPT) instead of a single-shot form with nothing to
come back to. Stored as one JSON file, capped at MAX_SESSIONS, newest first.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

SESSIONS_FILE = Path(__file__).resolve().parent.parent.parent / "vishwakarma-sessions.json"
MAX_SESSIONS = 50

_lock = Lock()


def _read_all() -> list[dict]:
    """Read every stored session, newest first. Returns [] if the file doesn't exist yet."""
    if not SESSIONS_FILE.exists():
        return []
    try:
        return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _write_all(sessions: list[dict]) -> None:
    """Overwrite the sessions file with the given list."""
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")


def save_session(
    task: str,
    engineered_prompt: str,
    language: str,
    complexity: str,
    plan: str | None,
    skill_used: str | None,
    agent_used: str | None,
    passed: bool,
    files: dict[str, str],
    attempts: list[dict],
    workdir: str | None = None,
) -> dict:
    """Persist one completed generation as a new session.

    Returns:
        The full session dict that was saved, including its generated id.
    """
    session = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "engineered_prompt": engineered_prompt,
        "language": language,
        "complexity": complexity,
        "plan": plan,
        "skill_used": skill_used,
        "agent_used": agent_used,
        "passed": passed,
        "files": files,
        "attempts": attempts,
        "workdir": workdir,
    }
    with _lock:
        sessions = _read_all()
        sessions.insert(0, session)
        _write_all(sessions[:MAX_SESSIONS])
    return session


def list_sessions() -> list[dict]:
    """Return lightweight summaries of every stored session, newest first."""
    return [
        {
            "id": s["id"],
            "created_at": s["created_at"],
            "task": s["task"],
            "language": s["language"],
            "passed": s["passed"],
        }
        for s in _read_all()
    ]


def get_session(session_id: str) -> dict | None:
    """Look up one full session by id."""
    for session in _read_all():
        if session["id"] == session_id:
            return session
    return None


def delete_session(session_id: str) -> bool:
    """Remove one session by id. Returns True if it existed."""
    with _lock:
        sessions = _read_all()
        remaining = [s for s in sessions if s["id"] != session_id]
        if len(remaining) == len(sessions):
            return False
        _write_all(remaining)
        return True
