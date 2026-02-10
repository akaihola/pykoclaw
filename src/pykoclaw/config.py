from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "PYKOCLAW_"}

    data: Path = Path.home() / ".local" / "share" / "pykoclaw"
    model: str = "claude-opus-4-6"

    @property
    def db_path(self) -> Path:
        return self.data / "pykoclaw.db"


settings = Settings()
