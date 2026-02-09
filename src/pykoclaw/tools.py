import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from textwrap import dedent
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool
from croniter import croniter

from pykoclaw.db import (
    create_task,
    delete_task,
    get_tasks_for_conversation,
    update_task,
)


def make_mcp_server(db: sqlite3.Connection, conversation: str):
    @tool(
        "schedule_task",
        dedent("""\
        Schedule a new task to run at specified times.
        Supports cron expressions, intervals (milliseconds), or one-time execution."""),
        {
            "prompt": str,
            "schedule_type": str,
            "schedule_value": str,
            "context_mode": str,
        },
    )
    async def schedule_task(args: dict[str, Any]) -> dict[str, Any]:
        task_id = uuid.uuid4().hex[:8]
        schedule_type = args["schedule_type"]
        schedule_value = args["schedule_value"]
        now = datetime.now(timezone.utc)

        if schedule_type == "cron":
            cron = croniter(schedule_value, now)
            next_run = cron.get_next(datetime).isoformat()
        elif schedule_type == "interval":
            next_run = (now + timedelta(milliseconds=int(schedule_value))).isoformat()
        else:
            next_run = schedule_value

        create_task(
            db,
            id=task_id,
            conversation=conversation,
            prompt=args["prompt"],
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            next_run=next_run,
            context_mode=args.get("context_mode", "group"),
        )

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Task {task_id} scheduled. Next run: {next_run}",
                }
            ]
        }

    @tool(
        "list_tasks",
        "List all tasks for the current conversation.",
        {},
    )
    async def list_tasks(args: dict[str, Any]) -> dict[str, Any]:
        tasks = get_tasks_for_conversation(db, conversation)
        if not tasks:
            return {"content": [{"type": "text", "text": "No tasks scheduled."}]}

        lines = ["Tasks:"]
        for task in tasks:
            lines.append(
                f"  {task['id']}: {task['prompt'][:50]} ({task['status']}, next: {task['next_run']})"
            )

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "pause_task",
        "Pause a scheduled task.",
        {"task_id": str},
    )
    async def pause_task(args: dict[str, Any]) -> dict[str, Any]:
        update_task(db, args["task_id"], status="paused")
        return {
            "content": [{"type": "text", "text": f"Task {args['task_id']} paused."}]
        }

    @tool(
        "resume_task",
        "Resume a paused task.",
        {"task_id": str},
    )
    async def resume_task(args: dict[str, Any]) -> dict[str, Any]:
        task_id = args["task_id"]
        task = db.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()

        if not task:
            return {"content": [{"type": "text", "text": f"Task {task_id} not found."}]}

        now = datetime.now(timezone.utc)
        schedule_type = task["schedule_type"]
        schedule_value = task["schedule_value"]

        if schedule_type == "cron":
            cron = croniter(schedule_value, now)
            next_run = cron.get_next(datetime).isoformat()
        elif schedule_type == "interval":
            next_run = (now + timedelta(milliseconds=int(schedule_value))).isoformat()
        else:
            next_run = schedule_value

        update_task(db, task_id, status="active", next_run=next_run)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Task {task_id} resumed. Next run: {next_run}",
                }
            ]
        }

    @tool(
        "cancel_task",
        "Cancel and delete a scheduled task.",
        {"task_id": str},
    )
    async def cancel_task(args: dict[str, Any]) -> dict[str, Any]:
        delete_task(db, args["task_id"])
        return {
            "content": [{"type": "text", "text": f"Task {args['task_id']} cancelled."}]
        }

    return create_sdk_mcp_server(
        name="pykoclaw",
        tools=[schedule_task, list_tasks, pause_task, resume_task, cancel_task],
    )
