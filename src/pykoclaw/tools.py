import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from textwrap import dedent
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from pykoclaw.config import settings
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
                        "originating one. Use the full prefixed conversation name "
                        '(e.g. "wa-tyko-120363...@g.us", '
                        '"matrix-!room:server"). '
                        "Bare identifiers without a channel prefix will be "
                        "auto-resolved using the originating conversation's prefix."
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
                "content": [{"type": "text", "text": f"No tasks scheduled {scope}."}]
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

    tools: list[Any] = [schedule_task, list_tasks, pause_task, resume_task, cancel_task]

    if api_key := settings.brave_api_key:  # type: ignore[attr-defined]

        @tool(
            "brave_search",
            dedent("""\
            Search the web using Brave Search. Use this instead of WebSearch
            (which is US-only and returns empty results outside the US).
            Returns titles, URLs, and descriptions for matching pages."""),
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string.",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of results to return (1–20, default 10).",
                    },
                    "freshness": {
                        "type": "string",
                        "enum": ["pd", "pw", "pm", "py"],
                        "description": (
                            "Limit results by age: "
                            "pd=past day, pw=past week, "
                            "pm=past month, py=past year."
                        ),
                    },
                },
                "required": ["query"],
            },
        )
        async def brave_search(args: dict[str, Any]) -> dict[str, Any]:
            query = args["query"]
            count = min(int(args.get("count", 10)), 20)
            params: dict[str, str | int] = {"q": query, "count": count}
            if freshness := args.get("freshness"):
                params["freshness"] = freshness

            url = (
                "https://api.search.brave.com/res/v1/web/search?"
                + urllib.parse.urlencode(params)
            )
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Brave Search error: HTTP {e.code} {e.reason}",
                        }
                    ]
                }
            except Exception as e:
                return {
                    "content": [{"type": "text", "text": f"Brave Search error: {e}"}]
                }

            results = data.get("web", {}).get("results", [])
            if not results:
                return {
                    "content": [
                        {"type": "text", "text": f"No results found for: {query}"}
                    ]
                }

            lines = []
            for r in results:
                title = r.get("title", "")
                result_url = r.get("url", "")
                snippet = r.get("description", "")
                lines.append(f"**{title}**\n{result_url}\n{snippet}")

            return {"content": [{"type": "text", "text": "\n\n".join(lines)}]}

        tools.append(brave_search)

    return create_sdk_mcp_server(
        name="pykoclaw",
        tools=tools,
    )
