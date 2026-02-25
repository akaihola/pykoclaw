from pathlib import Path

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
    model: str = "claude-opus-4-6"
    cli_path: Path | None = None
    idle_timeout: int = 1800  # Worker idle timeout in seconds (default 30 min)

    @property
    def db_path(self) -> Path:
        return self.data / "pykoclaw.db"


settings = Settings()
