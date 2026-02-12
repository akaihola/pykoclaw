import sqlite3
from pathlib import Path

import pytest

from pykoclaw.db import (
    create_task,
    delete_task,
    get_all_tasks,
    get_conversation,
    get_due_tasks,
    get_task,
    get_tasks_for_conversation,
    init_db,
    list_conversations,
    log_task_run,
    update_task,
    upsert_conversation,
)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


def test_init_db_creates_tables(tmp_path: Path) -> None:
    db = init_db(tmp_path / "test.db")
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    assert "conversations" in tables
    assert "scheduled_tasks" in tables
    assert "task_run_logs" in tables


def test_conversation_crud(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    conv = get_conversation(db, "test")
    assert conv is not None
    assert conv.name == "test"
    assert conv.session_id == "sess-1"
    assert conv.cwd == "/tmp/test"

    convs = list_conversations(db)
    assert len(convs) == 1
    assert convs[0].name == "test"


def test_task_crud(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t1",
        conversation="test",
        prompt="hello",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    task = get_task(db, task_id="t1")
    assert task is not None
    assert task.id == "t1"
    assert task.conversation == "test"
    assert task.prompt == "hello"
    assert task.status == "active"

    tasks = get_tasks_for_conversation(db, "test")
    assert len(tasks) == 1
    assert tasks[0].id == "t1"

    all_tasks = get_all_tasks(db)
    assert len(all_tasks) == 1

    update_task(db, task_id="t1", status="paused")
    task = get_task(db, task_id="t1")
    assert task is not None
    assert task.status == "paused"

    delete_task(db, task_id="t1")
    task = get_task(db, task_id="t1")
    assert task is None


def test_due_tasks(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t1",
        conversation="test",
        prompt="hello",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    due = get_due_tasks(db)
    assert len(due) == 1
    assert due[0].id == "t1"


def test_log_task_run(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t1",
        conversation="test",
        prompt="hello",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    log_task_run(
        db,
        task_id="t1",
        run_at="2020-01-01T00:00:00Z",
        duration_ms=100,
        status="success",
        result="ok",
    )

    logs = db.execute(
        "SELECT * FROM task_run_logs WHERE task_id = ?", ("t1",)
    ).fetchall()
    assert len(logs) == 1
    assert logs[0]["task_id"] == "t1"
    assert logs[0]["duration_ms"] == 100
    assert logs[0]["status"] == "success"
    assert logs[0]["result"] == "ok"
