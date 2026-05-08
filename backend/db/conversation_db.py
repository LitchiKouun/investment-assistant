"""SQLite persistence for conversations and messages (thread-safe per-operation)."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, List, Optional, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_db_path: Path | None = None


def configure(db_path: Path) -> None:
    global _db_path
    _db_path = db_path.resolve()


def _require_path() -> Path:
    if _db_path is None:
        raise RuntimeError("conversation DB not configured; call configure() first")
    return _db_path


def _with_conn(fn: Callable[[sqlite3.Connection], T]) -> T:
    path = _require_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = sqlite3.connect(str(path), isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            return fn(conn)
        finally:
            conn.close()


def init_db() -> None:
    def _init(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
            ON messages (conversation_id, created_at);
            """
        )

    _with_conn(_init)


def _now_ts() -> int:
    return int(time.time())


def create_conversation(title: str = "新会话") -> str:
    cid = str(uuid.uuid4())
    ts = _now_ts()

    def _ins(conn: sqlite3.Connection) -> str:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (cid, title, ts, ts),
        )
        return cid

    return _with_conn(_ins)


def list_conversations() -> List[dict[str, Any]]:
    def _list(conn: sqlite3.Connection) -> List[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    return _with_conn(_list)


def get_conversation(conversation_id: str) -> Optional[dict[str, Any]]:
    def _get(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
        crow = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if crow is None:
            return None
        mrows = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        ).fetchall()
        messages = [
            {"id": r["id"], "role": r["role"], "content": r["content"], "created_at": r["created_at"]}
            for r in mrows
        ]
        out = dict(crow)
        out["messages"] = messages
        return out

    return _with_conn(_get)


def conversation_exists(conversation_id: str) -> bool:
    def _ex(conn: sqlite3.Connection) -> bool:
        r = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ? LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return r is not None

    return _with_conn(_ex)


def update_conversation_title(conversation_id: str, title: str) -> bool:
    ts = _now_ts()

    def _upd(conn: sqlite3.Connection) -> bool:
        cur = conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, ts, conversation_id),
        )
        return cur.rowcount > 0

    return _with_conn(_upd)


def delete_conversation(conversation_id: str) -> bool:
    def _del(conn: sqlite3.Connection) -> bool:
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cur.rowcount > 0

    return _with_conn(_del)


def append_message(conversation_id: str, role: str, content: str) -> str:
    mid = str(uuid.uuid4())
    ts = _now_ts()

    def _app(conn: sqlite3.Connection) -> str:
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (mid, conversation_id, role, content, ts),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (ts, conversation_id),
        )
        return mid

    return _with_conn(_app)


def maybe_set_title_from_first_message(conversation_id: str, user_text: str) -> None:
    """If title is still the default, set it from the first line of the user message."""

    def _maybe(conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return
        if row["title"] not in ("新会话", ""):
            return
        snippet = (user_text or "").strip().replace("\n", " ")
        new_title = (snippet[:12] + "…") if len(snippet) > 12 else (snippet or "新会话")
        ts = _now_ts()
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (new_title, ts, conversation_id),
        )

    _with_conn(_maybe)
