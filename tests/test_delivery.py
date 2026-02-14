import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from pykoclaw.db import (
    create_task,
    enqueue_delivery,
    get_pending_deliveries,
    get_task,
    init_db,
    mark_delivered,
    parse_channel_prefix,
    upsert_conversation,
)
from pykoclaw.scheduler import run_task


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@dataclass
class _FakeMsg:
    type: str = "text"
    text: str = ""


async def _fake_agent_gen(*args, **kwargs):
    yield _FakeMsg(type="text", text="Scheduled task result")


def test_scheduler_enqueues_delivery_for_wa_task(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    upsert_conversation(db, "wa-5551234@s.whatsapp.net", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t1",
        conversation="wa-5551234@s.whatsapp.net",
        prompt="check weather",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    task = get_task(db, task_id="t1")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent", side_effect=_fake_agent_gen):
        asyncio.run(run_task(task, db, data_dir))

    pending = get_pending_deliveries(db, "wa")
    assert len(pending) == 1
    assert pending[0].task_id == "t1"
    assert pending[0].conversation == "wa-5551234@s.whatsapp.net"
    assert pending[0].channel_prefix == "wa"
    assert pending[0].message == "Scheduled task result"
    assert pending[0].status == "pending"


def test_scheduler_enqueues_delivery_for_acp_task(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    upsert_conversation(db, "acp-abc12345", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t2",
        conversation="acp-abc12345",
        prompt="summarize notes",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    task = get_task(db, task_id="t2")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent", side_effect=_fake_agent_gen):
        asyncio.run(run_task(task, db, data_dir))

    pending = get_pending_deliveries(db, "acp")
    assert len(pending) == 1
    assert pending[0].channel_prefix == "acp"
    assert pending[0].conversation == "acp-abc12345"


def test_empty_result_skips_delivery(db: sqlite3.Connection, data_dir: Path) -> None:
    async def _empty_gen(*args, **kwargs):
        yield _FakeMsg(type="text", text="")

    upsert_conversation(db, "wa-123", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t3",
        conversation="wa-123",
        prompt="do nothing",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    task = get_task(db, task_id="t3")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent", side_effect=_empty_gen):
        asyncio.run(run_task(task, db, data_dir))

    assert len(get_pending_deliveries(db, "wa")) == 0
    assert len(get_pending_deliveries(db, "acp")) == 0
    assert len(get_pending_deliveries(db, "chat")) == 0


def test_target_conversation_overrides_originating(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    upsert_conversation(db, "acp-source", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t4",
        conversation="acp-source",
        prompt="report",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
        target_conversation="wa-5551234@s.whatsapp.net",
    )

    task = get_task(db, task_id="t4")
    assert task is not None
    assert task.target_conversation == "wa-5551234@s.whatsapp.net"

    with patch("pykoclaw.scheduler.query_agent", side_effect=_fake_agent_gen):
        asyncio.run(run_task(task, db, data_dir))

    wa_pending = get_pending_deliveries(db, "wa")
    assert len(wa_pending) == 1
    assert wa_pending[0].conversation == "wa-5551234@s.whatsapp.net"

    acp_pending = get_pending_deliveries(db, "acp")
    assert len(acp_pending) == 0


def test_channel_prefix_parsing_edge_cases() -> None:
    assert parse_channel_prefix("wa-123@s.whatsapp.net") == "wa"
    assert parse_channel_prefix("acp-abc12345") == "acp"
    assert parse_channel_prefix("tg-987654") == "tg"
    assert parse_channel_prefix("chat-session") == "chat"
    assert parse_channel_prefix("myproject") == "chat"
    assert parse_channel_prefix("") == "chat"
    assert parse_channel_prefix("wa-") == "wa"
    assert parse_channel_prefix("-leading") == ""


def test_delivery_pickup_filters_by_prefix(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "wa-111", "s1", "/tmp")
    upsert_conversation(db, "acp-222", "s2", "/tmp")
    create_task(
        db,
        task_id="t5",
        conversation="wa-111",
        prompt="p",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )
    create_task(
        db,
        task_id="t6",
        conversation="acp-222",
        prompt="p",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    enqueue_delivery(
        db,
        task_id="t5",
        task_run_log_id=None,
        conversation="wa-111",
        channel_prefix="wa",
        message="wa msg",
    )
    enqueue_delivery(
        db,
        task_id="t6",
        task_run_log_id=None,
        conversation="acp-222",
        channel_prefix="acp",
        message="acp msg",
    )

    wa = get_pending_deliveries(db, "wa")
    assert len(wa) == 1
    assert wa[0].message == "wa msg"

    acp = get_pending_deliveries(db, "acp")
    assert len(acp) == 1
    assert acp[0].message == "acp msg"

    chat = get_pending_deliveries(db, "chat")
    assert len(chat) == 0


def test_mark_delivered_updates_status(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "wa-111", "s1", "/tmp")
    create_task(
        db,
        task_id="t7",
        conversation="wa-111",
        prompt="p",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    delivery_id = enqueue_delivery(
        db,
        task_id="t7",
        task_run_log_id=None,
        conversation="wa-111",
        channel_prefix="wa",
        message="result",
    )

    assert len(get_pending_deliveries(db, "wa")) == 1

    mark_delivered(db, delivery_id)

    assert len(get_pending_deliveries(db, "wa")) == 0

    row = db.execute(
        "SELECT * FROM delivery_queue WHERE id = ?", (delivery_id,)
    ).fetchone()
    assert row["status"] == "delivered"
    assert row["delivered_at"] is not None


def test_error_task_does_not_enqueue_delivery(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    upsert_conversation(db, "wa-err", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t-err",
        conversation="wa-err",
        prompt="fail",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    task = get_task(db, task_id="t-err")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent") as mock:
        mock.side_effect = RuntimeError("Agent crashed")
        asyncio.run(run_task(task, db, data_dir))

    assert len(get_pending_deliveries(db, "wa")) == 0
