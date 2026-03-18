"""Shared agent query logic used by both the interactive chat and the scheduler."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
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
logging.getLogger("claude_agent_sdk._internal.transport.subprocess_cli").setLevel(
    logging.WARNING
)

log = logging.getLogger(__name__)
_sdk_stderr_log = logging.getLogger("claude_agent_sdk.stderr")

# The sentence Anthropic requires to be present at the start of every system
# prompt when using OAuth tokens on Claude Max plans (gates Sonnet/Opus access).
_CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."

# Base system prompt prepended to every agent call, regardless of channel or
# context.  Keep rules here generic — no platform-specific wording.
_BASE_SYSTEM_PROMPT = (
    "Always format hyperlinks as [Label](URL). "
    "Never use bare URLs, fenced code blocks, or HTML anchor tags for links. "
    "Renderers and gateways automatically convert [Label](URL) to the "
    "native link format of each platform."
)


def _build_identity_prefix(agent_name: str | None) -> str:
    """Return the system-prompt identity block for this agent instance.

    The first sentence is the OAuth-required Claude Code identity string.
    When *agent_name* is configured a second sentence immediately reframes it:
    "Claude Code" is the technical runtime name; the agent's real name — the
    one users actually know — is *agent_name*.
    """
    if agent_name:
        return (
            f"{_CLAUDE_CODE_IDENTITY} "
            f'"Claude Code" is the technical runtime name of the platform; '
            f"your actual name — the one you use in all conversations — is {agent_name}."
        )
    return _CLAUDE_CODE_IDENTITY


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
    is_final: bool = False


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


def _build_agent_env() -> dict[str, str]:
    """Return the environment dict passed to the Claude Code subprocess.

    ``CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`` unconditionally disables Claude Code's
    auto-memory feature, which would otherwise silently write notes to the user's
    global ``~/.claude/projects/<project>/memory/MEMORY.md``.  When the SDK is
    used as a library the agent must not mutate the caller's Claude memory store.

    ``ENABLE_TOOL_SEARCH`` is forwarded from the host environment when present,
    as it controls an experimental tool-search feature in Claude Code.
    """
    env: dict[str, str] = {
        "SHELL": "/bin/bash",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    }
    if "ENABLE_TOOL_SEARCH" in os.environ:
        env["ENABLE_TOOL_SEARCH"] = os.environ["ENABLE_TOOL_SEARCH"]
    return env


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
    include_partial_messages: bool = True,
) -> AsyncGenerator[AgentMessage, None]:
    """Send *prompt* to the Claude agent and yield response messages."""
    conv_dir = data_dir / "conversations" / conversation_name
    conv_dir.mkdir(parents=True, exist_ok=True)

    mcp_servers: dict[str, Any] = {
        "pykoclaw": make_mcp_server(db, conversation_name),
    }

    # Load plugins and collect their MCP servers.
    # Failures in individual plugins (e.g. missing system libs) must not
    # prevent other plugins or the agent from running.
    plugins = load_plugins()
    for plugin in plugins:
        try:
            plugin_servers = plugin.get_mcp_servers(db, conversation_name)
            mcp_servers.update(plugin_servers)
        except Exception:
            log.exception("Failed to load MCP servers from %s", type(plugin).__name__)

    if extra_mcp_servers:
        mcp_servers.update(extra_mcp_servers)

    def _on_stderr(line: str) -> None:
        _sdk_stderr_log.debug("[%s] %s", conversation_name, line)

    # Build the full preamble: identity first (OAuth-required + name framing),
    # then formatting rules, then any caller-supplied context.
    identity_prefix = _build_identity_prefix(settings.agent_name)
    base_preamble = f"{identity_prefix}\n\n{_BASE_SYSTEM_PROMPT}"
    effective_system_prompt = (
        f"{base_preamble}\n\n{system_prompt}" if system_prompt else base_preamble
    )

    options = ClaudeAgentOptions(
        cli_path=shutil.which("claude"),
        cwd=str(conv_dir),
        permission_mode="bypassPermissions",
        mcp_servers=mcp_servers,
        model=model or settings.model,
        allowed_tools=list(_DEFAULT_ALLOWED_TOOLS),
        setting_sources=["project", "user"],
        system_prompt=effective_system_prompt,
        resume=resume_session_id,
        env=_build_agent_env(),
        stderr=_on_stderr,
        include_partial_messages=include_partial_messages,
    )

    async with ClaudeSDKClient(options) as client:
        await client.query(prompt)

        collected: list[AgentMessage] = []

        async def _on_text(text: str) -> None:
            collected.append(AgentMessage(type="text", text=text))

        sp_hash = prompt_hash(effective_system_prompt)

        async def _on_result(msg: ResultMessage) -> None:
            upsert_conversation(
                db,
                conversation_name,
                msg.session_id,
                str(conv_dir),
                system_prompt_hash=sp_hash,
            )
            if msg.result:
                collected.append(
                    AgentMessage(type="text", text=msg.result, is_final=True)
                )
            collected.append(
                AgentMessage(type="result", session_id=msg.session_id, text=msg.result)
            )

        await consume_sdk_response(client, on_text=_on_text, on_result=_on_result)

        for msg in collected:
            yield msg
