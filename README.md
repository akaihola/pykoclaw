# pykoclaw

[![Built with Claude Code](https://img.shields.io/badge/Built_with-Claude_Code-6f42c1?logo=anthropic&logoColor=white)](https://claude.ai/code)

> This project is developed by an AI coding agent ([Claude Code](https://claude.ai/code)), with human oversight and direction.

A Python CLI AI agent framework built on the Claude Agent SDK. Provides an
extensible plugin architecture for running Claude-powered agent conversations,
with built-in task scheduling and conversation persistence.

## Features

- **Plugin system** -- Plugins are discovered automatically via Python entry
  points. Each plugin can register CLI commands, MCP tools, database migrations,
  and configuration.
- **Conversation persistence** -- Conversations are tracked in SQLite with
  session IDs, enabling resumption across process restarts.
- **Task scheduling** -- Schedule agent tasks using cron expressions, fixed
  intervals, or one-time timestamps. Tasks run in the background via a polling
  scheduler.
- **MCP tools** -- A built-in MCP server exposes task management tools
  (`schedule_task`, `list_tasks`, `pause_task`, `resume_task`, `cancel_task`) to
  the agent.

## Installation

Install with [uv](https://docs.astral.sh/uv/):

```bash
# Core only
uv tool install pykoclaw@git+https://github.com/akaihola/pykoclaw.git

# With the interactive chat plugin
uv tool install pykoclaw@git+https://github.com/akaihola/pykoclaw.git \
    --with=pykoclaw-chat@git+https://github.com/akaihola/pykoclaw-chat.git

# With both plugins
uv tool install pykoclaw@git+https://github.com/akaihola/pykoclaw.git \
    --with=pykoclaw-chat@git+https://github.com/akaihola/pykoclaw-chat.git \
    --with=pykoclaw-whatsapp@git+https://github.com/akaihola/pykoclaw-whatsapp.git
```

Or with `uv pip install` into an existing environment:

```bash
uv pip install pykoclaw@git+https://github.com/akaihola/pykoclaw.git
uv pip install pykoclaw-chat@git+https://github.com/akaihola/pykoclaw-chat.git
uv pip install pykoclaw-whatsapp@git+https://github.com/akaihola/pykoclaw-whatsapp.git
```

## Usage

```bash
pykoclaw                  # Show help
pykoclaw conversations    # List all conversations
pykoclaw tasks            # List all scheduled tasks
pykoclaw scheduler        # Run the background task scheduler
```

Plugins add their own subcommands (see their respective READMEs):

```bash
pykoclaw chat <name>      # Interactive chat (pykoclaw-chat plugin)
pykoclaw whatsapp run     # WhatsApp listener (pykoclaw-whatsapp plugin)
```

## Configuration

Settings are read from environment variables with the `PYKOCLAW_` prefix:

| Variable             | Default                   | Description                                       |
| -------------------- | ------------------------- | ------------------------------------------------- |
| `PYKOCLAW_DATA`      | `~/.local/share/pykoclaw` | Data directory (database, conversations, history) |
| `PYKOCLAW_MODEL`     | `claude-opus-4-6`         | Claude model to use                               |
| `PYKOCLAW_CLI_PATH`  | *(bundled)*               | Path to Claude CLI binary (overrides bundled SDK) |

## Data directory layout

```
~/.local/share/pykoclaw/
  pykoclaw.db                # SQLite database
  history                    # Readline history (shared across chat sessions)
  CLAUDE.md                  # Global system prompt (user-editable)
  conversations/
    <name>/                  # Per-conversation working directory
      CLAUDE.md              # Per-conversation instructions (user-editable)
```

## Plugin architecture

Plugins implement the `PykoClawPlugin` protocol (or extend `PykoClawPluginBase`)
and register via the `pykoclaw.plugins` entry point group:

```toml
# In the plugin's pyproject.toml
[project.entry-points."pykoclaw.plugins"]
myplugin = "my_package:MyPlugin"
```

The plugin interface:

| Method                              | Purpose                                            |
| ----------------------------------- | -------------------------------------------------- |
| `register_commands(group)`          | Add CLI commands to the `pykoclaw` group           |
| `get_mcp_servers(db, conversation)` | Return MCP server definitions for the agent        |
| `get_db_migrations()`               | Return SQL statements to run on startup            |
| `get_config_class()`                | Return a Pydantic Settings class for plugin config |
| `on_message(message)`               | Handle incoming messages                           |
| `on_startup()` / `on_shutdown()`    | Lifecycle hooks                                    |

## Scheduling

The agent can schedule tasks via the built-in MCP tools. Three schedule types
are supported:

| Type       | `schedule_value`   | Example                    |
| ---------- | ------------------ | -------------------------- |
| `cron`     | Cron expression    | `0 9 * * *` (daily at 9am) |
| `interval` | Milliseconds       | `3600000` (every hour)     |
| `once`     | ISO 8601 timestamp | `2025-03-01T12:00:00`      |

Tasks support two context modes:

- **`isolated`** -- Each run starts a fresh agent session.
- **`group`** -- Runs resume the conversation's existing session.

By default, task results are delivered back to the conversation that scheduled
them. Use the optional `target_conversation` parameter to route results to a
different channel (e.g., schedule from ACP, deliver to WhatsApp).

### Delivery queue

After each task runs, the scheduler writes results to a `delivery_queue` table.
Channel plugins (WhatsApp, ACP) poll this queue and deliver messages through
their native transports. This decouples the scheduler from channel-specific
send logic.

Run the scheduler as a long-lived process:

```bash
pykoclaw scheduler
```

## Plugins

| Package                                                              | Description                            |
| -------------------------------------------------------------------- | -------------------------------------- |
| [pykoclaw-chat](https://github.com/akaihola/pykoclaw-chat)           | Interactive terminal chat              |
| [pykoclaw-whatsapp](https://github.com/akaihola/pykoclaw-whatsapp)   | WhatsApp integration                   |
| [pykoclaw-acp](https://github.com/akaihola/pykoclaw-acp)             | Agent Client Protocol (ACP) server     |
| [pykoclaw-messaging](https://github.com/akaihola/pykoclaw-messaging) | Shared channel-agnostic dispatch       |
