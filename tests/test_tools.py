import asyncio
import json
import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pykoclaw.db import (
    create_task,
    get_default_task_result_conversation,
    get_task,
    init_db,
    upsert_conversation,
)
from pykoclaw.tools import make_mcp_server


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


def test_make_mcp_server_returns_config(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "acp-test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-test")
    assert isinstance(server, dict)
    assert server["name"] == "pykoclaw"


def test_mcp_server_has_tools(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "acp-test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-test")
    assert "instance" in server
    instance = server["instance"]
    from mcp.types import ListToolsRequest

    assert ListToolsRequest in instance.request_handlers


def test_schedule_task_schema_optional(db: sqlite3.Connection) -> None:
    """Test that schedule_task has optional target_conversation and context_mode."""
    from mcp.types import ListToolsRequest

    upsert_conversation(db, "acp-test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-test")
    instance = server["instance"]

    handler = instance.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest()))
    tools_list = result.root.tools

    schedule_task_tool = None
    for tool in tools_list:
        if tool.name == "schedule_task":
            schedule_task_tool = tool
            break

    assert schedule_task_tool is not None, "schedule_task tool not found"

    input_schema = schedule_task_tool.inputSchema

    assert "target_conversation" in input_schema["properties"]
    assert "context_mode" in input_schema["properties"]
    assert "target_conversation" not in input_schema["required"]
    assert "context_mode" not in input_schema["required"]

    assert "prompt" in input_schema["required"]
    assert "schedule_type" in input_schema["required"]
    assert "schedule_value" in input_schema["required"]

    # Enum constraints prevent Claude from inventing invalid values
    assert input_schema["properties"]["schedule_type"]["enum"] == [
        "cron",
        "interval",
        "once",
    ]
    assert input_schema["properties"]["context_mode"]["enum"] == [
        "group",
        "isolated",
    ]


def _get_tool_schema(instance, tool_name: str) -> dict:
    """Helper: extract a tool's inputSchema from an MCP server instance."""
    from mcp.types import ListToolsRequest

    handler = instance.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest()))
    for tool in result.root.tools:
        if tool.name == tool_name:
            return tool.inputSchema
    raise AssertionError(f"Tool {tool_name!r} not found")


def _call_tool(instance, name: str, arguments: dict):
    """Helper: call a tool on the MCP server and return the CallToolResult."""
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = instance.request_handlers[CallToolRequest]
    request = CallToolRequest(
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    server_result = asyncio.run(handler(request))
    return server_result.root


def test_list_tasks_schema_has_all_param(db: sqlite3.Connection) -> None:
    """list_tasks tool should expose an optional 'all' boolean parameter."""
    upsert_conversation(db, "acp-test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-test")
    schema = _get_tool_schema(server["instance"], "list_tasks")

    assert "all" in schema["properties"]
    assert schema["properties"]["all"]["type"] == "boolean"
    # 'all' should be optional (not in required, or no required key at all)
    assert "all" not in schema.get("required", [])


def test_list_tasks_default_shows_current_conversation(db: sqlite3.Connection) -> None:
    """Without all=true, list_tasks only shows tasks for the current conversation."""
    upsert_conversation(db, "acp-conv-a", "sess-1", "/tmp/a")
    upsert_conversation(db, "acp-conv-b", "sess-2", "/tmp/b")

    create_task(
        db,
        task_id="task-a",
        conversation="acp-conv-a",
        prompt="Task in conv-a",
        schedule_type="cron",
        schedule_value="0 9 * * *",
        next_run="2026-03-01T09:00:00Z",
    )
    create_task(
        db,
        task_id="task-b",
        conversation="acp-conv-b",
        prompt="Task in conv-b",
        schedule_type="cron",
        schedule_value="0 10 * * *",
        next_run="2026-03-01T10:00:00Z",
    )

    server = make_mcp_server(db, "acp-conv-a")
    result = _call_tool(server["instance"], "list_tasks", {})

    text = result.content[0].text
    assert "task-a" in text
    assert "task-b" not in text


def test_list_tasks_all_shows_all_conversations(db: sqlite3.Connection) -> None:
    """With all=true, list_tasks shows tasks from all conversations."""
    upsert_conversation(db, "acp-conv-a", "sess-1", "/tmp/a")
    upsert_conversation(db, "acp-conv-b", "sess-2", "/tmp/b")

    create_task(
        db,
        task_id="task-a",
        conversation="acp-conv-a",
        prompt="Task in conv-a",
        schedule_type="cron",
        schedule_value="0 9 * * *",
        next_run="2026-03-01T09:00:00Z",
    )
    create_task(
        db,
        task_id="task-b",
        conversation="acp-conv-b",
        prompt="Task in conv-b",
        schedule_type="cron",
        schedule_value="0 10 * * *",
        next_run="2026-03-01T10:00:00Z",
    )

    server = make_mcp_server(db, "acp-conv-a")
    result = _call_tool(server["instance"], "list_tasks", {"all": True})

    text = result.content[0].text
    assert "task-a" in text
    assert "task-b" in text
    # Conversation labels should appear when showing all
    assert "acp-conv-a" in text
    assert "acp-conv-b" in text


def test_list_tasks_empty_with_all(db: sqlite3.Connection) -> None:
    """With all=true and no tasks anywhere, shows appropriate message."""
    upsert_conversation(db, "acp-test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-test")
    result = _call_tool(server["instance"], "list_tasks", {"all": True})

    text = result.content[0].text
    assert "anywhere" in text


def test_list_tasks_empty_default(db: sqlite3.Connection) -> None:
    """Without all=true and no tasks, shows conversation-scoped message."""
    upsert_conversation(db, "acp-test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-test")
    result = _call_tool(server["instance"], "list_tasks", {})

    text = result.content[0].text
    assert "this conversation" in text


def test_schedule_task_internal_context_requires_default_or_explicit_target(
    db: sqlite3.Connection,
) -> None:
    upsert_conversation(db, "scheduler-calendar-antti", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "scheduler-calendar-antti")

    result = _call_tool(
        server["instance"],
        "schedule_task",
        {
            "prompt": "test",
            "schedule_type": "once",
            "schedule_value": "2026-03-12T00:00:00Z",
        },
    )

    assert result.isError is False
    assert "set_task_result_destination" in result.content[0].text


def test_set_and_get_task_result_destination(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "acp-control", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-control")

    set_result = _call_tool(
        server["instance"],
        "set_task_result_destination",
        {"target_conversation": "matrix-!room:server"},
    )
    assert "matrix-!room:server" in set_result.content[0].text
    assert get_default_task_result_conversation(db) == "matrix-!room:server"

    get_result = _call_tool(server["instance"], "get_task_result_destination", {})
    assert "matrix-!room:server" in get_result.content[0].text


def test_schedule_task_uses_workspace_default_destination(
    db: sqlite3.Connection,
) -> None:
    upsert_conversation(db, "acp-ephemeral", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-ephemeral")

    _call_tool(
        server["instance"],
        "set_task_result_destination",
        {"target_conversation": "matrix-!room:server"},
    )

    result = _call_tool(
        server["instance"],
        "schedule_task",
        {
            "prompt": "test",
            "schedule_type": "once",
            "schedule_value": "2026-03-12T00:00:00Z",
        },
    )

    text = result.content[0].text
    assert "default destination: matrix-!room:server" in text

    task_id = text.split()[1]
    task = get_task(db, task_id=task_id)
    assert task is not None
    assert task.conversation == "acp-ephemeral"
    assert task.target_conversation == "matrix-!room:server"


def test_schedule_task_explicit_target_overrides_workspace_default(
    db: sqlite3.Connection,
) -> None:
    upsert_conversation(db, "maintenance", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "maintenance")

    _call_tool(
        server["instance"],
        "set_task_result_destination",
        {"target_conversation": "matrix-!room:server"},
    )

    result = _call_tool(
        server["instance"],
        "schedule_task",
        {
            "prompt": "test",
            "schedule_type": "once",
            "schedule_value": "2026-03-12T00:00:00Z",
            "target_conversation": "wa-vaino-120363424040407722@g.us",
        },
    )

    assert result.isError is False
    assert "wa-vaino-120363424040407722@g.us" in result.content[0].text

    task_id = result.content[0].text.split()[1]
    task = get_task(db, task_id=task_id)
    assert task is not None
    assert task.conversation == "maintenance"
    assert task.target_conversation == "wa-vaino-120363424040407722@g.us"


def test_clear_task_result_destination(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "acp-control", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "acp-control")

    _call_tool(
        server["instance"],
        "set_task_result_destination",
        {"target_conversation": "matrix-!room:server"},
    )
    clear_result = _call_tool(server["instance"], "clear_task_result_destination", {})

    assert "cleared" in clear_result.content[0].text
    assert get_default_task_result_conversation(db) is None


# --- brave_search tests ---

_FAKE_BRAVE_RESPONSE = {
    "web": {
        "results": [
            {
                "title": "AI Coding Agents 2026",
                "url": "https://example.com/ai-coding",
                "description": "A guide to AI coding agents.",
            },
            {
                "title": "Claude Code Tutorial",
                "url": "https://example.com/claude",
                "description": "How to use Claude Code.",
            },
        ]
    }
}


def _make_urlopen_mock(response_body: bytes) -> MagicMock:
    """Return a mock suitable for patching urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    mock_cm.__exit__.return_value = False
    return mock_cm


import pykoclaw.config as _config_mod  # noqa: E402 – used in brave_search patches


def test_brave_search_absent_without_key(db: sqlite3.Connection) -> None:
    """brave_search is not registered when BRAVE_API_KEY is not configured."""
    from mcp.types import ListToolsRequest

    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    with patch.object(_config_mod.settings, "brave_api_key", None):
        server = make_mcp_server(db, "test")

    handler = server["instance"].request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest()))
    tool_names = {t.name for t in result.root.tools}

    assert "brave_search" not in tool_names


def test_brave_search_present_with_key(db: sqlite3.Connection) -> None:
    """brave_search is registered when BRAVE_API_KEY is configured."""
    from mcp.types import ListToolsRequest

    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    with patch.object(_config_mod.settings, "brave_api_key", "test-key"):
        server = make_mcp_server(db, "test")

    handler = server["instance"].request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest()))
    tool_names = {t.name for t in result.root.tools}

    assert "brave_search" in tool_names


def test_brave_search_returns_results(db: sqlite3.Connection) -> None:
    """brave_search formats and returns titles, URLs, and snippets."""
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    with patch.object(_config_mod.settings, "brave_api_key", "test-key"):
        server = make_mcp_server(db, "test")

    mock_cm = _make_urlopen_mock(json.dumps(_FAKE_BRAVE_RESPONSE).encode())
    with patch("urllib.request.urlopen", return_value=mock_cm):
        result = _call_tool(server["instance"], "brave_search", {"query": "AI coding"})

    text = result.content[0].text
    assert "AI Coding Agents 2026" in text
    assert "https://example.com/ai-coding" in text
    assert "Claude Code Tutorial" in text
    assert "https://example.com/claude" in text


def test_brave_search_no_results(db: sqlite3.Connection) -> None:
    """brave_search returns a descriptive message when no results are found."""
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    with patch.object(_config_mod.settings, "brave_api_key", "test-key"):
        server = make_mcp_server(db, "test")

    empty = json.dumps({"web": {"results": []}}).encode()
    mock_cm = _make_urlopen_mock(empty)
    with patch("urllib.request.urlopen", return_value=mock_cm):
        result = _call_tool(
            server["instance"], "brave_search", {"query": "xyzzy obscure query"}
        )

    text = result.content[0].text
    assert "No results" in text


def test_brave_search_http_error(db: sqlite3.Connection) -> None:
    """brave_search returns an error message on HTTP failures."""
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    with patch.object(_config_mod.settings, "brave_api_key", "test-key"):
        server = make_mcp_server(db, "test")

    http_err = urllib.error.HTTPError(
        url="https://api.search.brave.com/res/v1/web/search",
        code=429,
        msg="Too Many Requests",
        hdrs=MagicMock(),
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        result = _call_tool(server["instance"], "brave_search", {"query": "test"})

    text = result.content[0].text
    assert "429" in text or "Too Many Requests" in text


# --- session_meta tests ---


def test_session_meta_returns_pi_compatible_fields(db: sqlite3.Connection) -> None:
    """session_meta returns fields compatible with Pi session_meta extension."""
    upsert_conversation(db, "acp-a1b2c3d4", "sess-file-path", "/tmp/test")
    server = make_mcp_server(db, "acp-a1b2c3d4")
    result = _call_tool(server["instance"], "session_meta", {})

    meta = json.loads(result.content[0].text)

    # Pi-compatible fields that CLAUDE.md references
    assert meta["shortId"] == "a1b2c3d4"
    assert meta["file"] == "sess-file-path"
    assert meta["name"] == "acp-a1b2c3d4"
    assert "slug" in meta

    # Pykoclaw extras
    assert meta["conversation"] == "acp-a1b2c3d4"
    assert meta["cwd"] == "/tmp/test"
    assert meta["created_at"] is not None


def test_session_meta_block_uses_pi_prefix(db: sqlite3.Connection) -> None:
    """Block format uses Pykoclaw-Session- prefix."""
    upsert_conversation(db, "acp-deadbeef", "sess-123", "/tmp/test")
    server = make_mcp_server(db, "acp-deadbeef")
    result = _call_tool(server["instance"], "session_meta", {})

    meta = json.loads(result.content[0].text)
    block = meta["block"]

    assert "Pykoclaw-Session: acp-deadbeef" in block
    assert "Pykoclaw-Session-Slug:" in block
    assert "Pykoclaw-Session-File: sess-123" in block
    assert "Pykoclaw-Session-Name: acp-deadbeef" in block


def test_session_meta_no_conversation_in_db(db: sqlite3.Connection) -> None:
    """session_meta handles missing conversation gracefully (ephemeral session)."""
    server = make_mcp_server(db, "acp-ephemeral")
    result = _call_tool(server["instance"], "session_meta", {})

    meta = json.loads(result.content[0].text)

    assert meta["shortId"] == "ephemera"  # first 8 chars of "ephemeral"
    assert meta["file"] is None
    assert meta["cwd"] is None
    assert "Pykoclaw-Session-File: ephemeral" in meta["block"]


def test_session_meta_non_acp_conversation(db: sqlite3.Connection) -> None:
    """session_meta works with non-ACP conversation names (e.g. wa-tyko)."""
    upsert_conversation(db, "wa-tyko", "sess-wa", "/tmp/wa")
    server = make_mcp_server(db, "wa-tyko")
    result = _call_tool(server["instance"], "session_meta", {})

    meta = json.loads(result.content[0].text)

    assert meta["shortId"] == "tyko"  # last segment, first 8 chars
    assert meta["conversation"] == "wa-tyko"
    assert meta["file"] == "sess-wa"
