"""Shared agent query logic used by both the interactive chat and the scheduler."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from pykoclaw.config import settings
from pykoclaw.db import upsert_conversation
from pykoclaw.tools import make_mcp_server


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
    "mcp__pykoclaw__*",
]


async def query_agent(
    prompt: str,
    *,
    db: sqlite3.Connection,
    data_dir: Path,
    conversation_name: str,
    system_prompt: str | None = None,
    resume_session_id: str | None = None,
    extra_mcp_servers: dict[str, Any] | None = None,
    model: str | None = None,
) -> AsyncIterator[AgentMessage]:
    """Send *prompt* to the Claude agent and yield response messages."""
    conv_dir = data_dir / "conversations" / conversation_name
    conv_dir.mkdir(parents=True, exist_ok=True)

    mcp_servers: dict[str, Any] = {
        "pykoclaw": make_mcp_server(db, conversation_name),
    }
    if extra_mcp_servers:
        mcp_servers.update(extra_mcp_servers)

    options = ClaudeAgentOptions(
        cwd=str(conv_dir),
        permission_mode="bypassPermissions",
        mcp_servers=mcp_servers,
        model=model or settings.model,
        allowed_tools=list(_DEFAULT_ALLOWED_TOOLS),
        setting_sources=["project"],
        system_prompt=system_prompt,
        resume=resume_session_id,
    )

    async with ClaudeSDKClient(options) as client:
        await client.query(prompt)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield AgentMessage(type="text", text=block.text)
            elif isinstance(message, ResultMessage):
                upsert_conversation(
                    db,
                    conversation_name,
                    message.session_id,
                    str(conv_dir),
                )
                yield AgentMessage(
                    type="result",
                    session_id=message.session_id,
                )
