# Draft: pykoclaw - Python Reimplementation of nanoclaw

## Requirements (confirmed)
- Reimplement nanoclaw (Node.js WhatsApp AI agent) in Python as `pykoclaw`
- Use `simonw/llm` from GitHub as LLM client library
- Minimize code: no extra comments, no exception handling, no defensive coding
- Favor functions over classes
- Idiomatic Python
- Proper Python package with `pyproject.toml` using `uv_build` as build system
- Create env with `uv sync`, run with `uv run`

## What nanoclaw Does (core flow)
1. **WhatsApp connection** via baileys library - receives/sends messages
2. **SQLite database** stores messages, groups, sessions, tasks, router state
3. **Message polling loop** - polls DB every 2s for new messages in registered groups
4. **Trigger matching** - messages must start with `@AssistantName`
5. **Conversation catch-up** - fetches all messages since last agent interaction
6. **Agent execution** - spawns Claude Agent SDK in Apple Container (Linux VM)
7. **IPC system** - file-based communication between host and containers
8. **Session management** - persistent conversation sessions per group
9. **Scheduled tasks** - cron/interval/once tasks that run as full agents
10. **Per-group memory** - CLAUDE.md hierarchy (global/group/files)

## Key Architectural Components
- `index.ts` - Main: WhatsApp connection, message routing, IPC watcher
- `db.ts` - SQLite operations (messages, groups, sessions, tasks, state)
- `config.ts` - Constants, trigger pattern, paths
- `container-runner.ts` - Spawns Apple Container with volume mounts
- `task-scheduler.ts` - Runs scheduled tasks when due
- `group-queue.ts` - Per-group queue with global concurrency limit
- `agent-runner/index.ts` - Runs INSIDE container, uses Claude Agent SDK

## Technical Decisions (FINAL)
- **Agent SDK**: `claude-agent-sdk` (Python) — replaces both simonw/llm AND custom tool implementations
- **I/O**: CLI stdin/stdout — no WhatsApp
- **Execution**: Direct, no containers — SDK tools run in host process
- **Database**: SQLite via Python stdlib `sqlite3`
- **Build system**: `uv_build` in pyproject.toml
- **Scheduler tools**: Custom MCP server via `@tool` decorator + `create_sdk_mcp_server()`
- **Sessions**: `ClaudeSDKClient` for conversation continuity, `resume` for cross-restart persistence
- **Default model**: claude-opus-4-6
- **Groups**: Named conversations, each with own cwd and CLAUDE.md

## Open Questions
1. Which Python WhatsApp library? Options:
   - `neonize` (Go-based WhatsApp library with Python bindings)
   - `whatsapp-web.js` doesn't have Python equivalent
   - `yowsup` (old, possibly unmaintained)
   - `python-whatsapp` (Twilio-based, different approach)
   - **Do we even need WhatsApp?** Or is the core just the agent loop?
2. Container execution: Do we need Apple Container support? Or subprocess?
3. Should we use `llm` CLI tool or library API?
4. How does `llm` handle conversations/sessions?
5. What's the scope? Full feature parity or minimal working agent?

## Research Findings: simonw/llm Library

### Core Python API
- `llm.get_model("claude-sonnet-4.5")` → get model
- `model.prompt("text")` → single prompt, returns Response (iterable for streaming)
- `model.conversation()` → creates Conversation with maintained history
- `conversation.prompt("text")` → prompt within conversation
- `model.chain("text", tools=[fn])` → auto-executes tools and continues
- `response.text()` → full response text
- Streaming: `for chunk in response: print(chunk)`

### Conversations
- `model.conversation()` creates a Conversation object
- Maintains full history across `.prompt()` calls
- Supports system prompts, tools, attachments
- No built-in persistence/resume across process restarts

### Claude Support
- Plugin: `llm-anthropic` (install via `llm install llm-anthropic` or as pip dep)
- Models: claude-opus-4.5, claude-sonnet-4.5, claude-haiku-4.5, claude-3.5-sonnet, etc.
- Auth: `ANTHROPIC_API_KEY` env var or `llm keys set anthropic`

### Tool/Function Calling
- Define tools as plain functions with type hints + docstrings
- `model.prompt("text", tools=[fn1, fn2])` 
- `model.chain("text", tools=[fn])` for automatic tool execution loop
- `llm.Toolbox` class for stateful tool groups
- `response.tool_calls()` and `response.execute_tool_calls()` for manual control

### Key Insight
- `llm` is a pure LLM client library, NOT an agent SDK
- It handles prompt → response, conversation history, tool calling
- It does NOT handle: file operations, bash execution, web browsing
- Agent capabilities (bash, file R/W, web) must be implemented as tools

## User Decisions (Round 1)
- **I/O Transport**: CLI (stdin/stdout) — terminal-based chat loop, no WhatsApp
- **Execution Model**: Direct (no isolation) — tools run in host process
- **Feature Scope**: Full feature parity — groups, scheduler, sessions, IPC, but adapted for CLI

## User Decisions (Round 2)
- **Groups**: Named conversations — switchable via CLI command, each with own memory/cwd
- **Tools**: All (bash, file R/W, web, scheduler). User asks about reusing Claude Agent SDK tools
- **Session Persistence**: llm's built-in SQLite logs DB
- **Default Model**: claude-opus-4-6

## User Decisions (Round 3)
- **Scheduler**: Separate process (`pykoclaw scheduler`) — runs independently
- **LLM Plugin**: Direct dependency — `llm-anthropic` in pyproject.toml

## MAJOR DISCOVERY: Claude Agent SDK for Python
- `pip install claude-agent-sdk` — direct Python equivalent of Node.js SDK
- Provides ClaudeSDKClient with session continuity, built-in tools, MCP support
- Built-in tools: Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch
- Custom tools via @tool decorator — can implement scheduler MCP tools
- Session resume via `resume` parameter
- Permission bypass mode like nanoclaw
- CLAUDE.md loading via setting_sources=["project"]
- This is a MUCH better fit than simonw/llm for this project
- **PENDING USER DECISION**: Use claude-agent-sdk instead of simonw/llm?

## Scope Boundaries
- INCLUDE: named conversations/groups, per-group memory (CLAUDE.md), scheduler (cron/interval/once), sessions via llm SQLite, agent tools (bash, file, web, scheduler), CLI I/O
- EXCLUDE: WhatsApp, Apple Container, Docker, container isolation, IPC
- ADAPT: container runner → direct llm calls; WhatsApp I/O → CLI stdin/stdout; groups → named conversations
