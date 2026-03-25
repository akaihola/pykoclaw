"""Tests for agent_core module."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from pykoclaw.agent_core import AgentMessage


# ---------------------------------------------------------------------------
# Fake SDK client (same pattern as test_sdk_consume.py)
# ---------------------------------------------------------------------------


@dataclass
class _FakeClient:
    """Stub ClaudeSDKClient whose receive_response yields canned messages."""

    messages: list[Any] = field(default_factory=list)

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def query(self, prompt: str) -> None:
        pass

    async def receive_response(self):  # noqa: ANN201
        for msg in self.messages:
            yield msg


def _result_msg(
    session_id: str = "sess-1",
    result: str = "",
) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=100,
        duration_api_ms=80,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        result=result,
    )


def _assistant_msg(*texts: str) -> AssistantMessage:
    return AssistantMessage(
        content=[TextBlock(text=t) for t in texts],
        model="test",
    )


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE conversations (
            name TEXT PRIMARY KEY,
            session_id TEXT,
            cwd TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            system_prompt_hash TEXT
        );
        """
    )
    return conn


def test_agent_message_dataclass_creation() -> None:
    """Test that AgentMessage dataclass can be created."""
    msg = AgentMessage(type="text", text="hello")
    assert msg.type == "text"
    assert msg.text == "hello"
    assert msg.session_id is None


def test_agent_message_with_session_id() -> None:
    """Test AgentMessage with session_id."""
    msg = AgentMessage(type="result", session_id="sess-123")
    assert msg.type == "result"
    assert msg.text is None
    assert msg.session_id == "sess-123"


def test_query_agent_function_signature() -> None:
    """Test that query_agent function is importable and has correct signature."""
    from inspect import signature

    from pykoclaw.agent_core import query_agent

    sig = signature(query_agent)
    params = list(sig.parameters.keys())

    assert "prompt" in params
    assert "db" in params
    assert "data_dir" in params
    assert "conversation_name" in params
    assert "system_prompt" in params
    assert "resume_session_id" in params
    assert "extra_mcp_servers" in params
    assert "model" in params
    assert "include_partial_messages" in params


def test_query_agent_include_partial_messages_default() -> None:
    """include_partial_messages defaults to True (preserves streaming for chat REPL)."""
    from inspect import signature

    from pykoclaw.agent_core import query_agent

    sig = signature(query_agent)
    assert sig.parameters["include_partial_messages"].default is True


def test_build_agent_env_disables_auto_memory() -> None:
    """CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 is always set in the subprocess env.

    Claude Code's auto-memory feature silently writes notes to
    ~/.claude/projects/<project>/memory/MEMORY.md.  When the SDK is used as a
    library the agent must not mutate the user's global Claude memory store, so
    auto memory is unconditionally disabled via this env var.
    """
    from pykoclaw.agent_core import _build_agent_env

    env = _build_agent_env()
    assert env.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY") == "1"


def test_build_agent_env_preserves_shell() -> None:
    """SHELL=/bin/bash is always set so Bash tool works on all platforms."""
    from pykoclaw.agent_core import _build_agent_env

    env = _build_agent_env()
    assert env.get("SHELL") == "/bin/bash"


def test_build_agent_env_forwards_enable_tool_search(monkeypatch: object) -> None:
    """ENABLE_TOOL_SEARCH is forwarded when present in the host environment."""
    from pykoclaw.agent_core import _build_agent_env

    monkeypatch.setenv("ENABLE_TOOL_SEARCH", "1")  # type: ignore[attr-defined]
    env = _build_agent_env()
    assert env.get("ENABLE_TOOL_SEARCH") == "1"


def test_build_agent_env_no_tool_search_when_absent(monkeypatch: object) -> None:
    """ENABLE_TOOL_SEARCH is absent from env when not set in the host."""
    from pykoclaw.agent_core import _build_agent_env

    monkeypatch.delenv("ENABLE_TOOL_SEARCH", raising=False)  # type: ignore[attr-defined]
    env = _build_agent_env()
    assert "ENABLE_TOOL_SEARCH" not in env


# ---------------------------------------------------------------------------
# Regression: query_agent must not yield duplicate text when ResultMessage
# carries the same content already emitted via AssistantMessage TextBlocks.
#
# Production evidence (2026-03-24):
#   - Slack DM thread D0AK314Q5EC, DB rows 606/607/609
#   - Bot-authored rows had text body duplicated inside one stored string
#   - Root cause: agent_core._on_result unconditionally appended msg.result
#     as a type="text" AgentMessage even though the text was already collected
#     by _on_text via AssistantMessage TextBlocks.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_agent_does_not_duplicate_text_when_result_matches_text_blocks(
    tmp_path: Any,
) -> None:
    """Regression: query_agent must yield each piece of reply text exactly once.

    When the SDK emits an AssistantMessage with a TextBlock containing the reply
    AND then a ResultMessage whose .result is the same text (the normal case in
    non-streaming mode), query_agent must NOT yield that text twice.

    Before the fix, _on_result unconditionally appended msg.result as a
    type="text" AgentMessage, causing full_text to be reply + reply.
    """
    from pathlib import Path

    from pykoclaw.agent_core import query_agent

    reply = "Hello, this is the agent reply."

    fake_client = _FakeClient(
        messages=[
            _assistant_msg(reply),
            _result_msg(session_id="sess-dup", result=reply),
        ]
    )

    db = _make_db()

    with patch("pykoclaw.agent_core.ClaudeSDKClient", return_value=fake_client):
        texts: list[str] = []
        async for msg in query_agent(
            "question",
            db=db,
            data_dir=Path(tmp_path),
            conversation_name="test-dedup",
            include_partial_messages=False,
        ):
            if msg.type == "text" and msg.text:
                texts.append(msg.text)

    reply_texts = [t for t in texts if t.strip() and "---" not in t]
    assert reply_texts == [reply], (
        f"Expected reply text exactly once, got {reply_texts!r}. "
        "The _on_result callback is duplicating msg.result as a text message."
    )


# ---------------------------------------------------------------------------
# cwd-to-data-dir: query_agent must set cwd=data_dir, not a per-conversation
# subdirectory, and must not create conversations/{name}/ directories.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_agent_cwd_is_data_dir(tmp_path: Any) -> None:
    """ClaudeAgentOptions.cwd must be set to data_dir, not conversations/{name}/."""
    from pathlib import Path

    from pykoclaw.agent_core import query_agent

    fake_client = _FakeClient(
        messages=[_result_msg(session_id="sess-cwd", result="ok")]
    )
    db = _make_db()
    data_dir = Path(tmp_path) / "workspace"
    data_dir.mkdir()

    with patch("pykoclaw.agent_core.ClaudeSDKClient") as mock_cls:
        mock_cls.return_value = fake_client

        async for _ in query_agent(
            "hello",
            db=db,
            data_dir=data_dir,
            conversation_name="test-conv",
            include_partial_messages=False,
        ):
            pass

        # ClaudeSDKClient was called with a ClaudeAgentOptions as first arg
        call_args = mock_cls.call_args
        options = call_args[0][0]  # positional arg
        assert options.cwd == str(data_dir), (
            f"Expected cwd={data_dir}, got cwd={options.cwd}. "
            "query_agent should pass data_dir as cwd, not a conversations/ subdir."
        )


@pytest.mark.asyncio
async def test_query_agent_does_not_create_conversations_dir(tmp_path: Any) -> None:
    """query_agent must NOT create data_dir/conversations/{name}/."""
    from pathlib import Path

    from pykoclaw.agent_core import query_agent

    fake_client = _FakeClient(
        messages=[_result_msg(session_id="sess-nodir", result="ok")]
    )
    db = _make_db()
    data_dir = Path(tmp_path) / "workspace"
    data_dir.mkdir()

    with patch("pykoclaw.agent_core.ClaudeSDKClient", return_value=fake_client):
        async for _ in query_agent(
            "hello",
            db=db,
            data_dir=data_dir,
            conversation_name="test-conv",
            include_partial_messages=False,
        ):
            pass

    conv_dir = data_dir / "conversations" / "test-conv"
    assert not conv_dir.exists(), (
        f"Directory {conv_dir} should not be created. "
        "query_agent should not create per-conversation subdirectories."
    )
