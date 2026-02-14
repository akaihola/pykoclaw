import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pykoclaw.db import (
    create_task,
    get_pending_deliveries,
    get_task,
    init_db,
    upsert_conversation,
)
from pykoclaw.models import ScheduledTask
from pykoclaw.scheduler import run_task


@dataclass
class _FakeMsg:
    type: str = "text"
    text: str = ""


async def _fake_agent_gen(*args, **kwargs):
    yield _FakeMsg(type="text", text="Hello from agent")


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


def test_cron_task_survives_error(db: sqlite3.Connection, data_dir: Path) -> None:
    """Verify recurring tasks get next_run even when agent call fails."""
    upsert_conversation(db, "test", "sess-1", "/tmp/test")

    create_task(
        db,
        task_id="cron-task",
        conversation="test",
        prompt="test prompt",
        schedule_type="cron",
        schedule_value="0 * * * *",
        next_run="2025-01-01T00:00:00+00:00",
        context_mode="isolated",
    )

    task = get_task(db, task_id="cron-task")
    assert task is not None
    assert task.schedule_type == "cron"
    assert task.status == "active"

    with patch("pykoclaw.scheduler.query_agent") as mock_query_agent:
        mock_query_agent.side_effect = RuntimeError("Agent failed")

        asyncio.run(run_task(task, db, data_dir))

    updated_task = get_task(db, task_id="cron-task")
    assert updated_task is not None
    assert updated_task.next_run is not None
    assert updated_task.status == "active"
    assert "Error: Agent failed" in updated_task.last_result


def test_interval_task_survives_error(db: sqlite3.Connection, data_dir: Path) -> None:
    """Verify interval tasks get next_run even when agent call fails."""
    upsert_conversation(db, "test", "sess-1", "/tmp/test")

    create_task(
        db,
        task_id="interval-task",
        conversation="test",
        prompt="test prompt",
        schedule_type="interval",
        schedule_value="3600000",
        next_run="2025-01-01T00:00:00+00:00",
        context_mode="isolated",
    )

    task = get_task(db, task_id="interval-task")
    assert task is not None
    assert task.schedule_type == "interval"
    assert task.status == "active"

    with patch("pykoclaw.scheduler.query_agent") as mock_query_agent:
        mock_query_agent.side_effect = RuntimeError("Agent failed")

        asyncio.run(run_task(task, db, data_dir))

    updated_task = get_task(db, task_id="interval-task")
    assert updated_task is not None
    assert updated_task.next_run is not None
    assert updated_task.status == "active"
    assert "Error: Agent failed" in updated_task.last_result


def test_once_task_marked_completed_on_error(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    """Verify once tasks are marked completed on error."""
    upsert_conversation(db, "test", "sess-1", "/tmp/test")

    create_task(
        db,
        task_id="once-task",
        conversation="test",
        prompt="test prompt",
        schedule_type="once",
        schedule_value="2025-01-01T00:00:00+00:00",
        next_run="2025-01-01T00:00:00+00:00",
        context_mode="isolated",
    )

    task = get_task(db, task_id="once-task")
    assert task is not None
    assert task.schedule_type == "once"
    assert task.status == "active"

    with patch("pykoclaw.scheduler.query_agent") as mock_query_agent:
        mock_query_agent.side_effect = RuntimeError("Agent failed")

        asyncio.run(run_task(task, db, data_dir))

    updated_task = get_task(db, task_id="once-task")
    assert updated_task is not None
    assert updated_task.next_run is None
    assert updated_task.status == "completed"
    assert "Error: Agent failed" in updated_task.last_result


def test_delivery_enqueued_after_successful_task(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    upsert_conversation(db, "wa-123@s.whatsapp.net", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t-del",
        conversation="wa-123@s.whatsapp.net",
        prompt="test prompt",
        schedule_type="once",
        schedule_value="2025-01-01T00:00:00+00:00",
        next_run="2025-01-01T00:00:00+00:00",
        context_mode="isolated",
    )

    task = get_task(db, task_id="t-del")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent", side_effect=_fake_agent_gen):
        asyncio.run(run_task(task, db, data_dir))

    pending = get_pending_deliveries(db, "wa")
    assert len(pending) == 1
    assert pending[0].task_id == "t-del"
    assert pending[0].conversation == "wa-123@s.whatsapp.net"
    assert pending[0].channel_prefix == "wa"
    assert pending[0].message == "Hello from agent"
    assert pending[0].status == "pending"


def test_no_delivery_on_error(db: sqlite3.Connection, data_dir: Path) -> None:
    upsert_conversation(db, "wa-123", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t-err",
        conversation="wa-123",
        prompt="test prompt",
        schedule_type="once",
        schedule_value="2025-01-01T00:00:00+00:00",
        next_run="2025-01-01T00:00:00+00:00",
        context_mode="isolated",
    )

    task = get_task(db, task_id="t-err")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent") as mock:
        mock.side_effect = RuntimeError("Agent failed")
        asyncio.run(run_task(task, db, data_dir))

    pending = get_pending_deliveries(db, "wa")
    assert len(pending) == 0


def test_no_delivery_on_empty_result(db: sqlite3.Connection, data_dir: Path) -> None:
    async def _empty_gen(*args, **kwargs):
        yield _FakeMsg(type="text", text="")

    upsert_conversation(db, "wa-123", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t-empty",
        conversation="wa-123",
        prompt="test prompt",
        schedule_type="once",
        schedule_value="2025-01-01T00:00:00+00:00",
        next_run="2025-01-01T00:00:00+00:00",
        context_mode="isolated",
    )

    task = get_task(db, task_id="t-empty")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent", side_effect=_empty_gen):
        asyncio.run(run_task(task, db, data_dir))

    pending = get_pending_deliveries(db, "wa")
    assert len(pending) == 0
