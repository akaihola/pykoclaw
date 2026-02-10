# pykoclaw

Python CLI AI agent built with `claude-agent-sdk` and `croniter`.

## Project structure

- `src/pykoclaw/` — package source
  - `__main__.py` — CLI entrypoint (`argparse` subcommands)
  - `agent.py` — conversation loop with CLAUDE.md memory
  - `db.py` — SQLite database layer
  - `scheduler.py` — timed task execution via `croniter`
  - `tools.py` — MCP tool definitions
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
- Follow standard Python naming: `snake_case` for functions/variables, `PascalCase` for classes.
