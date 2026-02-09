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
