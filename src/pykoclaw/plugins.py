"""Plugin framework: Protocol-based plugin system with entry point discovery."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

import click
from pydantic_settings import BaseSettings

from pykoclaw.db import DbConnection

log = logging.getLogger(__name__)


@runtime_checkable
class PykoClawPlugin(Protocol):
    """Protocol that all pykoclaw plugins must satisfy."""

    def register_commands(self, group: click.Group) -> None:
        """Register CLI commands with the Click group."""
        ...

    def get_mcp_servers(self, db: DbConnection, conversation: str) -> dict[str, Any]:
        """Return MCP server definitions for this plugin."""
        ...

    def get_db_migrations(self) -> list[str]:
        """Return SQL statements for database migrations."""
        ...

    def get_config_class(self) -> type[BaseSettings] | None:
        """Return a Pydantic Settings class for plugin configuration."""
        ...


class PykoClawPluginBase:
    """Base class with default no-op implementations for all plugin methods."""

    def register_commands(self, group: click.Group) -> None:
        pass

    def get_mcp_servers(self, db: DbConnection, conversation: str) -> dict[str, Any]:
        return {}

    def get_db_migrations(self) -> list[str]:
        return []

    def get_config_class(self) -> type[BaseSettings] | None:
        return None


def load_plugins() -> list[PykoClawPlugin]:
    plugins: list[PykoClawPlugin] = []
    for ep in entry_points(group="pykoclaw.plugins"):
        try:
            plugin_cls = ep.load()
            plugin = plugin_cls()
            plugins.append(plugin)
            log.debug("Loaded plugin %r from %s", ep.name, ep.value)
        except Exception:
            log.exception("Failed to load plugin %r", ep.name)
    return plugins


def run_db_migrations(db: DbConnection, plugins: list[PykoClawPlugin]) -> None:
    for plugin in plugins:
        for sql in plugin.get_db_migrations():
            try:
                db.executescript(sql)
            except Exception:
                log.exception("Failed to run migration from %s", type(plugin).__name__)
