import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)
from croniter import croniter

from pykoclaw.db import (
    get_conversation,
    get_due_tasks,
    log_task_run,
    update_task_after_run,
)
from pykoclaw.tools import make_mcp_server


async def run_task(task: dict, db: sqlite3.Connection, data_dir: Path) -> None:
    start_time = datetime.now(timezone.utc)
    task_id = task["id"]
    conversation_name = task["conversation"]
    prompt = task["prompt"]
    schedule_type = task["schedule_type"]
    schedule_value = task["schedule_value"]
    context_mode = task["context_mode"]

    conv_dir = data_dir / "conversations" / conversation_name
    conv_dir.mkdir(parents=True, exist_ok=True)

    conv = get_conversation(db, conversation_name)
    session_id = None
    if context_mode == "group" and conv and conv["session_id"]:
        session_id = conv["session_id"]

    result_text = ""
    error_msg = None

    try:
        options = ClaudeAgentOptions(
            cwd=str(conv_dir),
            permission_mode="bypassPermissions",
            mcp_servers=[make_mcp_server(db, conversation_name)],
            model=os.environ.get("PYKOCLAW_MODEL", "claude-opus-4-6"),
            allowed_tools=[
                "bash",
                "read",
                "write",
                "edit",
                "glob",
                "grep",
                "web_search",
                "web_fetch",
                "mcp__pykoclaw__*",
            ],
            setting_sources=["project"],
            resume=session_id,
        )

        client = ClaudeSDKClient(options)
        client.query(prompt)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_text += block.text
                        print(f"[task:{task_id}] {block.text}")

        now = datetime.now(timezone.utc)
        if schedule_type == "cron":
            cron = croniter(schedule_value, now)
            next_run = cron.get_next(datetime).isoformat()
        elif schedule_type == "interval":
            next_run = (now + timedelta(milliseconds=int(schedule_value))).isoformat()
        else:
            next_run = None

        result_summary = result_text[:200] if result_text else "Completed"

    except Exception as e:
        error_msg = str(e)
        result_summary = f"Error: {error_msg}"
        next_run = None

    duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

    update_task_after_run(db, task_id, next_run, result_summary)
    log_task_run(
        db,
        task_id=task_id,
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
