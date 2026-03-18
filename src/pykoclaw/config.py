from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {
        "extra": "ignore",
        "env_prefix": "PYKOCLAW_",
        "env_file": (
            str(Path.home() / ".local" / "share" / "pykoclaw" / ".env"),
            ".env",
        ),
        "env_file_encoding": "utf-8",
    }

    data: Path = Path.home() / ".local" / "share" / "pykoclaw"
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

    @property
    def db_path(self) -> Path:
        return self.data / "pykoclaw.db"


settings = Settings()
