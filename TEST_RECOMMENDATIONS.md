# Test Recommendations for PyKoclaw

## Current State

The project has 7 tests across 2 files (`test_db.py`, `test_tools.py`) covering
~160 lines. The database module has reasonable happy-path coverage, while the
tools module has only smoke tests. Three modules — `scheduler.py`, `agent.py`,
and `__main__.py` — have zero test coverage.

### What exists today

| Module | Source lines | Tests | Verdict |
|---|---|---|---|
| `db.py` | 212 | 5 tests — CRUD, due tasks, run logging | Good happy-path coverage |
| `tools.py` | 144 | 2 tests — server creation smoke tests | Superficial |
| `scheduler.py` | 115 | 0 | Not tested |
| `agent.py` | 74 | 0 | Not tested |
| `__main__.py` | 65 | 0 | Not tested |

### Structural issues

- The `db` fixture is duplicated in both test files instead of living in a
  shared `conftest.py`.
- No `conftest.py` exists at all — there are no shared fixtures, markers, or
  pytest configuration beyond `pyproject.toml`.
- No async test support is configured, despite `scheduler.py` and `agent.py`
  being entirely async.

---

## Recommendations — ordered by impact

### 1. Test the MCP tool functions end-to-end (HIGH impact, LOW effort)

**What:** The five tool functions in `tools.py` (`schedule_task`, `list_tasks`,
`pause_task`, `resume_task`, `cancel_task`) contain the core scheduling logic
(cron next-run calculation, interval arithmetic, status transitions). None of
this logic is currently tested.

**Why this is the highest priority:** These functions are where user intent
meets the database. A bug here silently creates wrong schedules, loses tasks, or
miscalculates next-run times. Because they are async but have no external
dependencies beyond an in-memory SQLite connection, they are straightforward to
test.

**Concrete tests to add:**

- `test_schedule_task_cron` — call `schedule_task` with `schedule_type="cron"`
  and a known expression, assert `next_run` is correct relative to "now".
- `test_schedule_task_interval` — same for `schedule_type="interval"`, assert
  `next_run ≈ now + interval_ms`.
- `test_schedule_task_once` — assert `next_run == schedule_value` verbatim.
- `test_list_tasks_empty` and `test_list_tasks_with_entries` — verify the
  formatted output.
- `test_pause_task` — create a task, pause it, verify status in DB.
- `test_resume_task_cron` / `test_resume_task_interval` /
  `test_resume_task_once` — resume a paused task for each schedule type, verify
  `next_run` recalculation and status flip to `"active"`.
- `test_resume_task_not_found` — assert the "not found" response for a
  nonexistent task ID.
- `test_cancel_task` — create then cancel, verify DB deletion.

**Setup required:** Add `pytest-asyncio` to dev dependencies, and use
`@pytest.mark.asyncio` on each test. The tool functions can be extracted from
the MCP server closure for direct invocation, or invoked through the MCP
server's `call_tool` handler.

---

### 2. Extract a `conftest.py` with shared fixtures (HIGH impact, LOW effort)

**What:** Create `tests/conftest.py` with:

```python
@pytest.fixture
def db(tmp_path):
    return init_db(tmp_path / "test.db")

@pytest.fixture
def db_with_conversation(db):
    upsert_conversation(db, "test", "sess-1", "/tmp/test")
    return db

@pytest.fixture
def db_with_task(db_with_conversation):
    create_task(
        db_with_conversation,
        id="t1", conversation="test", prompt="hello",
        schedule_type="once", schedule_value="2020-01-01T00:00:00Z",
        next_run="2020-01-01T00:00:00Z",
    )
    return db_with_conversation
```

**Why:** Every existing test manually creates a conversation + task. A fixture
chain removes this boilerplate, makes tests shorter, and makes it trivial to add
new tests that need a populated database. It also eliminates the current
duplication of the `db` fixture across files.

---

### 3. Add `update_task_after_run` tests to `test_db.py` (HIGH impact, LOW effort)

**What:** `update_task_after_run` (db.py:180-192) is called after every
scheduler execution. It has a `CASE WHEN ? IS NULL THEN 'completed' ELSE status
END` clause that sets status to `"completed"` when `next_run` is `None` (i.e.,
for one-shot tasks). This is completely untested.

**Tests to add:**

- `test_update_task_after_run_with_next_run` — pass a non-null `next_run`,
  assert `last_run` is set, `last_result` is stored, and status remains
  `"active"`.
- `test_update_task_after_run_without_next_run` — pass `next_run=None`, assert
  status flips to `"completed"`.

---

### 4. Test the scheduler's `run_task` with mocked Claude SDK (MEDIUM impact, MEDIUM effort)

**What:** `scheduler.py:run_task` orchestrates task execution: it reads the task
from the DB, runs a Claude agent, parses the response, recalculates `next_run`,
and logs the result. The Claude SDK interaction can be mocked, leaving the
scheduling logic and DB updates testable.

**Tests to add:**

- `test_run_task_cron_reschedules` — mock `ClaudeSDKClient` to return a canned
  response, run a cron task, assert `next_run` advances and a success log is
  written.
- `test_run_task_interval_reschedules` — same for interval tasks.
- `test_run_task_once_completes` — run a `"once"` task, assert `next_run`
  becomes `None` and status becomes `"completed"`.
- `test_run_task_error_handling` — mock the SDK to raise, assert an error log is
  written with the exception message and `next_run` is set to `None`.
- `test_run_task_group_context_reuses_session` — set `context_mode="group"` with
  an existing conversation session_id, assert the SDK is called with
  `resume=session_id`.
- `test_run_task_isolated_context` — set `context_mode="isolated"`, assert
  `resume=None`.

**Why:** This is where correctness matters most at runtime. A mocking approach
keeps tests fast and deterministic while covering the full task lifecycle.

---

### 5. Parametrize schedule-type branches (MEDIUM impact, LOW effort)

**What:** Both `tools.py` and `scheduler.py` contain a three-way
`if/elif/else` over `schedule_type` (`"cron"`, `"interval"`, `"once"`). This
branching logic is duplicated across `schedule_task`, `resume_task`, and
`run_task`. Parametrized tests naturally cover all three branches in a single
test definition.

**Example:**

```python
@pytest.mark.parametrize("schedule_type,schedule_value", [
    ("cron", "*/5 * * * *"),
    ("interval", "60000"),
    ("once", "2025-06-01T00:00:00Z"),
])
async def test_schedule_task_types(db_with_conversation, schedule_type, schedule_value):
    ...
```

**Why:** The `once` and `interval` paths in `resume_task` are particularly easy
to get wrong because the `else` branch just passes through `schedule_value`
directly — if someone later adds a fourth schedule type, the fallthrough would
silently mishandle it.

---

### 6. Test the CLI argument parsing and output formatting (MEDIUM impact, LOW effort)

**What:** `__main__.py` has four command branches. The `conversations` and
`tasks` subcommands do pure formatting — they query the DB and print. These are
testable without mocking the agent SDK.

**Tests to add:**

- `test_cli_conversations_output` — populate the DB, call `main()` with
  `["conversations"]` patched into `sys.argv`, capture stdout, assert expected
  format.
- `test_cli_tasks_output` — same for the `tasks` subcommand.
- `test_cli_no_command_shows_help` — assert help text is printed when no
  subcommand is given.

**Why:** CLI output is the user-facing contract. If the format changes
accidentally, these tests catch it.

---

### 7. Add edge-case and negative tests to the DB layer (MEDIUM impact, LOW effort)

**What:** The current DB tests only cover happy paths with simple data.

**Tests to add:**

- `test_upsert_conversation_updates_existing` — upsert twice with different
  `session_id`, assert the second value wins and `created_at` is unchanged.
- `test_get_conversation_not_found` — assert `None` for a nonexistent name.
- `test_update_task_no_matching_fields` — call `update_task` with an unknown
  keyword arg, assert it's a no-op (the function silently skips unrecognized
  keys).
- `test_get_due_tasks_excludes_paused` — create an active and a paused task,
  both past-due, assert only the active one is returned.
- `test_get_due_tasks_excludes_future` — create a task with a future `next_run`,
  assert it is not returned.
- `test_delete_task_cascades_run_logs` — create a task with run logs, delete the
  task, assert logs are also removed.
- `test_create_task_default_context_mode` — omit `context_mode`, assert it
  defaults to `"isolated"`.

---

### 8. Add `pytest-asyncio` and async test infrastructure (MEDIUM impact, LOW effort)

**What:** Add `pytest-asyncio` to dev dependencies in `pyproject.toml` and
configure it:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

**Why:** This is a prerequisite for recommendations 1 and 4. Without it, none of
the async tool functions or scheduler logic can be tested. With `asyncio_mode =
"auto"`, any `async def test_*` function is automatically recognized — no
per-test markers needed.

---

### 9. Test the `_data_dir` helper (LOW impact, LOW effort)

**What:** `db._data_dir()` reads `PYKOCLAW_DATA` from the environment and falls
back to `~/.local/share/pykoclaw`. The same logic is duplicated in
`__main__.py:32-34`.

**Tests to add:**

- `test_data_dir_from_env` — set `PYKOCLAW_DATA`, assert the returned path
  matches.
- `test_data_dir_default` — unset `PYKOCLAW_DATA`, assert the fallback path.

**Why secondary:** A bug here would be noticed immediately at startup, so the
risk is low. But the test is trivial to write and documents the contract.

---

### 10. Agent module: limited testability, defer to integration tests (LOW priority for now)

**What:** `agent.py:run_conversation` is a tight loop over `input()` and Claude
SDK streaming. Unit-testing it requires mocking `input`, `ClaudeSDKClient`, file
I/O, and `print` — the test would mostly be testing mocks.

**Recommendation:** Defer to manual or integration-level testing for now. If the
agent grows more complex (e.g., conversation branching, retry logic, error
recovery), extract testable helper functions and test those.

One small extraction that would be immediately testable:

- Factor the system-prompt loading logic (lines 22-31) into a standalone
  function `load_system_prompt(data_dir, name) -> str | None`. This is pure file
  I/O with simple logic, and easy to test with `tmp_path`.

---

## Summary: prioritized implementation order

| Priority | Recommendation | Effort | New tests |
|---|---|---|---|
| 1 | MCP tool functions end-to-end | Low | ~10 |
| 2 | `conftest.py` with shared fixtures | Low | 0 (enables others) |
| 3 | `update_task_after_run` tests | Low | 2 |
| 4 | Scheduler `run_task` with mocked SDK | Medium | ~6 |
| 5 | Parametrize schedule-type branches | Low | ~3 |
| 6 | CLI argument parsing and output | Low | ~3 |
| 7 | DB edge cases and negative tests | Low | ~7 |
| 8 | `pytest-asyncio` infrastructure | Low | 0 (prerequisite) |
| 9 | `_data_dir` helper | Low | 2 |
| 10 | Agent module extraction | Low | 1-2 |

Implementing recommendations 1-3 and 8 alone would roughly triple the test
count and cover the most critical untested logic (schedule calculation, status
transitions, and task-after-run behavior). Recommendations 4-7 would bring
comprehensive coverage to the scheduler and CLI, rounding out the suite.
