# Learnings

## 2026-02-09 Session Start
- Project: pykoclaw — Python CLI AI agent reimplementing nanoclaw
- Stack: claude-agent-sdk, SQLite, argparse, croniter, uv_build
- User preferences: minimal code, no comments, no exception handling, functions over classes, idiomatic Python
- pathlib.Path required, dedent() for multi-line strings (AGENTS.md)

## Wave 1: Project Skeleton (2026-02-09)
- Created pyproject.toml with uv_build>=0.9.2,<0.10.0
- Package structure: src/pykoclaw/ with __init__.py, __main__.py
- CLI uses argparse with 4 subcommands: chat, scheduler, conversations, tasks
- All stubs print "not implemented yet"
- Used dedent() for multi-line description string
- uv sync resolves 35 packages successfully
- Commit: ba9d2c4 (feat: create project skeleton...)
- All verification checks passed:
  - import pykoclaw → ok
  - pykoclaw --help → shows all 4 subcommands
  - uv run pykoclaw chat → "not implemented yet"

## Wave 2: SQLite Database Layer (2026-02-09)
- Created src/pykoclaw/db.py with 13 functions for conversations and scheduled tasks
- Schema: conversations (name, session_id, cwd, created_at), scheduled_tasks (id, conversation, prompt, schedule_type, schedule_value, context_mode, next_run, last_run, last_result, status, created_at), task_run_logs (id, task_id, run_at, duration_ms, status, result, error)
- All functions use sqlite3.Connection as first param, no ORM, no classes
- Used sqlite3.Row factory for dict-like row access
- All multi-line SQL strings use dedent() from textwrap
- Type hints: dict[str, object] for row dicts, list[dict[str, object]] for lists
- Functions: init_db, upsert_conversation, get_conversation, list_conversations, create_task, get_task, get_tasks_for_conversation, get_all_tasks, update_task, delete_task, get_due_tasks, update_task_after_run, log_task_run
- Verification test passed: all CRUD operations work correctly
- Commit: 1e3dd57 (feat: implement SQLite database layer...)
- Pushed to main

## Wave 3: Custom MCP Tools (2026-02-09)
- Created src/pykoclaw/tools.py with 5 tools for task scheduling
- Tools: schedule_task, list_tasks, pause_task, resume_task, cancel_task
- Used @tool decorator from claude-agent-sdk with async handlers
- schedule_task: generates UUID id (8 chars), calculates next_run using croniter for cron, timedelta for interval, direct value for once
- list_tasks: queries get_tasks_for_conversation, formats output
- pause_task: updates status to 'paused'
- resume_task: recalculates next_run based on schedule_type, updates status to 'active'
- cancel_task: deletes task via delete_task
- make_mcp_server(db, conversation) returns create_sdk_mcp_server result with all 5 tools
- Tool handlers return {"content": [{"type": "text", "text": "..."}]} format
- Verification test passed: server['name'] == 'pykoclaw'
- Commit: 1750368 (feat: implement custom MCP tools for task scheduling)
- Pushed to main

## Wave 4: Scheduler Process (2026-02-09)
- Created src/pykoclaw/scheduler.py with async task runner
- Functions: run_task(task, db, data_dir), run_scheduler(db, data_dir)
- run_task:
  - Creates ClaudeSDKClient with conversation cwd
  - Supports context_mode: 'group' (resume session) or 'isolated' (no resume)
  - Calculates next_run: cron via croniter, interval via timedelta, once → None
  - Streams response with [task:id] prefix
  - Logs task run with duration, status, result, error
- run_scheduler:
  - Polls every 60s for due tasks via get_due_tasks(db)
  - Runs each due task serially via run_task
  - Prints "Scheduler started" to stderr
- Imports: ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock from claude_agent_sdk
- Used dedent() for multi-line strings (none needed in this file)
- Verification test passed: import pykoclaw.scheduler → SCHEDULER_OK
- Commit: c930e07 (feat: implement scheduler process for timed task execution)
- Pushed to main

## Wave 5: Agent Conversation REPL (2026-02-09)
- Created src/pykoclaw/agent.py with async REPL loop
- Function: run_conversation(name, db, data_dir)
- REPL pattern: print "> " to stderr, read stdin via input(), send to client.query(), stream TextBlock responses
- Multi-turn: keep ClaudeSDKClient alive across the loop (single async with block), no continue_conversation param needed
- SDK multi-turn: just call client.query() again within same context manager — SDK handles context automatically
- SystemMessage with subtype 'init' provides session_id for DB upsert
- ResultMessage also has session_id but we capture from SystemMessage per spec
- CLAUDE.md hierarchy: global {data_dir}/CLAUDE.md as system_prompt (plain string or None), per-conversation via setting_sources=["project"]
- Empty input (just Enter) is skipped with continue, EOFError (Ctrl+D) breaks the loop
- No dedent() needed — no multi-line strings in this module
- LSP errors about claude_agent_sdk are pre-existing venv/LSP issue (same in scheduler.py, tools.py)
- Verification: `uv run python -c "import pykoclaw.agent; print('ok')"` → ok

## Wave 6: CLI Argument Wiring (2026-02-09)
- Updated src/pykoclaw/__main__.py to wire all argparse subcommands to implementations
- chat subcommand: added positional `name` argument, calls `asyncio.run(run_conversation(name, db, data_dir))`
- scheduler subcommand: calls `asyncio.run(run_scheduler(db, data_dir))`
- conversations subcommand: calls `list_conversations(db)`, prints name | session_id | created_at
- tasks subcommand: calls `get_all_tasks(db)`, prints id | conversation | prompt[:50] | status | next_run
- main() initializes DB via `init_db(data_dir / "pykoclaw.db")` before dispatching
- data_dir computed as `Path(os.environ.get("PYKOCLAW_DATA", "")) or (Path.home() / ".local" / "share" / "pykoclaw")`
- Used dict.get() for safe access to task/conversation fields (type safety)
- Verification passed:
  - `uv run pykoclaw --help` shows all 4 subcommands with chat taking name argument
  - `uv run pykoclaw conversations` exits 0 (empty output on fresh DB)
  - `uv run pykoclaw tasks` exits 0 (empty output on fresh DB)
- LSP diagnostics: only warnings (stub files, unused imports removed)

## Wave 7: Smoke Tests (2026-02-09)
- Created tests/test_db.py with 5 tests for database layer
  - test_init_db_creates_tables: verifies all 3 tables created
  - test_conversation_crud: upsert, get, list conversations
  - test_task_crud: create, get, get_tasks_for_conversation, get_all_tasks, update, delete
  - test_due_tasks: create task with past next_run, verify get_due_tasks returns it
  - test_log_task_run: log a task run, verify it's in the DB
- Created tests/test_tools.py with 2 tests for MCP tools
  - test_make_mcp_server_returns_config: verify server dict with name == 'pykoclaw'
  - test_mcp_server_has_tools: verify ListToolsRequest handler registered
- Used pytest fixtures with tmp_path for temp DB files
- All tests use plain assert statements, no exception handling
- Verification: `uv run pytest -x -v` passes all 7 tests
- Commit: (pending)
