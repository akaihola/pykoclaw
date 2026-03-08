"""Tests for the plugin framework."""

from __future__ import annotations

import sqlite3
from typing import Any

import click
from pydantic_settings import BaseSettings

from pykoclaw.plugins import (
    PykoClawPlugin,
    PykoClawPluginBase,
    TransformContext,
    compose_transformers,
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

    group = click.Group()
    plugin.register_commands(group)

    db = sqlite3.connect(":memory:")
    servers = plugin.get_mcp_servers(db, "test")
    assert servers == {}

    migrations = plugin.get_db_migrations()
    assert migrations == []

    config_cls = plugin.get_config_class()
    assert config_cls is None

    assert plugin.native_file_extensions() == frozenset()
    ctx = TransformContext(channel_prefix="test", native_file_extensions=frozenset())
    assert plugin.transform_response("body", ctx) == "body"


def test_plugin_base_implements_protocol() -> None:
    plugin = PykoClawPluginBase()
    assert isinstance(plugin, PykoClawPlugin)


def test_run_db_migrations_with_mock_plugin() -> None:
    db = sqlite3.connect(":memory:")

    class MockPlugin(PykoClawPluginBase):
        def get_db_migrations(self) -> list[str]:
            return [
                "CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)",
                "INSERT INTO test_table (name) VALUES ('test')",
            ]

    plugin = MockPlugin()
    run_db_migrations(db, [plugin])

    cursor = db.execute("SELECT name FROM test_table")
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "test"


def test_run_db_migrations_handles_plugin_errors() -> None:
    db = sqlite3.connect(":memory:")

    class BadPlugin(PykoClawPluginBase):
        def get_db_migrations(self) -> list[str]:
            return ["INVALID SQL SYNTAX"]

    class GoodPlugin(PykoClawPluginBase):
        def get_db_migrations(self) -> list[str]:
            return ["CREATE TABLE good_table (id INTEGER PRIMARY KEY)"]

    run_db_migrations(db, [BadPlugin(), GoodPlugin()])

    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='good_table'"
    )
    assert cursor.fetchone() is not None


def test_compose_transformers_applies_plugins_in_order_with_context() -> None:
    class PrefixPlugin(PykoClawPluginBase):
        def transform_response(self, text: str, ctx: TransformContext) -> str:
            return f"{ctx.channel_prefix}:prefix:{text}"

    class SuffixPlugin(PykoClawPluginBase):
        def transform_response(self, text: str, ctx: TransformContext) -> str:
            marker = ",".join(sorted(ctx.native_file_extensions)) or "none"
            return f"{text}:suffix:{marker}"

    ctx = TransformContext(
        channel_prefix="wa",
        native_file_extensions=frozenset({".png", ".jpg"}),
    )
    transform = compose_transformers([PrefixPlugin(), SuffixPlugin()], ctx)
    assert transform("body") == "wa:prefix:body:suffix:.jpg,.png"


def test_plugin_protocol_methods() -> None:
    class TestPlugin(PykoClawPluginBase):
        def register_commands(self, group: click.Group) -> None:
            @group.command("test_cmd")
            def test_cmd() -> None:
                pass

        def get_mcp_servers(self, db: Any, conversation: str) -> dict[str, Any]:
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

    db = sqlite3.connect(":memory:")
    servers = plugin.get_mcp_servers(db, "test")
    assert "test" in servers

    migrations = plugin.get_db_migrations()
    assert len(migrations) == 1

    config_cls = plugin.get_config_class()
    assert config_cls is not None
    assert issubclass(config_cls, BaseSettings)
