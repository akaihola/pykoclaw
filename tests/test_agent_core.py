"""Tests for agent_core module."""

from __future__ import annotations

from pykoclaw.agent_core import AgentMessage


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
