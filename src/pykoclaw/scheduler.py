import asyncio
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)

from pykoclaw.config import settings
from pykoclaw.db import (
    get_conversation,
    get_due_tasks,
    log_task_run,
    update_task_after_run,
)
from pykoclaw.models import ScheduledTask
from pykoclaw.scheduling import compute_next_run
from pykoclaw.tools import make_mcp_server


async def run_task(task: ScheduledTask, db: sqlite3.Connection, data_dir: Path) -> None:
    start_time = datetime.now(timezone.utc)

    conv_dir = data_dir / "conversations" / task.conversation
    conv_dir.mkdir(parents=True, exist_ok=True)

    conv = get_conversation(db, task.conversation)
    session_id = None
    if task.context_mode == "group" and conv and conv.session_id:
        session_id = conv.session_id

    result_text = ""
    error_msg = None

    try:
        options = ClaudeAgentOptions(
            cwd=str(conv_dir),
            permission_mode="bypassPermissions",
            mcp_servers={"pykoclaw": make_mcp_server(db, task.conversation)},
            model=settings.model,
            allowed_tools=[
                "Bash",
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                "WebSearch",
                "WebFetch",
                "mcp__pykoclaw__*",
            ],
            setting_sources=["project"],
            resume=session_id,
        )

        async with ClaudeSDKClient(options) as client:
            await client.query(task.prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            result_text += block.text
                            print(f"[task:{task.id}] {block.text}")

        if task.schedule_type in ("cron", "interval"):
            next_run = compute_next_run(task.schedule_type, task.schedule_value)
        else:
            next_run = None

        result_summary = result_text[:200] if result_text else "Completed"

    except Exception as e:
        error_msg = str(e)
        result_summary = f"Error: {error_msg}"
        next_run = None

    duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    update_task_after_run(db, task.id, next_run, result_summary)
    log_task_run(
        db,
        task_id=task.id,
        run_at=start_time.isoformat(),
        duration_ms=duration_ms,
        status="error" if error_msg else "success",
        result=result_text if result_text else None,
        error=error_msg,
    )


async def run_scheduler(db: sqlite3.Connection, data_dir: Path) -> None:
    print("Scheduler started", file=sys.stderr)

    while True:
        due_tasks = get_due_tasks(db)
        for task in due_tasks:
            await run_task(task, db, data_dir)

        await asyncio.sleep(60)
