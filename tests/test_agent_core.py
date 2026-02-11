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
