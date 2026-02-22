"""Shared agent query logic used by both the interactive chat and the scheduler."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
)

from pykoclaw.config import settings
from pykoclaw.db import DbConnection, upsert_conversation
from pykoclaw.plugins import load_plugins
from pykoclaw.sdk_consume import consume_sdk_response
from pykoclaw.tools import make_mcp_server

# Suppress the chatty "Using bundled Claude Code CLI: ..." INFO line that
# fires on every subprocess spawn — it adds no diagnostic value at INFO level.
import logging as _logging

_logging.getLogger("claude_agent_sdk._internal.transport.subprocess_cli").setLevel(
    _logging.WARNING
)


def prompt_hash(system_prompt: str | None) -> str | None:
    """Return a short hash of the system prompt, or None if absent."""
    if not system_prompt:
        return None
    return hashlib.sha256(system_prompt.encode()).hexdigest()[:16]


@dataclass
class AgentMessage:
    """A simplified message yielded by :func:`query_agent`."""

    type: Literal["text", "result"]
    text: str | None = None
    session_id: str | None = None


_DEFAULT_ALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "mcp__*",  # Allow all MCP servers (built-in and plugin-provided)
]


async def query_agent(
    prompt: str,
    *,
    db: DbConnection,
    data_dir: Path,
    conversation_name: str,
    system_prompt: str | None = None,
    resume_session_id: str | None = None,
    extra_mcp_servers: dict[str, Any] | None = None,
    model: str | None = None,
) -> AsyncGenerator[AgentMessage, None]:
    """Send *prompt* to the Claude agent and yield response messages."""
    conv_dir = data_dir / "conversations" / conversation_name
    conv_dir.mkdir(parents=True, exist_ok=True)

    mcp_servers: dict[str, Any] = {
        "pykoclaw": make_mcp_server(db, conversation_name),
    }

    # Load plugins and collect their MCP servers
    plugins = load_plugins()
    for plugin in plugins:
        plugin_servers = plugin.get_mcp_servers(db, conversation_name)
        mcp_servers.update(plugin_servers)

    if extra_mcp_servers:
        mcp_servers.update(extra_mcp_servers)

    options = ClaudeAgentOptions(
        cwd=str(conv_dir),
        permission_mode="bypassPermissions",
        mcp_servers=mcp_servers,
        model=model or settings.model,
        allowed_tools=list(_DEFAULT_ALLOWED_TOOLS),
        setting_sources=["project", "user"],
        system_prompt=system_prompt,
        resume=resume_session_id,
        env={"SHELL": "/bin/bash"},
    )

    async with ClaudeSDKClient(options) as client:
        await client.query(prompt)

        collected: list[AgentMessage] = []

        async def _on_text(text: str) -> None:
            collected.append(AgentMessage(type="text", text=text))

        sp_hash = prompt_hash(system_prompt)

        async def _on_result(msg: ResultMessage) -> None:
            upsert_conversation(
                db,
                conversation_name,
                msg.session_id,
                str(conv_dir),
                system_prompt_hash=sp_hash,
            )
            collected.append(
                AgentMessage(type="result", session_id=msg.session_id, text=msg.result)
            )

        await consume_sdk_response(client, on_text=_on_text, on_result=_on_result)

        for msg in collected:
            yield msg
