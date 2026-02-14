import sqlite3
from pathlib import Path

import pytest

from pykoclaw.db import (
    create_task,
    delete_task,
    enqueue_delivery,
    get_all_tasks,
    get_conversation,
    get_due_tasks,
    get_pending_deliveries,
    get_task,
    get_tasks_for_conversation,
    init_db,
    list_conversations,
    log_task_run,
    mark_delivered,
    mark_delivery_failed,
    parse_channel_prefix,
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


def test_init_db_creates_delivery_queue_table(tmp_path: Path) -> None:
    db = init_db(tmp_path / "test.db")
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    assert "delivery_queue" in tables


def test_parse_channel_prefix() -> None:
    assert parse_channel_prefix("wa-123@s.whatsapp.net") == "wa"
    assert parse_channel_prefix("acp-abc12345") == "acp"
    assert parse_channel_prefix("tg-987654") == "tg"
    assert parse_channel_prefix("myproject") == "chat"
    assert parse_channel_prefix("") == "chat"


def test_delivery_queue_enqueue_and_get_pending(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "wa-123@s.whatsapp.net", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t1",
        conversation="wa-123@s.whatsapp.net",
        prompt="hello",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    delivery_id = enqueue_delivery(
        db,
        task_id="t1",
        task_run_log_id=None,
        conversation="wa-123@s.whatsapp.net",
        channel_prefix="wa",
        message="Task result text",
    )
    assert isinstance(delivery_id, str)
    assert len(delivery_id) > 0

    pending = get_pending_deliveries(db, "wa")
    assert len(pending) == 1
    assert pending[0].id == delivery_id
    assert pending[0].task_id == "t1"
    assert pending[0].conversation == "wa-123@s.whatsapp.net"
    assert pending[0].channel_prefix == "wa"
    assert pending[0].message == "Task result text"
    assert pending[0].status == "pending"

    acp_pending = get_pending_deliveries(db, "acp")
    assert len(acp_pending) == 0


def test_delivery_queue_mark_delivered(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "wa-123", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t1",
        conversation="wa-123",
        prompt="hello",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    delivery_id = enqueue_delivery(
        db,
        task_id="t1",
        task_run_log_id=None,
        conversation="wa-123",
        channel_prefix="wa",
        message="result",
    )

    mark_delivered(db, delivery_id)

    pending = get_pending_deliveries(db, "wa")
    assert len(pending) == 0

    row = db.execute(
        "SELECT * FROM delivery_queue WHERE id = ?", (delivery_id,)
    ).fetchone()
    assert row["status"] == "delivered"
    assert row["delivered_at"] is not None


def test_delivery_queue_mark_failed(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "wa-123", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t1",
        conversation="wa-123",
        prompt="hello",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    delivery_id = enqueue_delivery(
        db,
        task_id="t1",
        task_run_log_id=None,
        conversation="wa-123",
        channel_prefix="wa",
        message="result",
    )

    mark_delivery_failed(db, delivery_id, "Connection refused")

    pending = get_pending_deliveries(db, "wa")
    assert len(pending) == 0

    row = db.execute(
        "SELECT * FROM delivery_queue WHERE id = ?", (delivery_id,)
    ).fetchone()
    assert row["status"] == "failed"
