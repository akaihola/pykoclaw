#!/usr/bin/env bash
# Creates GitHub issues for pykoclaw test coverage improvements.
# Requires: gh CLI authenticated (gh auth login)
# Usage: bash create-test-issues.sh

set -euo pipefail

REPO="akaihola/pykoclaw"

echo "Creating test coverage improvement issues for $REPO..."

# Issue 1: tools.py handler tests
gh issue create --repo "$REPO" \
  --title "Add tests for MCP tool handler functions in tools.py" \
  --label "testing" \
  --body "$(cat <<'EOF'
## Context

`tools.py` is at 34% coverage. The `make_mcp_server()` return structure is tested, but none of the 5 async tool handler functions are invoked in tests. These handlers contain real business logic (schedule calculation, DB mutations, formatting) and are the highest-value test targets in the codebase.

## Current state

- `make_mcp_server()` returns a dict with `name` and `instance` keys — tested ✓
- `schedule_task()` (lines 32-56) — **untested**
- `list_tasks()` (lines 71-81) — **untested**
- `pause_task()` (lines 89-90) — **untested**
- `resume_task()` (lines 100-121) — **untested**
- `cancel_task()` (lines 136-137) — **untested**

## Implementation plan

Create `tests/test_tool_handlers.py`. The tool handlers are defined as inner async functions inside `make_mcp_server()`, so the simplest approach is to call them through the MCP server's request handling, or to refactor them into standalone testable functions.

**Approach A (no refactor):** Use the MCP `Server` instance from `make_mcp_server()` to invoke tools via `call_tool` requests programmatically. Each tool takes an `args` dict and returns a dict with `content` list.

**Approach B (light refactor):** Extract the handler logic into module-level async functions that accept `(db, conversation, args)` and test those directly. `make_mcp_server()` would just wire them up as MCP tools.

### Test cases to write

**`schedule_task`:**
1. Schedule with `schedule_type="cron"`, `schedule_value="*/5 * * * *"` — verify task created in DB with a future `next_run`
2. Schedule with `schedule_type="interval"`, `schedule_value="60000"` — verify `next_run` is ~60s in the future
3. Schedule with `schedule_type="once"`, `schedule_value="2030-01-01T00:00:00Z"` — verify `next_run` matches the value
4. Verify the returned content text includes the task ID and next run time

**`list_tasks`:**
1. Call with no tasks — verify response is `"No tasks scheduled."`
2. Create 2-3 tasks, call `list_tasks` — verify all task IDs appear in output
3. Verify long prompts are truncated to 50 chars in the listing

**`pause_task`:**
1. Create an active task, pause it — verify DB status is `"paused"`
2. Verify response text confirms the pause

**`resume_task`:**
1. Create and pause a task with `schedule_type="cron"`, resume it — verify status is `"active"` and `next_run` is recalculated to a future time
2. Create and pause a task with `schedule_type="interval"`, resume it — verify `next_run` is recalculated
3. Resume a non-existent task ID — verify `"not found"` response

**`cancel_task`:**
1. Create a task with logged runs, cancel it — verify both `scheduled_tasks` and `task_run_logs` rows are deleted
2. Verify response text confirms cancellation

### Test fixture

Use the existing `db` fixture pattern (or the shared one from the conftest issue):

```python
@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    db = init_db(tmp_path / "test.db")
    upsert_conversation(db, "test-conv", "sess-1", "/tmp/test")
    return db
```

## Acceptance criteria

- [ ] All 5 tool handlers have at least one test each
- [ ] Edge cases (empty lists, missing tasks, different schedule types) are covered
- [ ] `tools.py` coverage reaches ≥90%
EOF
)"

echo "  ✓ Issue 1: tools.py handlers"

# Issue 2: db.py remaining gaps
gh issue create --repo "$REPO" \
  --title "Cover remaining gaps in db.py tests" \
  --label "testing" \
  --body "$(cat <<'EOF'
## Context

`db.py` is the best-tested module at 92% coverage, but a few functions and edge-case paths are untested. These are easy wins to close out.

## Uncovered lines

| Lines | Function | What's missing |
|---|---|---|
| 9 | `_data_dir()` | Never called in tests |
| 154 | `update_task()` | Early return when no recognized keys in `updates` |
| 183-192 | `update_task_after_run()` | Entirely untested |

## Test cases to add in `tests/test_db.py`

### `_data_dir()`
1. With `PYKOCLAW_DATA` env var set — verify returns `Path(value)`
2. Without env var — verify returns `~/.local/share/pykoclaw`
3. Use `monkeypatch.setenv` / `monkeypatch.delenv` for isolation

### `update_task()` early return
1. Call `update_task(db, "t1", unknown_field="value")` — verify no DB changes, no error raised
2. Call `update_task(db, "t1")` with no keyword args — verify same

### `update_task_after_run()`
1. Create a task, call `update_task_after_run(db, "t1", next_run="2030-01-01T00:00:00Z", last_result="done")` — verify `next_run`, `last_run`, `last_result` are set and `status` remains `"active"`
2. Call with `next_run=None` — verify `status` becomes `"completed"`
3. Verify `last_run` is set to approximately "now" (UTC)

### `upsert_conversation()` conflict path
1. Insert a conversation, then upsert with the same name but different `session_id` and `cwd` — verify the row is updated (not duplicated)
2. Verify `list_conversations` still returns exactly 1 row

### `get_due_tasks()` filtering
1. Create tasks with different statuses (`active`, `paused`) and `next_run` times (past, future, NULL) — verify only active tasks with past `next_run` are returned
2. Specifically: a paused task with past `next_run` should NOT appear

## Acceptance criteria

- [ ] `_data_dir()`, `update_task_after_run()`, and `update_task()` early return are all tested
- [ ] `upsert_conversation` update-on-conflict path is tested
- [ ] `get_due_tasks` edge cases (paused tasks, future tasks) are tested
- [ ] `db.py` coverage reaches 100%
EOF
)"

echo "  ✓ Issue 2: db.py gaps"

# Issue 3: __main__.py CLI tests
gh issue create --repo "$REPO" \
  --title "Add tests for CLI argument parsing and subcommands in __main__.py" \
  --label "testing" \
  --body "$(cat <<'EOF'
## Context

`__main__.py` is at 0% coverage. It contains the CLI entry point with argparse subcommands (`chat`, `scheduler`, `conversations`, `tasks`) and output formatting logic. The `chat` and `scheduler` commands launch async processes that need mocking, but argument parsing and the list-display commands are straightforward to test.

## Module overview (`src/pykoclaw/__main__.py`)

```
main()
├── argparse setup (4 subcommands)
├── data_dir resolution (PYKOCLAW_DATA env var or default)
├── init_db()
├── command dispatch:
│   ├── "chat" → asyncio.run(run_conversation(...))
│   ├── "scheduler" → asyncio.run(run_scheduler(...))
│   ├── "conversations" → list_conversations() + print
│   ├── "tasks" → get_all_tasks() + print
│   └── default → parser.print_help()
```

## Implementation plan

Create `tests/test_main.py`.

### Test cases

**Argument parsing:**
1. `["chat", "myconv"]` — verify `args.command == "chat"` and `args.name == "myconv"`
2. `["scheduler"]` — verify `args.command == "scheduler"`
3. `["conversations"]` — verify `args.command == "conversations"`
4. `["tasks"]` — verify `args.command == "tasks"`
5. `[]` (no args) — verify `args.command is None`

**Data directory resolution:**
1. With `PYKOCLAW_DATA=/custom/path` — verify `data_dir == Path("/custom/path")`
2. Without env var — verify falls back to `~/.local/share/pykoclaw`

**`conversations` subcommand output:**
1. Mock `list_conversations` to return 2 sample dicts
2. Call `main()` with `sys.argv = ["pykoclaw", "conversations"]`
3. Capture stdout and verify the `name | session_id | created_at` format

**`tasks` subcommand output:**
1. Mock `get_all_tasks` to return sample tasks (include one with a prompt >50 chars)
2. Call `main()` with `sys.argv = ["pykoclaw", "tasks"]`
3. Capture stdout and verify `id | conversation | prompt_preview | status | next_run` format
4. Verify long prompts are truncated to 50 chars

**`chat` subcommand dispatch:**
1. Mock `asyncio.run` and `run_conversation`
2. Call `main()` with `sys.argv = ["pykoclaw", "chat", "test"]`
3. Verify `run_conversation` was called with `("test", db, data_dir)`

**`scheduler` subcommand dispatch:**
1. Mock `asyncio.run` and `run_scheduler`
2. Call `main()` with `sys.argv = ["pykoclaw", "scheduler"]`
3. Verify `run_scheduler` was called with `(db, data_dir)`

**No-command case:**
1. Mock `parser.print_help`
2. Call `main()` with no args
3. Verify `print_help` was called

### Mocking approach

```python
from unittest.mock import patch, MagicMock

@patch("pykoclaw.__main__.run_conversation")
@patch("pykoclaw.__main__.init_db")
def test_chat_dispatch(mock_init_db, mock_run_conv, tmp_path):
    mock_init_db.return_value = MagicMock()
    with patch("sys.argv", ["pykoclaw", "chat", "myconv"]):
        with patch.dict(os.environ, {"PYKOCLAW_DATA": str(tmp_path)}):
            main()
    mock_run_conv.assert_called_once()
```

## Acceptance criteria

- [ ] Argument parsing for all 4 subcommands is tested
- [ ] Output formatting for `conversations` and `tasks` is tested with captured stdout
- [ ] `chat` and `scheduler` dispatch are tested via mocks (no real SDK calls)
- [ ] `PYKOCLAW_DATA` env var is tested
- [ ] `__main__.py` coverage reaches ≥80%
EOF
)"

echo "  ✓ Issue 3: __main__.py CLI"

# Issue 4: scheduler.py tests
gh issue create --repo "$REPO" \
  --title "Add tests for scheduler.py (run_task and run_scheduler)" \
  --label "testing" \
  --body "$(cat <<'EOF'
## Context

`scheduler.py` is at 0% coverage. It contains two async functions with significant logic: `run_task()` (execute a single scheduled task via Claude SDK) and `run_scheduler()` (polling loop). The SDK client must be mocked, but the surrounding logic (next-run calculation, error handling, DB updates, logging) is all testable.

## Module overview (`src/pykoclaw/scheduler.py`)

```
run_task(task, db, data_dir)
├── Resolve conversation directory
├── Determine session_id based on context_mode ("group" vs "isolated")
├── Create ClaudeAgentOptions and ClaudeSDKClient
├── Send prompt and collect response text
├── Calculate next_run based on schedule_type (cron/interval/once)
├── On exception: capture error, set next_run=None
├── Always: call update_task_after_run() and log_task_run()

run_scheduler(db, data_dir)
├── Loop forever:
│   ├── get_due_tasks()
│   ├── For each: run_task()
│   └── asyncio.sleep(60)
```

## Implementation plan

Create `tests/test_scheduler.py`. All tests should use `pytest-asyncio` (or `asyncio.run()` in sync tests) and mock the Claude SDK client.

### Mocking strategy

```python
from unittest.mock import AsyncMock, patch, MagicMock

def mock_sdk_client(response_text="Task completed"):
    """Create a mock ClaudeSDKClient context manager."""
    client = AsyncMock()

    # Mock receive_response to yield an AssistantMessage with a TextBlock
    text_block = MagicMock()
    text_block.text = response_text
    type(text_block).__class__ = type("TextBlock", (), {})

    message = MagicMock()
    message.content = [text_block]

    async def fake_receive():
        yield message

    client.receive_response = fake_receive
    client.query = AsyncMock()

    return client
```

### Test cases for `run_task()`

**Happy path — cron schedule:**
1. Create a task with `schedule_type="cron"`, `schedule_value="*/5 * * * *"`
2. Mock `ClaudeSDKClient` to return a text response
3. Call `await run_task(task_dict, db, data_dir)`
4. Verify `update_task_after_run` was called with a future `next_run`
5. Verify `log_task_run` was called with `status="success"` and non-None `result`

**Happy path — interval schedule:**
1. Same as above with `schedule_type="interval"`, `schedule_value="60000"`
2. Verify `next_run` is ~60 seconds in the future

**Happy path — one-time schedule:**
1. Same with `schedule_type="once"`
2. Verify `next_run=None` (task completes, doesn't reschedule)

**Context mode "group":**
1. Create a conversation with a `session_id`, create a task with `context_mode="group"`
2. Verify `ClaudeAgentOptions` is constructed with `resume=session_id`

**Context mode "isolated":**
1. Same but with `context_mode="isolated"`
2. Verify `resume=None`

**Error handling:**
1. Mock `ClaudeSDKClient` to raise an exception
2. Verify `update_task_after_run` is called with `next_run=None` and error in `last_result`
3. Verify `log_task_run` is called with `status="error"` and `error` set

**Result truncation:**
1. Mock SDK to return a >200 char response
2. Verify `update_task_after_run` receives `result_summary` truncated to 200 chars

### Test cases for `run_scheduler()`

1. Mock `get_due_tasks` to return 2 tasks on first call, 0 on second call
2. Mock `run_task` as an `AsyncMock`
3. Mock `asyncio.sleep` to raise `StopIteration` (or similar) on the second call to break the loop
4. Verify `run_task` was called twice with the correct task dicts

## Acceptance criteria

- [ ] `run_task()` is tested for cron, interval, and one-time schedules
- [ ] Both context modes ("group" and "isolated") are tested
- [ ] Error handling path is tested
- [ ] `run_scheduler()` loop logic is tested
- [ ] `scheduler.py` coverage reaches ≥80%
EOF
)"

echo "  ✓ Issue 4: scheduler.py"

# Issue 5: agent.py tests
gh issue create --repo "$REPO" \
  --title "Add tests for agent.py conversation setup and input loop" \
  --label "testing" \
  --body "$(cat <<'EOF'
## Context

`agent.py` is at 0% coverage. It contains `run_conversation()`, an async function that sets up CLAUDE.md files, constructs SDK options, and runs an interactive input loop. The SDK client must be mocked, but the setup logic and message handling are testable.

## Module overview (`src/pykoclaw/agent.py`)

```
run_conversation(name, db, data_dir)
├── Create conversation directory: data_dir/conversations/{name}/
├── Create/read global CLAUDE.md at data_dir/CLAUDE.md
├── Create conversation CLAUDE.md at conv_dir/CLAUDE.md
├── Read global CLAUDE.md content → system_prompt (or None if empty)
├── Construct ClaudeAgentOptions with tools, model, MCP server
├── Enter input loop:
│   ├── Print prompt "> "
│   ├── Read user input (break on EOFError)
│   ├── Skip empty input
│   ├── client.query(user_input)
│   ├── Iterate client.receive_response():
│   │   ├── AssistantMessage → print TextBlock text
│   │   └── ResultMessage → upsert_conversation(db, name, session_id, cwd)
│   └── Print newline
```

## Implementation plan

Create `tests/test_agent.py`.

### Test cases

**Directory and file setup:**
1. Call `run_conversation` with a fresh `data_dir` — verify `data_dir/conversations/{name}/` is created
2. Verify `data_dir/CLAUDE.md` is created if it doesn't exist
3. Verify `data_dir/conversations/{name}/CLAUDE.md` is created if it doesn't exist
4. If `data_dir/CLAUDE.md` already has content, verify it's used as `system_prompt`
5. If `data_dir/CLAUDE.md` is empty, verify `system_prompt` is `None`

**ClaudeAgentOptions construction:**
1. Mock `ClaudeSDKClient` and capture the `ClaudeAgentOptions` passed to it
2. Verify `cwd` is set to the conversation directory
3. Verify `mcp_servers` contains a `"pykoclaw"` key
4. Verify `allowed_tools` list matches expected tools
5. Verify `PYKOCLAW_MODEL` env var is used when set

**Input loop:**
1. Mock `input()` to return `"hello"` then raise `EOFError`
2. Verify `client.query("hello")` was called
3. Verify the loop exits cleanly on `EOFError`

**Empty input handling:**
1. Mock `input()` to return `""` then `"real input"` then `EOFError`
2. Verify `client.query` was called exactly once (empty input skipped)

**Message handling:**
1. Mock `receive_response` to yield an `AssistantMessage` with `TextBlock`
2. Capture stdout — verify the text was printed

**ResultMessage handling:**
1. Mock `receive_response` to yield a `ResultMessage` with a `session_id`
2. Verify `upsert_conversation(db, name, session_id, cwd)` was called

### Mocking approach

```python
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.query = AsyncMock()

    async def empty_response():
        return
        yield  # make it an async generator

    client.receive_response = empty_response
    return client

@pytest.mark.asyncio
async def test_conversation_setup(tmp_path, db, mock_client):
    data_dir = tmp_path / "data"
    with patch("pykoclaw.agent.ClaudeSDKClient") as MockSDK:
        MockSDK.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockSDK.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("builtins.input", side_effect=EOFError):
            await run_conversation("test", db, data_dir)

    assert (data_dir / "conversations" / "test").is_dir()
    assert (data_dir / "CLAUDE.md").exists()
```

## Dependencies

- `pytest-asyncio` (add to dev dependencies)

## Acceptance criteria

- [ ] Directory/file creation logic is tested
- [ ] `ClaudeAgentOptions` construction is verified (including env var override)
- [ ] Input loop handles empty input and EOFError correctly
- [ ] AssistantMessage and ResultMessage processing are both tested
- [ ] `agent.py` coverage reaches ≥70%
EOF
)"

echo "  ✓ Issue 5: agent.py"

# Issue 6: Test infrastructure
gh issue create --repo "$REPO" \
  --title "Improve test infrastructure: shared conftest, coverage config, pytest-asyncio" \
  --label "testing" \
  --body "$(cat <<'EOF'
## Context

The test suite lacks shared infrastructure, which leads to duplication and makes it harder to maintain tests as the project grows. This issue covers structural improvements that support all the other test-coverage issues.

## Changes

### 1. Create shared `tests/conftest.py`

The `db` fixture is duplicated in `test_db.py` and `test_tools.py`. Extract it into a shared conftest:

```python
# tests/conftest.py
import sqlite3
from pathlib import Path

import pytest

from pykoclaw.db import init_db, upsert_conversation


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh test database."""
    return init_db(tmp_path / "test.db")


@pytest.fixture
def db_with_conversation(db: sqlite3.Connection) -> sqlite3.Connection:
    """Test database with a sample conversation pre-created."""
    upsert_conversation(db, "test-conv", "sess-1", "/tmp/test")
    return db
```

Then remove the `db` fixtures from `test_db.py` and `test_tools.py`.

### 2. Add `pytest-cov` and `pytest-asyncio` to dev dependencies

Update `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "pytest-asyncio"]
```

### 3. Add pytest configuration in `pyproject.toml`

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.coverage.run]
source = ["pykoclaw"]

[tool.coverage.report]
show_missing = true
fail_under = 60
```

### 4. Remove duplicate fixtures from existing test files

- `tests/test_db.py`: Remove the `db` fixture (lines 22-24), keep all tests
- `tests/test_tools.py`: Remove the `db` fixture (lines 11-12), keep all tests

## Acceptance criteria

- [ ] `tests/conftest.py` exists with shared `db` and `db_with_conversation` fixtures
- [ ] Duplicate `db` fixtures removed from `test_db.py` and `test_tools.py`
- [ ] `pytest-cov` and `pytest-asyncio` added to dev dependencies
- [ ] `[tool.pytest.ini_options]` and `[tool.coverage.*]` sections added to `pyproject.toml`
- [ ] All existing tests still pass after the refactor
- [ ] `pytest --cov` works without extra CLI flags
EOF
)"

echo "  ✓ Issue 6: test infrastructure"

echo ""
echo "All 6 issues created successfully!"
