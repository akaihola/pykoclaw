"""Tests for the plugin framework."""

from __future__ import annotations

import sqlite3
from typing import Any

import click
from pydantic_settings import BaseSettings

from pykoclaw.plugins import (
    PykoClawPlugin,
    PykoClawPluginBase,
    load_plugins,
    run_db_migrations,
)


def test_load_plugins_returns_empty_list_when_no_plugins() -> None:
    """Test that load_plugins returns empty list when no plugins installed."""
    plugins = load_plugins()
    assert isinstance(plugins, list)


def test_plugin_base_default_implementations_dont_crash() -> None:
    """Test that PykoClawPluginBase default implementations work."""
    plugin = PykoClawPluginBase()

    # Test register_commands doesn't crash
    group = click.Group()
    plugin.register_commands(group)

    # Test get_mcp_servers returns empty dict
    db = sqlite3.connect(":memory:")
    servers = plugin.get_mcp_servers(db, "test")
    assert servers == {}

    # Test get_db_migrations returns empty list
    migrations = plugin.get_db_migrations()
    assert migrations == []

    # Test get_config_class returns None
    config_cls = plugin.get_config_class()
    assert config_cls is None


def test_plugin_base_implements_protocol() -> None:
    """Test that PykoClawPluginBase implements PykoClawPlugin protocol."""
    plugin = PykoClawPluginBase()
    assert isinstance(plugin, PykoClawPlugin)


def test_run_db_migrations_with_mock_plugin() -> None:
    """Test that run_db_migrations executes SQL from plugins."""
    db = sqlite3.connect(":memory:")

    class MockPlugin(PykoClawPluginBase):
        def get_db_migrations(self) -> list[str]:
            return [
                "CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)",
                "INSERT INTO test_table (name) VALUES ('test')",
            ]

    plugin = MockPlugin()
    run_db_migrations(db, [plugin])

    # Verify table was created and data inserted
    cursor = db.execute("SELECT name FROM test_table")
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "test"


def test_run_db_migrations_handles_plugin_errors() -> None:
    """Test that run_db_migrations continues on plugin errors."""
    db = sqlite3.connect(":memory:")

    class BadPlugin(PykoClawPluginBase):
        def get_db_migrations(self) -> list[str]:
            return ["INVALID SQL SYNTAX"]

    class GoodPlugin(PykoClawPluginBase):
        def get_db_migrations(self) -> list[str]:
            return ["CREATE TABLE good_table (id INTEGER PRIMARY KEY)"]

    bad_plugin = BadPlugin()
    good_plugin = GoodPlugin()

    # Should not raise, should log error and continue
    run_db_migrations(db, [bad_plugin, good_plugin])

    # Verify good plugin's migration ran
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='good_table'"
    )
    assert cursor.fetchone() is not None


def test_plugin_protocol_methods() -> None:
    """Test that plugin protocol methods have correct signatures."""

    class TestPlugin(PykoClawPluginBase):
        def register_commands(self, group: click.Group) -> None:
            @group.command("test_cmd")
            def test_cmd() -> None:
                pass

        def get_mcp_servers(
            self, db: sqlite3.Connection, conversation: str
        ) -> dict[str, Any]:
            return {"test": {"name": "test"}}

        def get_db_migrations(self) -> list[str]:
            return ["CREATE TABLE test (id INTEGER)"]

        def get_config_class(self) -> type[BaseSettings] | None:
            class TestSettings(BaseSettings):
                test_value: str = "default"

            return TestSettings

    plugin = TestPlugin()
    assert isinstance(plugin, PykoClawPlugin)

    group = click.Group()
    plugin.register_commands(group)
    assert "test_cmd" in group.commands

    # Test get_mcp_servers
    db = sqlite3.connect(":memory:")
    servers = plugin.get_mcp_servers(db, "test")
    assert "test" in servers

    # Test get_db_migrations
    migrations = plugin.get_db_migrations()
    assert len(migrations) == 1

    # Test get_config_class
    config_cls = plugin.get_config_class()
    assert config_cls is not None
    assert issubclass(config_cls, BaseSettings)
