import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from textwrap import dedent
from typing import Any

# Keywords that suggest the agent is instructed to actively send a message to
# a channel itself (required for ack_only tasks).
_SEND_KEYWORDS = frozenset(
    ["send", "post", "deliver", "dispatch", "message", "notify", "write to"]
)

_OUTPUT_CONTRACT_DELIVER_FINAL = dedent("""\

    ---

    Output contract — mandatory:
    - Work silently. No narration. No "Now I will...", "Let me...", "Done."
    - Your final reply must be ONLY the ready-to-send summary/report.
    - The scheduler will deliver your final reply to the configured destination.
    - Do NOT send any separate message yourself.
    - If there is nothing to report, reply with a single concise "No updates" line.
""")

_OUTPUT_CONTRACT_ACK_ONLY = dedent("""\

    ---

    Output contract — mandatory:
    - Work silently. No narration. No "Now I will...", "Let me...", "Done."
    - The summary message sent to the target channel must contain only the report content.
    - Your final reply must be ONLY a brief acknowledgement for the default destination.
    - Do NOT repeat the full summary in the acknowledgement.
    - Example acknowledgement: "Report sent to [channel]. Key finding: [one line]. Full report: [[path]]"
""")

from claude_agent_sdk import create_sdk_mcp_server, tool

from pykoclaw.config import settings
from pykoclaw.db import (
    DbConnection,
    clear_default_task_result_conversation,
    create_task,
    delete_task,
    get_all_tasks,
    get_conversation,
    get_default_task_result_conversation,
    get_task,
    get_tasks_for_conversation,
    set_default_task_result_conversation,
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
                        "configured default destination. Use the full prefixed "
                        'conversation name (e.g. "wa-tyko-120363...@g.us", '
                        '"matrix-!room:server"). Bare identifiers without a '
                        "channel prefix will be auto-resolved using the task's "
                        "originating conversation prefix when possible."
                    ),
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["deliver_final", "ack_only"],
                    "description": (
                        '"deliver_final": scheduler delivers the task\'s final reply to '
                        "the destination channel. "
                        '"ack_only": use when the task sends its main summary explicitly '
                        "to another channel; the scheduler should deliver only the final "
                        "acknowledgement reply."
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
        requested_target = args.get("target_conversation")
        default_target = get_default_task_result_conversation(db)
        effective_target = requested_target or default_target

        if effective_target is None and not get_conversation(db, conversation):
            effective_target = conversation

        if effective_target is None:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "No default task result destination is configured for this "
                            "workspace, and this conversation is not a routable channel. "
                            "Set a default with set_task_result_destination or pass "
                            "target_conversation explicitly."
                        ),
                    }
                ],
                "isError": True,
            }

        output_mode = args.get("output_mode", "deliver_final")

        # Warn when ack_only is requested but the prompt does not mention
        # sending a message to any channel.  The task will still be created —
        # this is advisory only.
        warning = ""
        if output_mode == "ack_only":
            prompt_lower = args["prompt"].lower()
            if not any(kw in prompt_lower for kw in _SEND_KEYWORDS):
                warning = (
                    " Warning: output_mode is 'ack_only' but the prompt does not "
                    "appear to instruct the task to send a message to a target "
                    "channel directly. Consider adding explicit send instructions "
                    "or using output_mode='deliver_final' instead."
                )

        create_task(
            db,
            task_id=task_id,
            conversation=conversation,
            prompt=args["prompt"],
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            next_run=next_run,
            context_mode=args.get("context_mode", "group"),
            target_conversation=effective_target,
            output_mode=output_mode,
        )

        msg = f"Task {task_id} scheduled. Next run: {next_run}. Output mode: {output_mode}"
        if requested_target:
            msg += f" Results will be delivered to: {effective_target}"
        elif default_target:
            msg += f" Results will be delivered to the default destination: {effective_target}"
        else:
            msg += f" Results will be delivered to: {effective_target}"

        return {"content": [{"type": "text", "text": msg + warning}]}

    @tool(
        "set_task_result_destination",
        "Set the default conversation that should receive future task results in this workspace.",
        {
            "type": "object",
            "properties": {
                "target_conversation": {
                    "type": "string",
                    "description": (
                        "Full prefixed conversation name that should receive task results "
                        'by default, e.g. "matrix-!room:server" or '
                        '"wa-tyko-120363...@g.us".'
                    ),
                },
            },
            "required": ["target_conversation"],
        },
    )
    async def set_task_result_destination(args: dict[str, Any]) -> dict[str, Any]:
        target_conversation = args["target_conversation"]
        set_default_task_result_conversation(db, target_conversation)
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Default task result destination set to: {target_conversation}"
                    ),
                }
            ]
        }

    @tool(
        "clear_task_result_destination",
        "Clear the workspace default task result destination.",
        {"type": "object", "properties": {}},
    )
    async def clear_task_result_destination(args: dict[str, Any]) -> dict[str, Any]:
        del args
        clear_default_task_result_conversation(db)
        return {
            "content": [
                {"type": "text", "text": "Default task result destination cleared."}
            ]
        }

    @tool(
        "get_task_result_destination",
        "Show the workspace default task result destination, if any.",
        {"type": "object", "properties": {}},
    )
    async def get_task_result_destination(args: dict[str, Any]) -> dict[str, Any]:
        del args
        target_conversation = get_default_task_result_conversation(db)
        if target_conversation is None:
            text = "No default task result destination configured."
        else:
            text = f"Default task result destination: {target_conversation}"
        return {"content": [{"type": "text", "text": text}]}

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

    @tool(
        "session_meta",
        dedent("""\
        Return the current pykoclaw session file path, UUID, slug, and a
        reusable metadata block for plans, notes, and commit footers.
        Use this before creating commits or writing project descriptions
        that need a session identifier."""),
        {
            "type": "object",
            "properties": {},
        },
    )
    async def session_meta(args: dict[str, Any]) -> dict[str, Any]:
        conv = get_conversation(db, conversation)
        # conversation is e.g. "acp-a1b2c3d4" or "wa-tyko" or task name
        short_id = (
            conversation.rsplit("-", 1)[-1][:8]
            if "-" in conversation
            else conversation[:8]
        )
        session_file = conv.session_id if conv else None
        created_at = conv.created_at if conv else None

        # Derive slug: "{timestamp}_{shortId}" when timestamp available,
        # otherwise just the conversation name
        slug = f"{created_at}_{short_id}" if created_at else conversation

        meta = {
            # Pi-compatible field names (CLAUDE.md references these)
            "file": session_file,
            "shortId": short_id,
            "slug": slug,
            "name": conversation,
            # Pykoclaw-specific extras
            "conversation": conversation,
            "cwd": conv.cwd if conv else None,
            "created_at": created_at,
        }

        block = "\n".join(
            [
                f"Pykoclaw-Session: {conversation}",
                f"Pykoclaw-Session-Slug: {slug}",
                f"Pykoclaw-Session-File: {session_file or 'ephemeral'}",
                f"Pykoclaw-Session-Name: {conversation}",
            ]
        )

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({**meta, "block": block}, indent=2),
                }
            ]
        }

    @tool(
        "schedule_channel_report_task",
        dedent("""\
        Create a scheduled task that safely produces a report and/or sends a
        channel message without duplicate delivery or exposed thinking.

        Two delivery models are supported:

        deliver_final — the task does all work silently and its final reply
        (the report summary) is delivered by the scheduler to the configured
        destination.  Use this when a single summary goes to one destination.

        ack_only — the task does its work, sends the main summary to a target
        channel directly (e.g. WhatsApp, Slack, Telegram), and its final reply
        is only a brief acknowledgement delivered by the scheduler.  Use this
        when a task must write a workspace report, send a rich summary to one
        channel, and send a short "done" confirmation to your default channel.

        The output contract (silent work, no narration, correct final reply) is
        automatically appended to the prompt — you do not need to write it
        yourself."""),
        {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": (
                        "Describe what the task should do: what files to read/write, "
                        "what to research, what summary to prepare, and (for ack_only) "
                        "which tool to use and which channel to send the summary to."
                    ),
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["deliver_final", "ack_only"],
                    "description": (
                        '"deliver_final": scheduler delivers the final reply as the '
                        "report/summary. "
                        '"ack_only": task sends the summary itself; scheduler delivers '
                        "only the acknowledgement."
                    ),
                },
                "schedule_type": {
                    "type": "string",
                    "enum": ["cron", "interval", "once"],
                    "description": (
                        '"cron": recurring via cron expression. '
                        '"interval": recurring every N milliseconds. '
                        '"once": one-shot at an ISO 8601 timestamp.'
                    ),
                },
                "schedule_value": {
                    "type": "string",
                    "description": "Cron expression, millisecond interval, or ISO 8601 timestamp.",
                },
                "context_mode": {
                    "type": "string",
                    "enum": ["group", "isolated"],
                    "description": (
                        '"group": agent sees conversation history (default). '
                        '"isolated": fresh session each run.'
                    ),
                },
                "target_conversation": {
                    "type": "string",
                    "description": (
                        "Destination for scheduler-delivered results. "
                        "Defaults to the workspace default destination."
                    ),
                },
            },
            "required": [
                "task_description",
                "output_mode",
                "schedule_type",
                "schedule_value",
            ],
        },
    )
    async def schedule_channel_report_task(args: dict[str, Any]) -> dict[str, Any]:
        task_description = args["task_description"]
        output_mode = args["output_mode"]

        contract = (
            _OUTPUT_CONTRACT_ACK_ONLY
            if output_mode == "ack_only"
            else _OUTPUT_CONTRACT_DELIVER_FINAL
        )
        full_prompt = task_description.rstrip() + contract

        # Warn ack_only tasks that don't describe a direct send.
        warning = ""
        if output_mode == "ack_only":
            desc_lower = task_description.lower()
            if not any(kw in desc_lower for kw in _SEND_KEYWORDS):
                warning = (
                    " Warning: output_mode is 'ack_only' but the task description "
                    "does not appear to instruct the task to send a message to a "
                    "target channel directly. Add explicit send instructions to the "
                    "task description."
                )

        schedule_type = args["schedule_type"]
        schedule_value = args["schedule_value"]
        next_run = compute_next_run(schedule_type, schedule_value)

        requested_target = args.get("target_conversation")
        default_target = get_default_task_result_conversation(db)
        effective_target = requested_target or default_target

        if effective_target is None and not get_conversation(db, conversation):
            effective_target = conversation

        if effective_target is None:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "No default task result destination configured. "
                            "Set one with set_task_result_destination or pass "
                            "target_conversation explicitly."
                        ),
                    }
                ],
                "isError": True,
            }

        task_id = uuid.uuid4().hex[:8]
        create_task(
            db,
            task_id=task_id,
            conversation=conversation,
            prompt=full_prompt,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            next_run=next_run,
            context_mode=args.get("context_mode", "group"),
            target_conversation=effective_target,
            output_mode=output_mode,
        )

        msg = (
            f"Task {task_id} scheduled. Next run: {next_run}. "
            f"Output mode: {output_mode}. "
            f"Destination: {effective_target}. "
            "Output contract appended automatically."
        )
        return {"content": [{"type": "text", "text": msg + warning}]}

    tools: list[Any] = [
        schedule_task,
        schedule_channel_report_task,
        set_task_result_destination,
        get_task_result_destination,
        clear_task_result_destination,
        list_tasks,
        pause_task,
        resume_task,
        cancel_task,
        session_meta,
    ]

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
