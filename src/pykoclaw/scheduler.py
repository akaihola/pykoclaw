import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from pykoclaw.agent_core import query_agent
from pykoclaw.db import (
    DbConnection,
    enqueue_delivery,
    get_conversation,
    get_due_tasks,
    log_task_run,
    parse_channel_prefix,
    update_task_after_run,
)
from pykoclaw.models import ScheduledTask
from pykoclaw.scheduling import compute_next_run

log = logging.getLogger(__name__)

# Known channel prefixes used in conversation names (e.g. "wa-...", "matrix-...").
_KNOWN_CHANNEL_PREFIXES = {"wa", "acp", "matrix", "tg", "chat"}


def _has_known_prefix(conversation: str) -> bool:
    """Return True if ``conversation`` starts with a known channel prefix + dash."""
    return any(conversation.startswith(f"{p}-") for p in _KNOWN_CHANNEL_PREFIXES)


def resolve_delivery_target(task: ScheduledTask) -> tuple[str, str]:
    """Determine the delivery conversation and channel prefix for a task.

    When ``target_conversation`` is set but lacks a recognised channel prefix
    (e.g. a bare WhatsApp JID like ``120363...@g.us`` or a bare Matrix room
    like ``!abc:matrix.org``), the prefix is inherited from
    ``task.conversation``.  The conversation name is also reconstructed so
    channel plugins can route the delivery correctly.

    Returns:
        ``(conversation, channel_prefix)`` tuple ready for
        :func:`~pykoclaw.db.enqueue_delivery`.
    """
    delivery_conversation = task.target_conversation or task.conversation

    if _has_known_prefix(delivery_conversation):
        return delivery_conversation, parse_channel_prefix(delivery_conversation)

    # Bare identifier — inherit prefix from the originating conversation.
    if not _has_known_prefix(task.conversation):
        # Can't infer — fall through with the default.
        prefix = parse_channel_prefix(delivery_conversation)
        log.warning(
            "Cannot infer channel prefix for delivery target %r "
            "(origin conversation %r also has no known prefix)",
            delivery_conversation,
            task.conversation,
        )
        return delivery_conversation, prefix

    origin_prefix = parse_channel_prefix(task.conversation)

    # Check if the bare target is the tail of the originating conversation name.
    # e.g. origin="wa-tyko-120363...@g.us", target="120363...@g.us"
    #      → suffix "tyko-120363...@g.us" ends with target → reuse origin.
    origin_suffix = (
        task.conversation.split("-", 1)[1] if "-" in task.conversation else ""
    )
    if origin_suffix.endswith(delivery_conversation):
        log.info(
            "Bare target %r matched origin %r — using origin as delivery conversation",
            delivery_conversation,
            task.conversation,
        )
        return task.conversation, origin_prefix

    # Bare target doesn't match the origin's suffix — prepend the prefix.
    reconstructed = f"{origin_prefix}-{delivery_conversation}"
    log.info(
        "Bare target %r — prepending prefix %r → %r",
        delivery_conversation,
        origin_prefix,
        reconstructed,
    )
    return reconstructed, origin_prefix


async def run_task(task: ScheduledTask, db: DbConnection, data_dir: Path) -> None:
    start_time = datetime.now(timezone.utc)

    conv = get_conversation(db, task.conversation)
    resume_session_id = None
    if task.context_mode == "group" and conv and conv.session_id:
        resume_session_id = conv.session_id

    result_text = ""
    error_msg = None

    try:
        async for msg in query_agent(
            task.prompt,
            db=db,
            data_dir=data_dir,
            conversation_name=task.conversation,
            resume_session_id=resume_session_id,
        ):
            if msg.type == "text" and msg.text:
                result_text += msg.text
                print(f"[task:{task.id}] {msg.text}")

        if task.schedule_type in ("cron", "interval"):
            next_run = compute_next_run(task.schedule_type, task.schedule_value)
        else:
            next_run = None

        result_summary = result_text[:200] if result_text else "Completed"

    except Exception as e:
        error_msg = str(e)
        result_summary = f"Error: {error_msg}"
        # Preserve next_run for recurring tasks even on error
        if task.schedule_type in ("cron", "interval"):
            next_run = compute_next_run(task.schedule_type, task.schedule_value)
        else:
            next_run = None

    duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    update_task_after_run(
        db, task_id=task.id, next_run=next_run, last_result=result_summary
    )
    log_task_run(
        db,
        task_id=task.id,
        run_at=start_time.isoformat(),
        duration_ms=duration_ms,
        status="error" if error_msg else "success",
        result=result_text if result_text else None,
        error=error_msg,
    )

    if result_text and not error_msg:
        delivery_conversation, channel_prefix = resolve_delivery_target(task)
        enqueue_delivery(
            db,
            task_id=task.id,
            task_run_log_id=None,
            conversation=delivery_conversation,
            channel_prefix=channel_prefix,
            message=result_text,
        )


async def run_scheduler(db: DbConnection, data_dir: Path) -> None:
    db.execute("PRAGMA journal_mode=WAL")
    print("Scheduler started", file=sys.stderr)

    while True:
        due_tasks = get_due_tasks(db)
        for task in due_tasks:
            await run_task(task, db, data_dir)

        await asyncio.sleep(60)
