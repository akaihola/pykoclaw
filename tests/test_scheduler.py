import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pykoclaw.db import create_task, get_task, init_db, upsert_conversation
from pykoclaw.models import ScheduledTask
from pykoclaw.scheduler import run_task


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
