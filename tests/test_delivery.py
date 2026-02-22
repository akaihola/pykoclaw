import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from claude_agent_sdk import ProcessError

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
from pykoclaw.scheduler import resolve_delivery_target, run_task


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


async def _fake_agent_gen_with_reply_tags(*args, **kwargs):
    yield _FakeMsg(type="text", text="<reply>\n🍌 BANANAS! 🍌\n</reply>")


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


def test_reply_tags_stripped_from_delivery_message(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    """Agent output wrapped in <reply> tags should have the tags stripped
    before the message is enqueued for delivery."""
    upsert_conversation(db, "wa-tyko-group@g.us", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t-reply",
        conversation="wa-tyko-group@g.us",
        prompt="remind about bananas",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    task = get_task(db, task_id="t-reply")
    assert task is not None

    with patch(
        "pykoclaw.scheduler.query_agent",
        side_effect=_fake_agent_gen_with_reply_tags,
    ):
        asyncio.run(run_task(task, db, data_dir))

    pending = get_pending_deliveries(db, "wa")
    assert len(pending) == 1
    assert "<reply>" not in pending[0].message
    assert "</reply>" not in pending[0].message
    assert pending[0].message == "🍌 BANANAS! 🍌"


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


def test_target_conversation_bare_jid_inherits_prefix(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    """When target_conversation is a bare JID (no channel prefix), the scheduler
    should inherit the channel prefix from task.conversation so the delivery
    is routable.  This is the 'BANANAS bug' — see scheduler.py."""
    upsert_conversation(db, "wa-tyko-120363407060889798@g.us", "sess-1", "/tmp/test")
    create_task(
        db,
        task_id="t-bare",
        conversation="wa-tyko-120363407060889798@g.us",
        prompt="remind about bananas",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
        target_conversation="120363407060889798@g.us",
    )

    task = get_task(db, task_id="t-bare")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent", side_effect=_fake_agent_gen):
        asyncio.run(run_task(task, db, data_dir))

    # Must be picked up by the 'wa' channel, NOT stuck as 'chat'
    wa_pending = get_pending_deliveries(db, "wa")
    assert len(wa_pending) == 1
    assert wa_pending[0].channel_prefix == "wa"
    # Conversation should include the full prefixed name
    assert wa_pending[0].conversation == "wa-tyko-120363407060889798@g.us"

    # Must NOT end up in the 'chat' dead-letter channel
    chat_pending = get_pending_deliveries(db, "chat")
    assert len(chat_pending) == 0


def test_target_conversation_matrix_bare_room_inherits_prefix(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    """Same as above but for Matrix — bare room ID should inherit 'matrix' prefix."""
    upsert_conversation(
        db, "matrix-!RHetEGOWFgXEsOojtZ:matrix.org", "sess-1", "/tmp/test"
    )
    create_task(
        db,
        task_id="t-matrix-bare",
        conversation="matrix-!RHetEGOWFgXEsOojtZ:matrix.org",
        prompt="daily report",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
        target_conversation="!RHetEGOWFgXEsOojtZ:matrix.org",
    )

    task = get_task(db, task_id="t-matrix-bare")
    assert task is not None

    with patch("pykoclaw.scheduler.query_agent", side_effect=_fake_agent_gen):
        asyncio.run(run_task(task, db, data_dir))

    matrix_pending = get_pending_deliveries(db, "matrix")
    assert len(matrix_pending) == 1
    assert matrix_pending[0].conversation == "matrix-!RHetEGOWFgXEsOojtZ:matrix.org"

    chat_pending = get_pending_deliveries(db, "chat")
    assert len(chat_pending) == 0


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


def test_scheduler_retries_on_process_error(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    """When session resume raises ProcessError, the scheduler should clear
    the session and retry fresh — mirroring dispatch_to_agent's behavior."""
    upsert_conversation(db, "wa-retry", "stale-sess", "/tmp/test")
    create_task(
        db,
        task_id="t-retry",
        conversation="wa-retry",
        prompt="check weather",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    task = get_task(db, task_id="t-retry")
    assert task is not None

    call_count = 0

    async def _gen_with_retry(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs.get("resume_session_id") == "stale-sess":
            raise ProcessError("CLI crash", exit_code=1)
        yield _FakeMsg(type="text", text="Retried OK")

    with patch("pykoclaw.scheduler.query_agent", side_effect=_gen_with_retry):
        asyncio.run(run_task(task, db, data_dir))

    assert call_count == 2
    wa_pending = get_pending_deliveries(db, "wa")
    assert len(wa_pending) == 1
    assert wa_pending[0].message == "Retried OK"


def test_scheduler_process_error_propagates_when_fresh(
    db: sqlite3.Connection, data_dir: Path
) -> None:
    """ProcessError with no session to resume should propagate as an error
    (logged, not re-raised — the outer except Exception catches it)."""
    upsert_conversation(db, "wa-noresume", None, "/tmp/test")
    create_task(
        db,
        task_id="t-noresume",
        conversation="wa-noresume",
        prompt="check weather",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )

    task = get_task(db, task_id="t-noresume")
    assert task is not None

    async def _gen_crash(*args, **kwargs):
        raise ProcessError("CLI crash", exit_code=1)
        yield  # noqa: RET503

    with patch("pykoclaw.scheduler.query_agent", side_effect=_gen_crash):
        # Should not raise — the outer except Exception catches it
        asyncio.run(run_task(task, db, data_dir))

    # No delivery enqueued (error path)
    assert len(get_pending_deliveries(db, "wa")) == 0


def test_resolve_delivery_target_endswith_boundary() -> None:
    """Bare target must match on a '-' boundary, not arbitrary substring.
    e.g. target='o-foo@g.us' must NOT match origin suffix 'tyko-foo@g.us'."""
    from pykoclaw.models import ScheduledTask

    task = ScheduledTask(
        id="t-boundary",
        conversation="wa-tyko-foo@g.us",
        prompt="test",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        target_conversation="o-foo@g.us",
        created_at="2025-01-01T00:00:00",
    )

    conv, prefix = resolve_delivery_target(task)
    # Must NOT reuse "wa-tyko-foo@g.us" — the bare target "o-foo@g.us"
    # doesn't match on a dash boundary, so it should be prepended.
    assert conv == "wa-o-foo@g.us"
    assert prefix == "wa"


def test_resolve_delivery_target_exact_suffix_match() -> None:
    """Bare target that exactly matches origin suffix (after first dash)."""
    from pykoclaw.models import ScheduledTask

    task = ScheduledTask(
        id="t-exact",
        conversation="wa-120363@g.us",
        prompt="test",
        schedule_type="once",
        schedule_value="2020-01-01T00:00:00Z",
        target_conversation="120363@g.us",
        created_at="2025-01-01T00:00:00",
    )

    conv, prefix = resolve_delivery_target(task)
    # Exact match of the suffix — reuse origin
    assert conv == "wa-120363@g.us"
    assert prefix == "wa"
