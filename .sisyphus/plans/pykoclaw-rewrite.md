# pykoclaw — Python CLI AI Agent (Reimplementation of nanoclaw)

## TL;DR

> **Quick Summary**: Reimplement nanoclaw (Node.js WhatsApp AI agent) as a minimal Python CLI application using `claude-agent-sdk`. pykoclaw is a thin wrapper that adds named conversations, SQLite persistence, scheduled tasks, and custom MCP tools around the SDK's built-in agent capabilities.
>
> **Deliverables**:
> - Python package `pykoclaw` with `pyproject.toml` (uv_build)
> - CLI entrypoint: `pykoclaw chat <name>` (REPL conversation loop)
> - CLI entrypoint: `pykoclaw scheduler` (scheduled task runner)
> - SQLite database for conversations, sessions, scheduled tasks
> - Custom MCP server for scheduler tools (schedule_task, list_tasks, etc.)
> - Per-conversation memory via CLAUDE.md files
> - Minimal smoke tests
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 3 waves
> **Critical Path**: Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 7

---

## Context

### Original Request
Reimplement `nanoclaw/` (a Node.js WhatsApp AI agent using Claude Agent SDK) as `pykoclaw` in Python. Use minimal code, idiomatic Python, functions over classes, proper Python package with uv_build.

### Interview Summary
**Key Discussions**:
- I/O: CLI (stdin/stdout) instead of WhatsApp — REPL-style conversation loop
- Execution: Direct (no containers) — SDK tools run on host
- Scope: Full feature parity adapted for CLI — groups → named conversations, scheduler as separate process
- Agent SDK: `claude-agent-sdk` (Python) instead of `simonw/llm` — provides built-in tools and session management
- Default model: claude-opus-4-6
- Tests: Minimal smoke tests

**Research Findings**:
- `claude-agent-sdk` provides `ClaudeSDKClient` for multi-turn conversations with session persistence
- Built-in tools: Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch
- Custom tools via `@tool` decorator + `create_sdk_mcp_server()` for in-process MCP servers
- Session resume via `resume` parameter in `ClaudeAgentOptions`
- SDK spawns Claude Code CLI as subprocess — tools access local filesystem/commands directly
- `setting_sources=["project"]` required to load CLAUDE.md files

### Metis Review
**Identified Gaps** (addressed):
- CLI interaction model → Auto-resolved: REPL mode (simplest, matches minimal code philosophy)
- `send_message` tool in CLI → Auto-resolved: prints to stdout
- PreCompact hook / archiving → Out of scope for v1
- CLAUDE.md hierarchy → `cwd` per conversation + global CLAUDE.md as system_prompt append
- Main conversation privileges → All conversations equal (user is admin in CLI)
- Data directory → XDG `~/.local/share/pykoclaw/`
- Conversation creation → auto-created on first `pykoclaw chat <name>`
- Message storage → Rely on SDK sessions, no separate message table
- CLI arg parser → `argparse` (no extra deps)
- Session resume validation → Include as Task 0 spike

---

## Work Objectives

### Core Objective
Create a minimal Python CLI agent that provides nanoclaw's core capabilities (named conversations with memory, scheduled tasks, agent tools) using claude-agent-sdk, with maximum code economy.

### Concrete Deliverables
- `pyproject.toml` — package metadata with uv_build, dependencies
- `src/pykoclaw/__init__.py` — package init
- `src/pykoclaw/__main__.py` — CLI entrypoint (argparse)
- `src/pykoclaw/db.py` — SQLite operations
- `src/pykoclaw/agent.py` — ClaudeSDKClient conversation loop
- `src/pykoclaw/tools.py` — Custom MCP tools for scheduler
- `src/pykoclaw/scheduler.py` — Scheduled task runner
- `tests/test_db.py` — DB smoke tests
- `tests/test_tools.py` — MCP tool smoke tests

### Definition of Done
- [ ] `uv sync` completes without errors
- [ ] `uv run pykoclaw --help` shows subcommands (chat, scheduler)
- [ ] `uv run pykoclaw chat main` enters REPL, can send/receive messages
- [ ] Conversation resumes across restart (same session)
- [ ] `uv run pykoclaw scheduler` polls for due tasks
- [ ] Scheduler tools work from within a conversation
- [ ] Per-conversation CLAUDE.md files are loaded
- [ ] `uv run pytest` passes

### Must Have
- Named conversations with isolated working directories
- SQLite persistence for sessions and scheduled tasks
- Session resume across process restarts
- Scheduler as separate process with cron/interval/once support
- Custom MCP tools: schedule_task, list_tasks, pause_task, resume_task, cancel_task (5 tools, matching nanoclaw minus WhatsApp-specific ones)
- CLAUDE.md memory hierarchy (global + per-conversation)
- No Claude Code system prompt preset — the `claude_code` preset is a huge coding-focused prompt unnecessary for a general assistant. Use `system_prompt=None` (SDK default) or global CLAUDE.md as a plain string. The built-in tools (Bash, Read, etc.) work regardless of system prompt.
- Minimal code throughout

### Must NOT Have (Guardrails)
- No WhatsApp/messaging integration
- No container/Docker/sandbox isolation
- No IPC file-based communication
- No GroupQueue concurrency system
- No rich terminal UI (curses/blessed/rich/textual)
- No configuration files — env vars + CLI args only
- No abstract base classes or custom exception hierarchies
- No exception handling or defensive coding
- No extra comments in code
- No click/typer dependency (use argparse)
- No classes where functions suffice
- No PreCompact hooks or transcript archiving
- No message cursor recovery or retry backoff logic

---

## Verification Strategy

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
>
> ALL tasks in this plan MUST be verifiable WITHOUT any human action.

### Test Decision
- **Infrastructure exists**: NO (fresh project)
- **Automated tests**: YES (tests-after, minimal smoke tests)
- **Framework**: pytest

### Agent-Executed QA Scenarios (MANDATORY — ALL tasks)

**Verification Tool by Deliverable Type:**

| Type | Tool | How Agent Verifies |
|------|------|-------------------|
| Package setup | Bash | `uv sync`, `uv run python -c "import pykoclaw"` |
| CLI | Bash (timeout + pipe) | `echo "quit" \| timeout 10 uv run pykoclaw chat main` |
| Scheduler | Bash (timeout) | `timeout 5 uv run pykoclaw scheduler; test $? -eq 124` |
| Tests | Bash | `uv run pytest -x` |

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately):
├── Task 1: Project skeleton (pyproject.toml, package structure)
└── Task 0: SDK session resume validation spike (independent research)

Wave 2 (After Wave 1):
├── Task 2: SQLite database layer
├── Task 3: Custom MCP tools for scheduler
└── (Task 0 findings inform Task 4 design)

Wave 3 (After Wave 2):
├── Task 4: Agent conversation loop (core)
├── Task 5: Scheduler process
└── Task 6: CLAUDE.md memory hierarchy

Wave 4 (After Wave 3):
├── Task 7: CLI entrypoint (argparse, wiring)
└── Task 8: Smoke tests
```

### Dependency Matrix

| Task | Depends On | Blocks | Can Parallelize With |
|------|------------|--------|---------------------|
| 0 | None | 4 | 1 |
| 1 | None | 2, 3, 4, 5, 6, 7 | 0 |
| 2 | 1 | 4, 5 | 3 |
| 3 | 1 | 4 | 2 |
| 4 | 0, 2, 3 | 7 | 5, 6 |
| 5 | 2 | 7 | 4, 6 |
| 6 | 1 | 7 | 4, 5 |
| 7 | 4, 5, 6 | 8 | None |
| 8 | 7 | None | None |

### Agent Dispatch Summary

| Wave | Tasks | Recommended Agents |
|------|-------|--------------------|
| 1 | 0, 1 | task(category="quick") for both |
| 2 | 2, 3 | task(category="quick") for both |
| 3 | 4, 5, 6 | task(category="unspecified-high") for 4; task(category="quick") for 5, 6 |
| 4 | 7, 8 | task(category="quick") for both |

---

## TODOs

- [x] 0. Validate SDK session resume across process restarts (RESULT: resume BROKEN in SDK, works in CLI. Multi-turn must stay within same client instance.)

  **What to do**:
  - Write a standalone Python script that:
    1. Creates a `ClaudeSDKClient` with `ClaudeAgentOptions(permission_mode='bypassPermissions')`
    2. Sends a prompt, captures the session_id from the `SystemMessage` (subtype `init`)
    3. Exits the process
    4. Starts again with `ClaudeAgentOptions(resume=session_id)`
    5. Sends a follow-up referencing the first prompt
    6. Verifies Claude remembers context
  - Document: where does the SDK store session data? (`~/.claude/` JSONL files?)
  - Document: does `resume` work with `ClaudeSDKClient` or only `query()`?
  - If resume doesn't work as expected, document the workaround

  **Must NOT do**:
  - Don't build any pykoclaw infrastructure
  - Don't over-engineer — this is a validation spike

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Small standalone script, focused validation
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: Task 4 (conversation loop design depends on resume behavior)
  - **Blocked By**: None

  **References**:
  - `nanoclaw/container/agent-runner/src/index.ts:466` — How nanoclaw passes `sessionId` to resume: `resume: sessionId` in query options
  - `nanoclaw/src/index.ts:311` — How nanoclaw stores/retrieves session IDs via `sessions[group.folder]`
  - Claude Agent SDK Python docs — `ClaudeSDKClient` class, `resume` parameter in `ClaudeAgentOptions`
  - Claude Agent SDK Python docs — `SystemMessage` with `subtype='init'` contains `session_id`

  **Acceptance Criteria**:

  ```
  Scenario: Validate session resume across restarts
    Tool: Bash
    Preconditions: claude-agent-sdk installed, ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN set
    Steps:
      1. Create temp directory for test
      2. Write validation script (PEP 723 inline metadata)
      3. Run: uv run /tmp/test_resume.py
      4. Assert: script exits 0
      5. Assert: stdout contains "RESUME_OK" (the script prints this on success)
    Expected Result: Session resumes with context from first exchange
    Evidence: Script stdout captured
  ```

  **Commit**: NO (spike — results inform design, script is throwaway)

---

- [x] 1. Create project skeleton with pyproject.toml

  **What to do**:
  - Create `pyproject.toml` with:
    - `[project]`: name=pykoclaw, version=0.1.0, requires-python>=3.12
    - `[project.dependencies]`: claude-agent-sdk, cron-parser (or croniter for Python)
    - `[project.optional-dependencies]`: dev = ["pytest"]
    - `[project.scripts]`: pykoclaw = "pykoclaw.__main__:main"
    - `[build-system]`: requires=["uv_build>=0.9.2,<0.10.0"], build-backend="uv_build"
  - Create `src/pykoclaw/__init__.py` (empty or version only)
  - Create `src/pykoclaw/__main__.py` with stub `main()` that prints help
  - Create `tests/__init__.py` (empty)
  - Run `uv sync` to create venv and install deps
  - Verify: `uv run pykoclaw --help` exits 0

  **Must NOT do**:
  - Don't implement any real functionality yet
  - Don't add unnecessary dependencies
  - Don't create config files

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Boilerplate file creation, no logic
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 0)
  - **Blocks**: Tasks 2, 3, 4, 5, 6, 7
  - **Blocked By**: None

  **References**:
  - `nanoclaw/package.json` — Reference for dependency list and project metadata
  - uv_build docs: https://docs.astral.sh/uv/concepts/build-backends/
  - AGENTS.md — Use `uv sync`, `uv run`, `pathlib.Path`, `dedent()` for multi-line strings

  **Acceptance Criteria**:

  ```
  Scenario: Package installs and runs
    Tool: Bash
    Preconditions: uv installed
    Steps:
      1. uv sync
      2. Assert: exit code 0
      3. uv run python -c "import pykoclaw; print('ok')"
      4. Assert: stdout contains "ok"
      5. uv run pykoclaw --help
      6. Assert: exit code 0, stdout contains "pykoclaw" and "chat" and "scheduler"
    Expected Result: Package installed, CLI shows help
    Evidence: Command outputs captured
  ```

  **Commit**: YES
  - Message: `feat: create project skeleton with pyproject.toml and package structure`
  - Files: `pyproject.toml`, `src/pykoclaw/__init__.py`, `src/pykoclaw/__main__.py`, `tests/__init__.py`
  - Pre-commit: `uv run pykoclaw --help`

---

- [x] 2. Implement SQLite database layer

  **What to do**:
  - Create `src/pykoclaw/db.py` with functions:
    - `init_db(db_path: Path) -> sqlite3.Connection` — creates tables, returns connection
    - Tables: `conversations` (name TEXT PK, session_id TEXT, cwd TEXT, created_at TEXT), `scheduled_tasks` (id TEXT PK, conversation TEXT, prompt TEXT, schedule_type TEXT, schedule_value TEXT, context_mode TEXT DEFAULT 'isolated', next_run TEXT, last_run TEXT, last_result TEXT, status TEXT DEFAULT 'active', created_at TEXT), `task_run_logs` (id INTEGER PK AUTOINCREMENT, task_id TEXT, run_at TEXT, duration_ms INTEGER, status TEXT, result TEXT, error TEXT)
    - CRUD functions for conversations: `get_conversation`, `upsert_conversation`, `list_conversations`
    - CRUD functions for tasks: `create_task`, `get_task`, `get_tasks_for_conversation`, `get_all_tasks`, `update_task`, `delete_task`, `get_due_tasks`, `update_task_after_run`, `log_task_run`
  - Data directory: `Path(os.environ.get("PYKOCLAW_DATA", Path.home() / ".local" / "share" / "pykoclaw"))`
  - DB file at: `{data_dir}/pykoclaw.db`

  **Must NOT do**:
  - No ORM (SQLAlchemy, peewee, etc.)
  - No migration framework
  - No connection pooling
  - No parameter validation

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Straightforward CRUD, schema from nanoclaw as reference
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Task 3)
  - **Blocks**: Tasks 4, 5
  - **Blocked By**: Task 1

  **References**:
  - `nanoclaw/src/db.ts:12-113` — SQLite schema: tables for messages, scheduled_tasks, task_run_logs, router_state, sessions, registered_groups. Adapt for CLI concepts (groups → conversations, no messages table, no router_state, no registered_groups)
  - `nanoclaw/src/db.ts:284-415` — Task CRUD functions: createTask, getTaskById, getTasksForGroup, getAllTasks, updateTask, deleteTask, getDueTasks, updateTaskAfterRun, logTaskRun — port these directly
  - `nanoclaw/src/types.ts:53-75` — ScheduledTask and TaskRunLog interfaces — port field names
  - AGENTS.md — Use `pathlib.Path` over `os.path`

  **Acceptance Criteria**:

  ```
  Scenario: Database creates tables and CRUD works
    Tool: Bash
    Preconditions: uv sync completed
    Steps:
      1. uv run python -c "
         from pykoclaw.db import init_db; from pathlib import Path; import tempfile
         db = init_db(Path(tempfile.mktemp(suffix='.db')))
         # Test conversation CRUD
         from pykoclaw.db import upsert_conversation, get_conversation, list_conversations
         upsert_conversation(db, 'test', 'sess-1', '/tmp/test')
         c = get_conversation(db, 'test')
         assert c['session_id'] == 'sess-1', f'Expected sess-1, got {c}'
         # Test task CRUD
         from pykoclaw.db import create_task, get_task, get_due_tasks
         create_task(db, id='t1', conversation='test', prompt='hello', schedule_type='once', schedule_value='2020-01-01T00:00:00Z', next_run='2020-01-01T00:00:00Z')
         t = get_task(db, 't1')
         assert t['prompt'] == 'hello'
         due = get_due_tasks(db)
         assert len(due) == 1
         print('DB_OK')
         "
      2. Assert: stdout contains "DB_OK"
    Expected Result: All CRUD operations work
    Evidence: Command output captured
  ```

  **Commit**: YES
  - Message: `feat: implement SQLite database layer for conversations and tasks`
  - Files: `src/pykoclaw/db.py`
  - Pre-commit: inline test above

---

- [x] 3. Implement custom MCP tools for scheduler

  **What to do**:
  - Create `src/pykoclaw/tools.py` with:
    - Use `@tool` decorator from `claude_agent_sdk` for each tool
    - Tools: `schedule_task` (creates task in SQLite), `list_tasks` (lists tasks), `pause_task`, `resume_task`, `cancel_task` — these 5 match nanoclaw's MCP tools (minus send_message and register_group which don't apply to CLI)
    - A `make_mcp_server(db: sqlite3.Connection, conversation: str) -> McpSdkServerConfig` function that creates the in-process MCP server with all tools bound to the given db/conversation
    - Tools write to SQLite directly (same DB as scheduler process reads)
  - Remove `send_message` tool — in CLI mode, agent output goes directly to stdout

  **Must NOT do**:
  - No `send_message` tool (stdout is the output channel)
  - No group authorization checks (all conversations equal in CLI)
  - No IPC file writing

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Straightforward tool definitions following SDK pattern
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Task 2)
  - **Blocks**: Task 4
  - **Blocked By**: Task 1

  **References**:
  - `nanoclaw/container/agent-runner/src/ipc-mcp-stdio.ts` — Original MCP tool definitions: send_message, schedule_task, list_tasks, pause_task, resume_task, cancel_task, register_group. NOTE: nanoclaw does NOT have get_task or update_task tools — those are pykoclaw additions for better CLI UX. register_group is WhatsApp-specific and dropped. send_message is dropped (stdout is the output channel). Port schedule_task, list_tasks, pause_task, resume_task, cancel_task tool names, descriptions, and input schemas.
  - Claude Agent SDK Python docs — `@tool` decorator, `create_sdk_mcp_server()`, `SdkMcpTool`, tool input schemas
  - `nanoclaw/src/index.ts:560-758` — processTaskIpc: how host processes task commands (schedule_task creates task with cron parsing, pause/resume/cancel update DB). Port this logic into the tool handlers.

  **Acceptance Criteria**:

  ```
  Scenario: MCP tools can be created and have correct names
    Tool: Bash
    Preconditions: uv sync completed
    Steps:
      1. uv run python -c "
         from pykoclaw.tools import make_mcp_server
         from pykoclaw.db import init_db
         from pathlib import Path; import tempfile
         db = init_db(Path(tempfile.mktemp(suffix='.db')))
         server = make_mcp_server(db, 'test')
         assert server['name'] == 'pykoclaw'
         print('TOOLS_OK')
         "
      2. Assert: stdout contains "TOOLS_OK"
    Expected Result: MCP server creates successfully with tools
    Evidence: Command output captured
  ```

  **Commit**: YES
  - Message: `feat: implement custom MCP tools for task scheduling`
  - Files: `src/pykoclaw/tools.py`
  - Pre-commit: inline test above

---

- [x] 4. Implement agent conversation loop

  **What to do**:
  - Create `src/pykoclaw/agent.py` with:
    - `async def run_conversation(name: str, db: sqlite3.Connection, data_dir: Path) -> None`
    - Sets up conversation directory: `{data_dir}/conversations/{name}/`
    - Creates `CLAUDE.md` in conversation dir if not exists (empty)
    - Loads global `CLAUDE.md` from `{data_dir}/CLAUDE.md` if exists
    - Creates `ClaudeSDKClient` with `ClaudeAgentOptions`:
      - `cwd` = conversation directory
      - `permission_mode='bypassPermissions'`
      - `allowed_tools` = all built-in + `mcp__pykoclaw__*`
      - `setting_sources=['project']` (loads conversation's CLAUDE.md)
      - `system_prompt` = global CLAUDE.md content as a plain string (NOT the `claude_code` preset). The Claude Code preset injects a massive coding-focused system prompt. For a general-purpose assistant, just pass the global CLAUDE.md content directly as a string, or `None` if no global CLAUDE.md exists. The built-in tools (Bash, Read, etc.) work regardless of the system prompt.
      - `mcp_servers` = scheduler MCP server from `make_mcp_server()`
      - `model` = `os.environ.get("PYKOCLAW_MODEL", "claude-opus-4-6")`
      - `resume` = session_id from DB (if conversation exists)
    - REPL loop:
      1. Print prompt marker (e.g., `> `)
      2. Read user input from stdin (handle EOF for exit)
      3. Send to `client.query(user_input)`
      4. Stream response via `client.receive_response()`, print `TextBlock` content
      5. Capture session_id from `SystemMessage` (subtype `init`)
      6. Save session_id to DB via `upsert_conversation()`
      7. Repeat
  - Use findings from Task 0 to implement session resume correctly

  **Must NOT do**:
  - No fancy prompt (no readline, no prompt_toolkit)
  - No message formatting (no XML tags like nanoclaw)
  - No typing indicators
  - No cursor rollback or retry logic
  - No output marker parsing

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Core logic, async programming, SDK integration, needs careful session handling
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (after wave 2)
  - **Parallel Group**: Wave 3 (with Tasks 5, 6)
  - **Blocks**: Task 7
  - **Blocked By**: Tasks 0, 2, 3

  **References**:
  - `nanoclaw/container/agent-runner/src/index.ts:331-445` — runQuery function: how nanoclaw creates the SDK query with options, processes messages, extracts session_id from `system/init` message, handles result messages. Port the message processing loop pattern.
  - `nanoclaw/container/agent-runner/src/index.ts:447-531` — main function: the query loop pattern (run query → wait → run again). Adapt for CLI REPL (run query → read input → run again).
  - `nanoclaw/container/agent-runner/src/index.ts:374-411` — SDK options: `cwd`, `resume`, `systemPrompt` with append, `allowedTools`, `permissionMode`, `settingSources`, `mcpServers`. Port these options to Python `ClaudeAgentOptions`.
  - `nanoclaw/src/index.ts:304-381` — runAgent: how host prepares session_id, wraps onOutput to track new session_id, saves to DB. Port the session tracking pattern.
  - Task 0 findings — Session resume behavior documentation
  - Claude Agent SDK Python docs — `ClaudeSDKClient`, `receive_response()`, `AssistantMessage`, `TextBlock`, `SystemMessage`, `ResultMessage`

  **Acceptance Criteria**:

  ```
  Scenario: Conversation starts and responds
    Tool: Bash
    Preconditions: uv sync, ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN set
    Steps:
      1. echo 'Say exactly "PYKOCLAW_WORKS" and nothing else' | timeout 60 uv run pykoclaw chat test-conv
      2. Assert: exit code 0 (or 124 for timeout, either acceptable)
      3. Assert: stdout contains "PYKOCLAW_WORKS"
    Expected Result: Agent responds to prompt
    Evidence: Command stdout captured

  Scenario: Conversation directory created
    Tool: Bash
    Steps:
      1. ls ~/.local/share/pykoclaw/conversations/test-conv/
      2. Assert: directory exists
    Expected Result: Conversation dir created on first use
    Evidence: ls output captured

  Scenario: Session persists in DB
    Tool: Bash
    Steps:
      1. uv run python -c "
         from pykoclaw.db import init_db, get_conversation
         from pathlib import Path
         db = init_db(Path.home() / '.local' / 'share' / 'pykoclaw' / 'pykoclaw.db')
         c = get_conversation(db, 'test-conv')
         assert c is not None and c['session_id'], f'No session: {c}'
         print('SESSION_OK')
         "
      2. Assert: stdout contains "SESSION_OK"
    Expected Result: Session ID saved to DB
    Evidence: Command output captured
  ```

  **Commit**: YES
  - Message: `feat: implement agent conversation loop with session persistence`
  - Files: `src/pykoclaw/agent.py`
  - Pre-commit: `uv run python -c "import pykoclaw.agent; print('ok')"`

---

- [x] 5. Implement scheduler process

  **What to do**:
  - Create `src/pykoclaw/scheduler.py` with:
    - `async def run_scheduler(db: sqlite3.Connection, data_dir: Path) -> None`
    - Poll loop: every 60 seconds, query `get_due_tasks(db)`
    - For each due task:
      1. Create `ClaudeSDKClient` with same options as conversation loop but:
         - `cwd` = task's conversation directory
         - `resume` = None (isolated context) or conversation's session_id (group context, per `context_mode`)
         - Prompt = task's prompt text
      2. Run query, stream response to stdout (with `[task:{id}]` prefix)
      3. Calculate `next_run` based on schedule_type (cron → `croniter`, interval → `now + ms`, once → `None`)
      4. Call `update_task_after_run(db, task_id, next_run, result_summary)`
      5. Call `log_task_run(db, ...)`
    - Use `croniter` library for cron expression parsing (simpler than `cron-parser` in Python)
  - Update `pyproject.toml` to add `croniter` dependency if not already present

  **Must NOT do**:
  - No concurrency queue (run tasks serially)
  - No retry/backoff logic
  - No IPC — reads/writes same SQLite DB directly
  - No container spawning

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Straightforward async loop with SDK calls
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 4, 6)
  - **Blocks**: Task 7
  - **Blocked By**: Task 2

  **References**:
  - `nanoclaw/src/task-scheduler.ts:34-182` — runTask function: how nanoclaw runs a scheduled task. Gets group, creates container agent, processes output, calculates next_run (cron/interval/once), logs run. Port this logic directly.
  - `nanoclaw/src/task-scheduler.ts:184-222` — startSchedulerLoop: poll every SCHEDULER_POLL_INTERVAL, get due tasks, re-check status, enqueue. Port the poll loop pattern.
  - `nanoclaw/src/db.ts:373-415` — getDueTasks, updateTaskAfterRun, logTaskRun SQL queries. Reuse these queries.
  - `nanoclaw/src/types.ts:53-75` — ScheduledTask type with schedule_type enum ('cron' | 'interval' | 'once')
  - croniter docs: https://github.com/kiorky/croniter — Python cron expression parser

  **Acceptance Criteria**:

  ```
  Scenario: Scheduler starts and polls
    Tool: Bash
    Preconditions: uv sync completed
    Steps:
      1. timeout 5 uv run pykoclaw scheduler 2>&1 || true
      2. Assert: exit code 124 (timeout — scheduler was running)
      3. Assert: stdout or stderr contains "scheduler" or "polling" or similar start message
    Expected Result: Scheduler runs until killed
    Evidence: Command output captured

  Scenario: Scheduler picks up due task
    Tool: Bash
    Preconditions: ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN set
    Steps:
      1. uv run python -c "
         from pykoclaw.db import init_db, create_task, upsert_conversation
         from pathlib import Path
         data_dir = Path.home() / '.local' / 'share' / 'pykoclaw'
         db = init_db(data_dir / 'pykoclaw.db')
         upsert_conversation(db, 'sched-test', None, str(data_dir / 'conversations' / 'sched-test'))
         (data_dir / 'conversations' / 'sched-test').mkdir(parents=True, exist_ok=True)
         create_task(db, id='t-test', conversation='sched-test', prompt='Say SCHEDULER_OK', schedule_type='once', schedule_value='2020-01-01T00:00:00Z', next_run='2020-01-01T00:00:00Z')
         print('TASK_CREATED')
         "
      2. Assert: stdout contains "TASK_CREATED"
      3. timeout 120 uv run pykoclaw scheduler 2>&1 || true
      4. Check DB: task status should be 'completed' and task_run_logs should have an entry
    Expected Result: Task executes and logs run
    Evidence: DB state verified via python script
  ```

  **Commit**: YES
  - Message: `feat: implement scheduler process for timed task execution`
  - Files: `src/pykoclaw/scheduler.py`
  - Pre-commit: `uv run python -c "import pykoclaw.scheduler; print('ok')"`

---

- [x] 6. Implement CLAUDE.md memory hierarchy

  **What to do**:
  - Create `{data_dir}/CLAUDE.md` template on first run (brief instruction text)
  - Create `{data_dir}/conversations/{name}/CLAUDE.md` on conversation creation
  - In `agent.py`, load global CLAUDE.md and pass as `system_prompt` (plain string, NOT the `claude_code` preset). If no global CLAUDE.md exists, pass `system_prompt=None`.
  - Ensure `setting_sources=['project']` loads per-conversation CLAUDE.md from cwd
  - The agent can modify its own CLAUDE.md via Write tool (it runs in conversation cwd)

  **Must NOT do**:
  - No read-only restrictions (no main/non-main distinction)
  - No CLAUDE.md validation or schema enforcement

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Small file creation + option wiring
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 4, 5)
  - **Blocks**: Task 7
  - **Blocked By**: Task 1

  **References**:
  - `nanoclaw/docs/SPEC.md:266-286` — Memory hierarchy: global CLAUDE.md read by all, group CLAUDE.md per group. Port this concept.
  - `nanoclaw/container/agent-runner/src/index.ts:367-381` — How nanoclaw loads global CLAUDE.md: reads `/workspace/global/CLAUDE.md`, passes as `systemPrompt: { type: 'preset', preset: 'claude_code', append: globalClaudeMd }`. NOTE: nanoclaw uses the claude_code preset because it needs coding tools in container. pykoclaw should NOT use the preset — pass global CLAUDE.md as a plain string system_prompt instead.
  - `nanoclaw/groups/main/CLAUDE.md` and `nanoclaw/groups/global/CLAUDE.md` — Example CLAUDE.md content for reference
  - Claude Agent SDK Python docs — `SystemPromptPreset` with `append` field, `setting_sources`

  **Acceptance Criteria**:

  ```
  Scenario: CLAUDE.md files created for new conversation
    Tool: Bash
    Steps:
      1. echo 'quit' | timeout 10 uv run pykoclaw chat memory-test 2>/dev/null || true
      2. test -f ~/.local/share/pykoclaw/CLAUDE.md
      3. Assert: global CLAUDE.md exists
      4. test -f ~/.local/share/pykoclaw/conversations/memory-test/CLAUDE.md
      5. Assert: per-conversation CLAUDE.md exists
    Expected Result: Both CLAUDE.md files created
    Evidence: file existence checks
  ```

  **Commit**: YES (groups with Task 4 if convenient)
  - Message: `feat: implement CLAUDE.md memory hierarchy`
  - Files: modifications to `src/pykoclaw/agent.py`
  - Pre-commit: file existence check

---

- [x] 7. Wire CLI entrypoint with argparse

  **What to do**:
  - Update `src/pykoclaw/__main__.py`:
    - `argparse` with subcommands:
      - `chat <name>` — run conversation REPL (calls `run_conversation`)
      - `scheduler` — run scheduler loop (calls `run_scheduler`)
      - `conversations` — list all conversations from DB
      - `tasks` — list all scheduled tasks from DB
    - `main()` function: parse args, init DB, dispatch to subcommand
    - `asyncio.run()` for async subcommands
  - Wire all modules together: db, agent, scheduler, tools

  **Must NOT do**:
  - No click/typer dependency
  - No shell completion
  - No verbose/debug flags (use PYKOCLAW_LOG_LEVEL env var if needed)
  - No color output

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Wiring code, argparse boilerplate
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (sequential — needs all prior tasks)
  - **Blocks**: Task 8
  - **Blocked By**: Tasks 4, 5, 6

  **References**:
  - `nanoclaw/src/index.ts:1053-1074` — main() function: init DB, load state, setup shutdown handlers, connect. Port the init sequence (init_db, dispatch to subcommand).
  - `nanoclaw/src/config.ts` — Constants: ASSISTANT_NAME, POLL_INTERVAL, SCHEDULER_POLL_INTERVAL. Port as env vars or module-level constants.
  - AGENTS.md — `dedent()` for multi-line strings in help text

  **Acceptance Criteria**:

  ```
  Scenario: CLI help shows all subcommands
    Tool: Bash
    Steps:
      1. uv run pykoclaw --help
      2. Assert: exit code 0
      3. Assert: stdout contains "chat"
      4. Assert: stdout contains "scheduler"
      5. Assert: stdout contains "conversations"
      6. Assert: stdout contains "tasks"
    Expected Result: All subcommands listed
    Evidence: help output captured

  Scenario: conversations subcommand works
    Tool: Bash
    Steps:
      1. uv run pykoclaw conversations
      2. Assert: exit code 0
      3. Assert: stdout lists conversations (or empty table if none)
    Expected Result: Conversations listed from DB
    Evidence: Command output captured

  Scenario: tasks subcommand works
    Tool: Bash
    Steps:
      1. uv run pykoclaw tasks
      2. Assert: exit code 0
    Expected Result: Tasks listed from DB
    Evidence: Command output captured
  ```

  **Commit**: YES
  - Message: `feat: wire CLI entrypoint with argparse subcommands`
  - Files: `src/pykoclaw/__main__.py`
  - Pre-commit: `uv run pykoclaw --help`

---

- [x] 8. Add smoke tests

  **What to do**:
  - Create `tests/test_db.py`:
    - Test `init_db` creates tables
    - Test conversation CRUD (upsert, get, list)
    - Test task CRUD (create, get, update, delete, due tasks)
    - Test `log_task_run`
    - All tests use in-memory or temp SQLite DB
  - Create `tests/test_tools.py`:
    - Test `make_mcp_server` returns valid config
    - Test tool definitions have correct names and schemas
  - Run: `uv run pytest -x`

  **Must NOT do**:
  - No integration tests (would require API keys)
  - No mocking of claude-agent-sdk
  - No test fixtures beyond what's needed
  - No coverage requirements

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple unit tests for DB and tool definitions
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (after Task 7)
  - **Blocks**: None (final task)
  - **Blocked By**: Task 7

  **References**:
  - `src/pykoclaw/db.py` — Functions to test (from Task 2)
  - `src/pykoclaw/tools.py` — MCP server factory to test (from Task 3)
  - pytest docs for basic test patterns

  **Acceptance Criteria**:

  ```
  Scenario: All smoke tests pass
    Tool: Bash
    Preconditions: All prior tasks complete
    Steps:
      1. uv run pytest -x -v
      2. Assert: exit code 0
      3. Assert: output shows test count > 0
      4. Assert: output contains "passed"
    Expected Result: All tests pass
    Evidence: pytest output captured
  ```

  **Commit**: YES
  - Message: `test: add smoke tests for database and MCP tools`
  - Files: `tests/test_db.py`, `tests/test_tools.py`
  - Pre-commit: `uv run pytest -x`

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1 | `feat: create project skeleton with pyproject.toml and package structure` | pyproject.toml, src/pykoclaw/__init__.py, __main__.py, tests/__init__.py | `uv run pykoclaw --help` |
| 2 | `feat: implement SQLite database layer for conversations and tasks` | src/pykoclaw/db.py | inline python test |
| 3 | `feat: implement custom MCP tools for task scheduling` | src/pykoclaw/tools.py | inline python test |
| 4 | `feat: implement agent conversation loop with session persistence` | src/pykoclaw/agent.py | `echo test \| uv run pykoclaw chat test` |
| 5 | `feat: implement scheduler process for timed task execution` | src/pykoclaw/scheduler.py | import check |
| 6 | `feat: implement CLAUDE.md memory hierarchy` | src/pykoclaw/agent.py (update) | file existence check |
| 7 | `feat: wire CLI entrypoint with argparse subcommands` | src/pykoclaw/__main__.py | `uv run pykoclaw --help` |
| 8 | `test: add smoke tests for database and MCP tools` | tests/test_db.py, tests/test_tools.py | `uv run pytest -x` |

---

## Success Criteria

### Verification Commands
```bash
uv sync                                           # Expected: exit 0
uv run pykoclaw --help                            # Expected: shows chat, scheduler, conversations, tasks
uv run pykoclaw conversations                     # Expected: exit 0, lists conversations
uv run pykoclaw tasks                             # Expected: exit 0, lists tasks
echo 'Say HELLO' | timeout 60 uv run pykoclaw chat test  # Expected: output contains HELLO
timeout 5 uv run pykoclaw scheduler || test $? -eq 124   # Expected: ran until timeout
uv run pytest -x                                  # Expected: all tests pass
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All smoke tests pass
- [ ] Package installs cleanly with `uv sync`
- [ ] CLI works for all subcommands
- [ ] Conversations persist across restarts
- [ ] Scheduler picks up and executes due tasks
- [ ] CLAUDE.md files created and loaded
