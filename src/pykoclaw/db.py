from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any, TypeVar

from pydantic import BaseModel

from pykoclaw.models import Conversation, DeliveryQueueItem, ScheduledTask, TaskRunLog


class ThreadSafeConnection:
    """Thin wrapper around :class:`sqlite3.Connection` that serialises access
    with a :class:`threading.Lock`.

    All public methods that touch the underlying connection acquire the lock
    first, making it safe to share a single instance across threads (Go
    callback thread, asyncio event-loop thread, main thread).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: Any) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executemany(sql, seq_of_parameters)

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executescript(sql_script)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            self._conn.rollback()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Acquire lock, yield raw connection, commit on success / rollback on error.

        This context manager holds the lock for the entire transaction, ensuring
        that multiple statements execute atomically without releasing and
        re-acquiring the lock between them.

        Yields:
            The raw sqlite3.Connection object.

        Raises:
            Any exception raised within the context will trigger a rollback.
        """
        self._lock.acquire()
        try:
            yield self._conn
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        finally:
            self._lock.release()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def row_factory(self) -> Any:
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._conn.row_factory = value


DbConnection = sqlite3.Connection | ThreadSafeConnection

ModelT = TypeVar("ModelT", bound=BaseModel)


def _rows_to(model: type[ModelT], rows: list[sqlite3.Row]) -> list[ModelT]:
    """Convert a list of sqlite3.Row objects to a list of model instances.

    Args:
        model: The Pydantic model class to instantiate
        rows: List of sqlite3.Row objects from database query

    Returns:
        List of model instances
    """
    return [model(**row) for row in rows]


def init_db(db_path: Path) -> ThreadSafeConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(db_path), check_same_thread=False)
    raw.row_factory = sqlite3.Row
    db = ThreadSafeConnection(raw)

    db.executescript(
        dedent("""\
        CREATE TABLE IF NOT EXISTS conversations (
            name TEXT PRIMARY KEY,
            session_id TEXT,
            cwd TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id TEXT PRIMARY KEY,
            conversation TEXT NOT NULL,
            prompt TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            schedule_value TEXT NOT NULL,
            context_mode TEXT DEFAULT 'isolated',
            target_conversation TEXT,
            next_run TEXT,
            last_run TEXT,
            last_result TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS task_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            run_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            status TEXT NOT NULL,
            result TEXT,
            error TEXT,
            FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
        );

        CREATE TABLE IF NOT EXISTS delivery_queue (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            task_run_log_id INTEGER,
            conversation TEXT NOT NULL,
            channel_prefix TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_next_run ON scheduled_tasks(next_run);
        CREATE INDEX IF NOT EXISTS idx_status ON scheduled_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_task_run_logs ON task_run_logs(task_id, run_at);
        CREATE INDEX IF NOT EXISTS idx_delivery_queue_status
            ON delivery_queue(channel_prefix, status);
    """)
    )

    db.commit()
    return db


def parse_channel_prefix(conversation_name: str) -> str:
    """Extract prefix before first ``-``, defaulting to ``"chat"`` if no dash."""
    if "-" in conversation_name:
        return conversation_name.split("-", 1)[0]
    return "chat"


def enqueue_delivery(
    db: DbConnection,
    *,
    task_id: str,
    task_run_log_id: int | None,
    conversation: str,
    channel_prefix: str,
    message: str,
) -> str:
    import uuid

    delivery_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        dedent("""\
        INSERT INTO delivery_queue
            (id, task_id, task_run_log_id, conversation, channel_prefix, message, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
    """),
        (
            delivery_id,
            task_id,
            task_run_log_id,
            conversation,
            channel_prefix,
            message,
            now,
        ),
    )
    db.commit()
    return delivery_id


def get_pending_deliveries(
    db: DbConnection, channel_prefix: str
) -> list[DeliveryQueueItem]:
    rows = db.execute(
        dedent("""\
        SELECT * FROM delivery_queue
        WHERE channel_prefix = ? AND status = 'pending'
        ORDER BY created_at
    """),
        (channel_prefix,),
    ).fetchall()
    return _rows_to(DeliveryQueueItem, rows)


def mark_delivered(db: DbConnection, delivery_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "UPDATE delivery_queue SET status = 'delivered', delivered_at = ? WHERE id = ?",
        (now, delivery_id),
    )
    db.commit()


def mark_delivery_failed(db: DbConnection, delivery_id: str, error: str) -> None:
    db.execute(
        "UPDATE delivery_queue SET status = 'failed' WHERE id = ?",
        (delivery_id,),
    )
    db.commit()


def upsert_conversation(db: DbConnection, name: str, session_id: str, cwd: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        dedent("""\
        INSERT INTO conversations (name, session_id, cwd, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            session_id = excluded.session_id,
            cwd = excluded.cwd
    """),
        (name, session_id, cwd, now),
    )
    db.commit()


def get_conversation(db: DbConnection, name: str) -> Conversation | None:
    row = db.execute("SELECT * FROM conversations WHERE name = ?", (name,)).fetchone()
    return Conversation(**row) if row else None


def list_conversations(db: DbConnection) -> list[Conversation]:
    rows = db.execute("SELECT * FROM conversations ORDER BY created_at DESC").fetchall()
    return _rows_to(Conversation, rows)


def create_task(
    db: DbConnection,
    *,
    task_id: str,
    conversation: str,
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    next_run: str | None,
    context_mode: str = "group",
    target_conversation: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        dedent("""\
        INSERT INTO scheduled_tasks
            (id, conversation, prompt, schedule_type, schedule_value, context_mode,
             target_conversation, next_run, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """),
        (
            task_id,
            conversation,
            prompt,
            schedule_type,
            schedule_value,
            context_mode,
            target_conversation,
            next_run,
            "active",
            now,
        ),
    )
    db.commit()


def get_task(db: DbConnection, task_id: str) -> ScheduledTask | None:
    row = db.execute(
        "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return ScheduledTask(**row) if row else None


def get_tasks_for_conversation(
    db: DbConnection, conversation: str
) -> list[ScheduledTask]:
    rows = db.execute(
        "SELECT * FROM scheduled_tasks WHERE conversation = ? ORDER BY created_at DESC",
        (conversation,),
    ).fetchall()
    return _rows_to(ScheduledTask, rows)


def get_all_tasks(db: DbConnection) -> list[ScheduledTask]:
    rows = db.execute(
        "SELECT * FROM scheduled_tasks ORDER BY created_at DESC"
    ).fetchall()
    return _rows_to(ScheduledTask, rows)


def update_task(db: DbConnection, task_id: str, **updates: object) -> None:
    fields = []
    values = []

    for key in ["prompt", "schedule_type", "schedule_value", "next_run", "status"]:
        if key in updates:
            fields.append(f"{key} = ?")
            values.append(updates[key])

    if not fields:
        return

    values.append(task_id)
    db.execute(f"UPDATE scheduled_tasks SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()


def delete_task(db: DbConnection, task_id: str) -> None:
    if isinstance(db, ThreadSafeConnection):
        with db.transaction() as conn:
            conn.execute("DELETE FROM task_run_logs WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
    else:
        db.execute("DELETE FROM task_run_logs WHERE task_id = ?", (task_id,))
        db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        db.commit()


def get_due_tasks(db: DbConnection) -> list[ScheduledTask]:
    now = datetime.now(timezone.utc).isoformat()
    rows = db.execute(
        dedent("""\
        SELECT * FROM scheduled_tasks
        WHERE status = 'active' AND next_run IS NOT NULL AND next_run <= ?
        ORDER BY next_run
    """),
        (now,),
    ).fetchall()
    return _rows_to(ScheduledTask, rows)


def update_task_after_run(
    db: DbConnection, task_id: str, next_run: str | None, last_result: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        dedent("""\
        UPDATE scheduled_tasks
        SET next_run = ?, last_run = ?, last_result = ?, status = CASE WHEN ? IS NULL THEN 'completed' ELSE status END
        WHERE id = ?
    """),
        (next_run, now, last_result, next_run, task_id),
    )
    db.commit()


def log_task_run(
    db: DbConnection,
    *,
    task_id: str,
    run_at: str,
    duration_ms: int,
    status: str,
    result: str | None = None,
    error: str | None = None,
) -> None:
    db.execute(
        dedent("""\
        INSERT INTO task_run_logs (task_id, run_at, duration_ms, status, result, error)
        VALUES (?, ?, ?, ?, ?, ?)
    """),
        (task_id, run_at, duration_ms, status, result, error),
    )
    db.commit()
