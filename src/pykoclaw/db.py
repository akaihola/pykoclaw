import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

from pykoclaw.models import Conversation, ScheduledTask


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

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

        CREATE INDEX IF NOT EXISTS idx_next_run ON scheduled_tasks(next_run);
        CREATE INDEX IF NOT EXISTS idx_status ON scheduled_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_task_run_logs ON task_run_logs(task_id, run_at);
    """)
    )

    db.commit()
    return db


def upsert_conversation(
    db: sqlite3.Connection, name: str, session_id: str, cwd: str
) -> None:
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


def get_conversation(db: sqlite3.Connection, name: str) -> Conversation | None:
    row = db.execute("SELECT * FROM conversations WHERE name = ?", (name,)).fetchone()
    return Conversation(**row) if row else None


def list_conversations(db: sqlite3.Connection) -> list[Conversation]:
    rows = db.execute("SELECT * FROM conversations ORDER BY created_at DESC").fetchall()
    return [Conversation(**row) for row in rows]


def create_task(
    db: sqlite3.Connection,
    *,
    id: str,
    conversation: str,
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    next_run: str | None,
    context_mode: str = "isolated",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        dedent("""\
        INSERT INTO scheduled_tasks (id, conversation, prompt, schedule_type, schedule_value, context_mode, next_run, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """),
        (
            id,
            conversation,
            prompt,
            schedule_type,
            schedule_value,
            context_mode,
            next_run,
            "active",
            now,
        ),
    )
    db.commit()


def get_task(db: sqlite3.Connection, id: str) -> ScheduledTask | None:
    row = db.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (id,)).fetchone()
    return ScheduledTask(**row) if row else None


def get_tasks_for_conversation(
    db: sqlite3.Connection, conversation: str
) -> list[ScheduledTask]:
    rows = db.execute(
        "SELECT * FROM scheduled_tasks WHERE conversation = ? ORDER BY created_at DESC",
        (conversation,),
    ).fetchall()
    return [ScheduledTask(**row) for row in rows]


def get_all_tasks(db: sqlite3.Connection) -> list[ScheduledTask]:
    rows = db.execute(
        "SELECT * FROM scheduled_tasks ORDER BY created_at DESC"
    ).fetchall()
    return [ScheduledTask(**row) for row in rows]


def update_task(db: sqlite3.Connection, id: str, **updates: object) -> None:
    fields = []
    values = []

    for key in ["prompt", "schedule_type", "schedule_value", "next_run", "status"]:
        if key in updates:
            fields.append(f"{key} = ?")
            values.append(updates[key])

    if not fields:
        return

    values.append(id)
    db.execute(f"UPDATE scheduled_tasks SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()


def delete_task(db: sqlite3.Connection, id: str) -> None:
    db.execute("DELETE FROM task_run_logs WHERE task_id = ?", (id,))
    db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (id,))
    db.commit()


def get_due_tasks(db: sqlite3.Connection) -> list[ScheduledTask]:
    now = datetime.now(timezone.utc).isoformat()
    rows = db.execute(
        dedent("""\
        SELECT * FROM scheduled_tasks
        WHERE status = 'active' AND next_run IS NOT NULL AND next_run <= ?
        ORDER BY next_run
    """),
        (now,),
    ).fetchall()
    return [ScheduledTask(**row) for row in rows]


def update_task_after_run(
    db: sqlite3.Connection, id: str, next_run: str | None, last_result: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        dedent("""\
        UPDATE scheduled_tasks
        SET next_run = ?, last_run = ?, last_result = ?, status = CASE WHEN ? IS NULL THEN 'completed' ELSE status END
        WHERE id = ?
    """),
        (next_run, now, last_result, next_run, id),
    )
    db.commit()


def log_task_run(
    db: sqlite3.Connection,
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
