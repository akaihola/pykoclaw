# pykoclaw

Python CLI AI agent framework built on `claude-agent-sdk` and `croniter`.

## Project structure

- `src/pykoclaw/` — package source
  - `__main__.py` — CLI entrypoint (Click command group)
  - `agent_core.py` — `query_agent()` async generator for streaming Claude
    responses
  - `config.py` — Pydantic Settings (`PYKOCLAW_` env prefix, `.env` support)
  - `db.py` — SQLite database layer (conversations, scheduled\_tasks,
    task\_run\_logs, delivery\_queue)
  - `models.py` — Pydantic models (`ScheduledTask`, `TaskRunLog`,
    `DeliveryQueueItem`)
  - `plugins.py` — Plugin protocol, discovery, and migration runner
  - `scheduler.py` — timed task execution via `croniter`, delivery queue writes
  - `scheduling.py` — cron/interval/once schedule helpers
  - `tools.py` — MCP tool definitions (`schedule_task`, `list_tasks`,
    `pause_task`, `resume_task`, `cancel_task`)
- `tests/` — `pytest` test suite

## Build & run

- **Package manager:** `uv`
- **Python:** >=3.12
- **Install deps:** `uv sync`
- **Install dev deps:** `uv sync --dev`
- **Run:** `uv run pykoclaw`
- **Tests:** `uv run pytest`

## Conventions

- Keep code simple and minimal; avoid over-engineering.
- Use type hints for function signatures.
- Follow standard Python naming: `snake_case` for functions/variables,
  `PascalCase` for classes.
- Use `pathlib.Path` over `os.path`.
- Use `textwrap.dedent()` for all multi-line strings.
- Pydantic models for data classes; Pydantic Settings for configuration.
- In Markdown files, use reference links — never inline `[text](url)`.
