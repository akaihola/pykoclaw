from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_path, user_data_path
from pydantic import AliasChoices, Field
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
)


def _build_env_files() -> tuple[str, ...]:
    """Build the ordered list of .env files to load, lowest priority first.

    Precedence (lowest → highest, all overridden by actual env vars):
    1. Global XDG config dir: ``user_config_path("pykoclaw") / ".env"``
    2. Per-data-dir config: ``$PYKOCLAW_DATA/.env`` (only when env var is set)
    3. CWD ``.env``

    This function is intentionally semi-public (single underscore rather than
    fully private) so that sibling packages such as ``pykoclaw-pykofinder``
    can share the exact same resolution logic without duplicating it.  If the
    number of packages that need this grows, consider promoting it to a proper
    public utility in a ``pykoclaw.config_utils`` module.

    Note: ``PYKOCLAW_DATA`` is read from the *environment* at instantiation
    time, not from any ``.env`` file.  This avoids a chicken-and-egg problem
    (we need to know the data dir before we can locate its ``.env``).
    """
    files: list[str] = []
    # 1. Global XDG config dir (lowest priority among files)
    files.append(str(user_config_path("pykoclaw", appauthor=False) / ".env"))
    # 2. Per-data-dir override (only if PYKOCLAW_DATA is explicitly set)
    pykoclaw_data = os.environ.get("PYKOCLAW_DATA")
    if pykoclaw_data:
        files.append(str(Path(pykoclaw_data) / ".env"))
    # 3. CWD .env (highest priority among files)
    files.append(".env")
    return tuple(files)


class Settings(BaseSettings):
    model_config = {
        "extra": "ignore",
        "env_prefix": "PYKOCLAW_",
        "env_file_encoding": "utf-8",
    }

    data: Path = Field(
        default_factory=lambda: user_data_path("pykoclaw", appauthor=False)
    )
    model: str = "claude-sonnet-4-6"
    cli_path: Path | None = None
    idle_timeout: int = 1800  # Worker idle timeout in seconds (default 30 min)
    # The real-world name this agent instance goes by (e.g. "Tyko", "Ressu").
    # When set, it is woven into the identity prefix of every system prompt so
    # the agent knows that "Claude Code" is merely the technical runtime name
    # and that it should present itself as <agent_name> to users.
    agent_name: str | None = None
    # Accept BRAVE_API_KEY (no prefix) or PYKOCLAW_BRAVE_API_KEY.
    # The env_prefix is not applied when validation_alias is set.
    brave_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("BRAVE_API_KEY", "PYKOCLAW_BRAVE_API_KEY"),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            DotEnvSettingsSource(settings_cls, env_file=_build_env_files()),
            file_secret_settings,
        )

    @property
    def db_path(self) -> Path:
        return self.data / "pykoclaw.db"


settings = Settings()
