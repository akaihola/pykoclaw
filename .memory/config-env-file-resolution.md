# Config .env File Resolution

**Tags:** config, pydantic-settings, XDG, platformdirs
**Related:** [plugin-config-env-file.md]

## How settings are loaded (pykoclaw + pykoclaw-pykofinder)

Both packages use `settings_customise_sources()` with a dynamic `_build_env_files()`
function (defined in `pykoclaw.config`) to build the `.env` load order at
instantiation time.

**Precedence (lowest → highest):**

1. `user_config_path("pykoclaw", appauthor=False) / ".env"`
   → `~/.config/pykoclaw/.env` on Linux (respects `XDG_CONFIG_HOME`)
2. `$PYKOCLAW_DATA/.env` — only loaded if `PYKOCLAW_DATA` env var is set
3. CWD `.env`
4. Actual environment variables (always override all files)

## Key design decisions

- `_build_env_files()` reads `os.environ.get("PYKOCLAW_DATA")` at
  instantiation time — no chicken-and-egg issue since `PYKOCLAW_DATA` must
  be an explicit env var (not read from `.env` files).
- `platformdirs.user_data_path("pykoclaw")` is used as `settings.data` default
  (computed via `Field(default_factory=...)`).
- `pykoclaw-pykofinder` imports `_build_env_files` from `pykoclaw.config`
  so both share exactly the same resolution logic.

## Production config location

Global config lives at `~/.config/pykoclaw/.env`.
Old location (`~/.local/share/pykoclaw/.env`) is no longer read.

[plugin-config-env-file.md]: plugin-config-env-file.md
