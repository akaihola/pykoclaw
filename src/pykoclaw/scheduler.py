import asyncio
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
        delivery_conversation = task.target_conversation or task.conversation
        enqueue_delivery(
            db,
            task_id=task.id,
            task_run_log_id=None,
            conversation=delivery_conversation,
            channel_prefix=parse_channel_prefix(delivery_conversation),
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
