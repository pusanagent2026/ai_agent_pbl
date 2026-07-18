"""Per-session conversation memory for the web UI (SQLite).

The task-planning agent is otherwise stateless -- each /api/analyze-tasks
request builds a fresh message list, so follow-up questions like "그 중 3번
누구 줘" have no context. This store keeps the recent turns per browser
session so web.py can feed them back to the model (a sliding window, not the
full history), and clears them on logout.

Deliberately standalone and separate from session_store.py: it holds
conversation text (not credentials), so no encryption and no dependency on
the in-memory SESSIONS credential store. Keyed by the session cookie id.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# How many recent turns (user + assistant messages combined) to replay to the
# model. Bounds token cost; older turns fall out of the window.
HISTORY_TURNS = int(os.environ.get("CONVERSATION_HISTORY_TURNS", "8"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    turn_index  INTEGER NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id, turn_index);

CREATE TABLE IF NOT EXISTS analysis_state (
    session_id      TEXT PRIMARY KEY,
    proposed_tasks  TEXT,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""


def _db_path() -> str:
    return os.environ.get("CONVERSATION_DB_PATH", "conversation.db")


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(_db_path())
    try:
        connection.executescript(_SCHEMA)
        with connection:
            yield connection
    finally:
        connection.close()


def load_recent(session_id: str, limit: int = HISTORY_TURNS) -> list[dict[str, str]]:
    """Return the most recent `limit` turns in chronological order (oldest
    first), shaped as OpenAI chat messages ready to splice before the current
    question."""
    if not session_id:
        return []
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT role, content FROM conversation_turns
            WHERE session_id = ?
            ORDER BY turn_index DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]


def append(session_id: str, role: str, content: str) -> None:
    if not session_id or not content:
        return
    with _connection() as connection:
        row = connection.execute(
            "SELECT COALESCE(MAX(turn_index), -1) FROM conversation_turns WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        next_index = (row[0] if row else -1) + 1
        connection.execute(
            "INSERT INTO conversation_turns (session_id, turn_index, role, content) "
            "VALUES (?, ?, ?, ?)",
            (session_id, next_index, role, content),
        )


def save_analysis(session_id: str, proposed_tasks: Any) -> None:
    if not session_id:
        return
    payload = json.dumps(proposed_tasks or [], ensure_ascii=False)
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO analysis_state (session_id, proposed_tasks, updated_at)
            VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT(session_id) DO UPDATE SET
                proposed_tasks = excluded.proposed_tasks,
                updated_at = excluded.updated_at
            """,
            (session_id, payload),
        )


def clear(session_id: str) -> None:
    if not session_id:
        return
    with _connection() as connection:
        connection.execute("DELETE FROM conversation_turns WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM analysis_state WHERE session_id = ?", (session_id,))
