"""Plugin framework: Protocol-based plugin system with entry point discovery."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

import click
from pydantic_settings import BaseSettings

from pykoclaw.db import DbConnection

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TransformContext:
    """Channel-specific response transform context."""

    channel_prefix: str
    native_file_extensions: frozenset[str]

    def supports_extension(self, suffix: str) -> bool:
        return suffix.lower() in self.native_file_extensions


@runtime_checkable
class PykoClawPlugin(Protocol):
    """Protocol that all pykoclaw plugins must satisfy."""

    def register_commands(self, group: click.Group) -> None: ...

    def get_mcp_servers(
        self, db: DbConnection, conversation: str
    ) -> dict[str, Any]: ...

    def get_db_migrations(self) -> list[str]: ...

    def get_config_class(self) -> type[BaseSettings] | None: ...

    def native_file_extensions(self) -> frozenset[str]:
        """Return file suffixes the channel can deliver natively from disk."""
        ...

    def transform_response(self, text: str, ctx: TransformContext) -> str:
        """Post-process agent response text before channel formatting."""
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

    def native_file_extensions(self) -> frozenset[str]:
        return frozenset()

    def transform_response(self, text: str, ctx: TransformContext) -> str:
        return text


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


def compose_transformers(
    plugins: list[PykoClawPlugin], ctx: TransformContext
) -> Callable[[str], str]:
    """Compose plugin response transformers in plugin registration order."""

    if not plugins:
        return lambda text: text

    def transform(text: str) -> str:
        for plugin in plugins:
            text = plugin.transform_response(text, ctx)
        return text

    return transform


def run_db_migrations(db: DbConnection, plugins: list[PykoClawPlugin]) -> None:
    for plugin in plugins:
        for sql in plugin.get_db_migrations():
            try:
                db.executescript(sql)
            except Exception:
                log.exception("Failed to run migration from %s", type(plugin).__name__)
