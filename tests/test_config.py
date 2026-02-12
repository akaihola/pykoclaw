"""Tests for Settings configuration and .env file loading."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pykoclaw.config import Settings


class TestSettingsDefaults:
    """Test Settings default values in isolated environment."""

    def test_settings_defaults_no_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings uses defaults when no .env file exists."""
        # Change to temp dir with no .env file
        monkeypatch.chdir(tmp_path)

        settings = Settings()

        assert settings.model == "claude-opus-4-6"
        assert settings.data == Path.home() / ".local" / "share" / "pykoclaw"

    def test_settings_db_path_property(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings.db_path property."""
        monkeypatch.chdir(tmp_path)

        settings = Settings()

        expected = Path.home() / ".local" / "share" / "pykoclaw" / "pykoclaw.db"
        assert settings.db_path == expected


class TestSettingsEnvFileLoading:
    """Test Settings loads from .env file in CWD."""

    def test_settings_loads_from_cwd_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings loads PYKOCLAW_MODEL from .env in CWD."""
        # Create .env file in temp dir
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_MODEL=claude-3-sonnet\n")

        # Change to temp dir
        monkeypatch.chdir(tmp_path)

        settings = Settings()

        assert settings.model == "claude-3-sonnet"

    def test_settings_loads_custom_data_path_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings loads PYKOCLAW_DATA from .env in CWD."""
        custom_data = tmp_path / "custom_data"
        custom_data.mkdir()

        env_file = tmp_path / ".env"
        env_file.write_text(f"PYKOCLAW_DATA={custom_data}\n")

        monkeypatch.chdir(tmp_path)

        settings = Settings()

        assert settings.data == custom_data

    def test_settings_loads_multiple_vars_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings loads multiple PYKOCLAW_* vars from .env."""
        custom_data = tmp_path / "my_data"
        custom_data.mkdir()

        env_file = tmp_path / ".env"
        env_file.write_text(
            dedent(f"""\
                PYKOCLAW_MODEL=claude-3-haiku
                PYKOCLAW_DATA={custom_data}
                """)
        )

        monkeypatch.chdir(tmp_path)

        settings = Settings()

        assert settings.model == "claude-3-haiku"
        assert settings.data == custom_data


class TestSettingsEnvVarOverride:
    """Test environment variables override .env file values."""

    def test_env_var_overrides_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test env var PYKOCLAW_MODEL overrides .env value."""
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_MODEL=from-env-file\n")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PYKOCLAW_MODEL", "from-env-var")

        settings = Settings()

        assert settings.model == "from-env-var"

    def test_env_var_overrides_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test env var PYKOCLAW_MODEL overrides default."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PYKOCLAW_MODEL", "claude-3-opus")

        settings = Settings()

        assert settings.model == "claude-3-opus"

    def test_precedence_env_var_over_env_file_over_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test full precedence: env var > .env file > default."""
        env_file = tmp_path / ".env"
        env_file.write_text("PYKOCLAW_MODEL=from-env-file\n")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PYKOCLAW_MODEL", "from-env-var")

        settings = Settings()

        # Should use env var, not .env file or default
        assert settings.model == "from-env-var"


class TestSettingsEnvFileIgnoresWrongPrefix:
    """Test Settings ignores env vars with wrong prefix."""

    def test_settings_ignores_non_pykoclaw_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings ignores MODEL (no PYKOCLAW_ prefix)."""
        env_file = tmp_path / ".env"
        env_file.write_text("MODEL=should-be-ignored\n")

        monkeypatch.chdir(tmp_path)

        settings = Settings()

        # Should use default, not the unprefixed MODEL var
        assert settings.model == "claude-opus-4-6"

    def test_settings_ignores_wrong_prefix_in_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings ignores OTHER_MODEL env var."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OTHER_MODEL", "should-be-ignored")

        settings = Settings()

        assert settings.model == "claude-opus-4-6"


class TestSettingsEnvFileEncoding:
    """Test Settings handles .env file encoding correctly."""

    def test_settings_reads_utf8_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings reads UTF-8 encoded .env file."""
        env_file = tmp_path / ".env"
        # Write UTF-8 content with special characters
        env_file.write_text("PYKOCLAW_MODEL=claude-3-sonnet-utf8-✓\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)

        settings = Settings()

        assert "utf8-✓" in settings.model


class TestSettingsMissingEnvFile:
    """Test Settings handles missing .env files gracefully."""

    def test_settings_works_without_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings works fine when .env doesn't exist."""
        # Ensure no .env file exists
        assert not (tmp_path / ".env").exists()

        monkeypatch.chdir(tmp_path)

        # Should not crash, should use defaults
        settings = Settings()

        assert settings.model == "claude-opus-4-6"

    def test_settings_works_with_empty_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings works with empty .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("")

        monkeypatch.chdir(tmp_path)

        settings = Settings()

        assert settings.model == "claude-opus-4-6"

    def test_settings_works_with_comments_only_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Settings works with .env file containing only comments."""
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\n# Another comment\n")

        monkeypatch.chdir(tmp_path)

        settings = Settings()

        assert settings.model == "claude-opus-4-6"
