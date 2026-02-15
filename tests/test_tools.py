import asyncio
import sqlite3
from pathlib import Path

import pytest

from pykoclaw.db import init_db, upsert_conversation
from pykoclaw.tools import make_mcp_server


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


def test_make_mcp_server_returns_config(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "test")
    assert isinstance(server, dict)
    assert server["name"] == "pykoclaw"


def test_mcp_server_has_tools(db: sqlite3.Connection) -> None:
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "test")
    assert "instance" in server
    instance = server["instance"]
    from mcp.types import ListToolsRequest

    assert ListToolsRequest in instance.request_handlers


def test_schedule_task_schema_optional(db: sqlite3.Connection) -> None:
    """Test that schedule_task has optional target_conversation and context_mode."""
    from mcp.types import ListToolsRequest

    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    server = make_mcp_server(db, "test")
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
