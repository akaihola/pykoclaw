import uuid
from textwrap import dedent
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from pykoclaw.db import (
    DbConnection,
    create_task,
    delete_task,
    get_all_tasks,
    get_task,
    get_tasks_for_conversation,
    update_task,
)
from pykoclaw.scheduling import compute_next_run


def make_mcp_server(db: DbConnection, conversation: str):
    @tool(
        "schedule_task",
        dedent("""\
        Schedule a new task to run at specified times.
        Supports cron expressions, intervals (milliseconds), or one-time execution.
        Results are delivered back to the originating channel by default.
        Set target_conversation to deliver results to a different channel instead \
        (e.g. "wa-123@s.whatsapp.net" to target a WhatsApp chat)."""),
        {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The task prompt — what the agent should do when the task fires.",
                },
                "schedule_type": {
                    "type": "string",
                    "enum": ["cron", "interval", "once"],
                    "description": (
                        '"cron": recurring via cron expression (e.g. "0 9 * * *"). '
                        '"interval": recurring every N milliseconds (e.g. "3600000"). '
                        '"once": one-shot at an ISO 8601 timestamp (e.g. "2025-03-01T12:00:00Z").'
                    ),
                },
                "schedule_value": {
                    "type": "string",
                    "description": (
                        "Interpreted based on schedule_type — "
                        "a cron expression, milliseconds, or ISO 8601 timestamp."
                    ),
                },
                "context_mode": {
                    "type": "string",
                    "enum": ["group", "isolated"],
                    "description": (
                        '"group": agent sees the conversation history (default). '
                        '"isolated": agent starts with a blank session each run.'
                    ),
                },
                "target_conversation": {
                    "type": "string",
                    "description": (
                        "Deliver results to a different conversation instead of the "
                        'originating one (e.g. "wa-123@s.whatsapp.net").'
                    ),
                },
            },
            "required": ["prompt", "schedule_type", "schedule_value"],
        },
    )
    async def schedule_task(args: dict[str, Any]) -> dict[str, Any]:
        task_id = uuid.uuid4().hex[:8]
        schedule_type = args["schedule_type"]
        schedule_value = args["schedule_value"]
        next_run = compute_next_run(schedule_type, schedule_value)
        target_conversation = args.get("target_conversation")

        create_task(
            db,
            task_id=task_id,
            conversation=conversation,
            prompt=args["prompt"],
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            next_run=next_run,
            context_mode=args.get("context_mode", "group"),
            target_conversation=target_conversation,
        )

        msg = f"Task {task_id} scheduled. Next run: {next_run}"
        if target_conversation:
            msg += f" Results will be delivered to: {target_conversation}"

        return {"content": [{"type": "text", "text": msg}]}

    @tool(
        "list_tasks",
        "List scheduled tasks. By default lists tasks for the current conversation only. "
        "Set all=true to list tasks across all conversations.",
        {
            "type": "object",
            "properties": {
                "all": {
                    "type": "boolean",
                    "description": (
                        "If true, list tasks from all conversations, "
                        "not just the current one."
                    ),
                },
            },
        },
    )
    async def list_tasks(args: dict[str, Any]) -> dict[str, Any]:
        show_all = args.get("all", False)
        if show_all:
            tasks = get_all_tasks(db)
        else:
            tasks = get_tasks_for_conversation(db, conversation)

        if not tasks:
            scope = "anywhere" if show_all else "for this conversation"
            return {
                "content": [
                    {"type": "text", "text": f"No tasks scheduled {scope}."}
                ]
            }

        lines = ["Tasks:"]
        for task in tasks:
            prefix = f"  {task.id}: "
            if show_all:
                prefix += f"[{task.conversation}] "
            lines.append(
                f"{prefix}{task.prompt[:50]} ({task.status}, next: {task.next_run})"
            )

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "pause_task",
        "Pause a scheduled task.",
        {"task_id": str},
    )
    async def pause_task(args: dict[str, Any]) -> dict[str, Any]:
        update_task(db, task_id=args["task_id"], status="paused")
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
        task = get_task(db, task_id=task_id)

        if not task:
            return {"content": [{"type": "text", "text": f"Task {task_id} not found."}]}

        next_run = compute_next_run(task.schedule_type, task.schedule_value)
        update_task(db, task_id=task_id, status="active", next_run=next_run)
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
        delete_task(db, task_id=args["task_id"])
        return {
            "content": [{"type": "text", "text": f"Task {args['task_id']} cancelled."}]
        }

    return create_sdk_mcp_server(
        name="pykoclaw",
        tools=[schedule_task, list_tasks, pause_task, resume_task, cancel_task],
    )
