# Test Coverage Analysis

**Date**: 2026-02-10
**Overall coverage**: 31% (7 tests, 262 statements, 182 missed)

## Current Coverage by Module

| Module | Stmts | Miss | Cover | Notes |
|---|---|---|---|---|
| `__init__.py` | 1 | 0 | 100% | Trivial |
| `db.py` | 64 | 5 | 92% | Best tested; small gaps |
| `tools.py` | 58 | 38 | 34% | Only structure tested, no handlers |
| `__main__.py` | 43 | 43 | 0% | No tests |
| `agent.py` | 37 | 37 | 0% | No tests |
| `scheduler.py` | 59 | 59 | 0% | No tests |

## Priority 1 — `tools.py` Tool Handlers

The 5 MCP tool handlers (`schedule_task`, `list_tasks`, `pause_task`, `resume_task`,
`cancel_task`) are async functions that operate on the database with no external SDK
dependency at call time. They are the highest-value targets for new tests.

Recommended tests:
- `schedule_task`: cron, interval, and one-time schedule types; verify DB task creation
- `list_tasks`: empty case and populated case; verify output format
- `pause_task` / `resume_task`: status transitions; `resume_task` recalculates `next_run`
- `resume_task` for a non-existent task (returns "not found")
- `cancel_task`: verify task and logs are deleted

## Priority 2 — `db.py` Remaining Gaps

- `update_task_after_run()` — completely untested (lines 183-192)
- `update_task()` with no recognized keys — early-return path (line 154)
- `_data_dir()` — env var and fallback paths (line 9)
- `upsert_conversation` conflict path — update existing conversation
- `get_due_tasks` with mixed statuses (active, paused, future)

## Priority 3 — `__main__.py` CLI

- Argument parsing for each subcommand
- `conversations` and `tasks` output formatting (mock DB, capture stdout)
- Default help case when no command given
- `PYKOCLAW_DATA` env var handling

## Priority 4 — `scheduler.py`

Requires mocking `ClaudeSDKClient`:
- `run_task()` happy path: next_run calculation for cron/interval/once
- `run_task()` error path: exception handling, error logging
- `run_scheduler()` loop: dispatches due tasks, sleeps between iterations

## Priority 5 — `agent.py`

Hardest to test (tightly coupled to SDK):
- Setup logic: CLAUDE.md creation, options construction
- Input loop with mocked stdin
- `upsert_conversation` called on `ResultMessage`

## Structural Recommendations

1. Add shared `conftest.py` (db fixture is duplicated across test files)
2. Add `pytest-cov` to dev dependencies
3. Add `[tool.pytest.ini_options]` in `pyproject.toml` with coverage defaults
4. Set `--cov-fail-under=60` to prevent regressions
