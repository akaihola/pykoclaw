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
    compose_system_prompt_additions,
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


def test_run_db_migrations_ignores_duplicate_column_errors(caplog) -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, body TEXT)")

    class DuplicateColumnPlugin(PykoClawPluginBase):
        def get_db_migrations(self) -> list[str]:
            return [
                "ALTER TABLE test_table ADD COLUMN body TEXT",
                "ALTER TABLE test_table ADD COLUMN attachment_path TEXT",
            ]

    class GoodPlugin(PykoClawPluginBase):
        def get_db_migrations(self) -> list[str]:
            return ["CREATE TABLE good_table (id INTEGER PRIMARY KEY)"]

    with caplog.at_level("INFO"):
        run_db_migrations(db, [DuplicateColumnPlugin(), GoodPlugin()])

    cursor = db.execute("PRAGMA table_info(test_table)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "body" in columns
    assert "attachment_path" in columns
    assert "Skipping already-applied migration from DuplicateColumnPlugin" in caplog.text

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


def test_get_system_prompt_addition_base_returns_none() -> None:
    """PykoClawPluginBase default returns None — no addition."""
    plugin = PykoClawPluginBase()
    assert plugin.get_system_prompt_addition() is None


def test_get_system_prompt_addition_custom_plugin() -> None:
    """A plugin can return a non-empty string addition."""

    class GreetPlugin(PykoClawPluginBase):
        def get_system_prompt_addition(self) -> str | None:
            return "Always greet users warmly."

    assert GreetPlugin().get_system_prompt_addition() == "Always greet users warmly."


def test_compose_system_prompt_additions_no_plugins() -> None:
    assert compose_system_prompt_additions([]) is None


def test_compose_system_prompt_additions_all_none() -> None:
    """All plugins returning None → result is None."""
    plugins: list[PykoClawPlugin] = [PykoClawPluginBase(), PykoClawPluginBase()]
    assert compose_system_prompt_additions(plugins) is None


def test_compose_system_prompt_additions_single_plugin() -> None:
    class AddPlugin(PykoClawPluginBase):
        def get_system_prompt_addition(self) -> str | None:
            return "Use full paths."

    result = compose_system_prompt_additions([AddPlugin()])
    assert result == "Use full paths."


def test_compose_system_prompt_additions_multiple_plugins() -> None:
    """Multiple plugins with additions are joined by a blank line."""

    class PluginA(PykoClawPluginBase):
        def get_system_prompt_addition(self) -> str | None:
            return "Instruction A."

    class PluginB(PykoClawPluginBase):
        def get_system_prompt_addition(self) -> str | None:
            return None  # silent — skipped

    class PluginC(PykoClawPluginBase):
        def get_system_prompt_addition(self) -> str | None:
            return "Instruction C."

    result = compose_system_prompt_additions([PluginA(), PluginB(), PluginC()])
    assert result == "Instruction A.\n\nInstruction C."


def test_compose_system_prompt_additions_empty_string_skipped() -> None:
    """Plugins returning an empty string are treated as silent."""

    class EmptyPlugin(PykoClawPluginBase):
        def get_system_prompt_addition(self) -> str | None:
            return ""

    assert compose_system_prompt_additions([EmptyPlugin()]) is None


def test_plugin_base_default_includes_system_prompt_addition() -> None:
    """Verifies the full set of default method values including the new one."""
    plugin = PykoClawPluginBase()
    assert plugin.get_system_prompt_addition() is None


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
