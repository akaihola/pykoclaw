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
- **Web search** -- When `BRAVE_API_KEY` is configured, the `brave_search` MCP
  tool is automatically registered. It uses the [Brave Search API] to perform
  geo-unrestricted web searches. Claude Code's built-in `WebSearch` is US-only
  and returns empty results outside the US; `brave_search` is the intended
  replacement for international deployments.

## Installation

Install with [uv](https://docs.astral.sh/uv/):

```bash
# Core only
uv tool install pykoclaw@git+https://github.com/akaihola/pykoclaw.git

# With the interactive chat plugin
uv tool install pykoclaw@git+https://github.com/akaihola/pykoclaw.git \
    --with=pykoclaw-chat@git+https://github.com/akaihola/pykoclaw-chat.git

# With all currently published plugins
uv tool install pykoclaw@git+https://github.com/akaihola/pykoclaw.git \
    --with=pykoclaw-chat@git+https://github.com/akaihola/pykoclaw-chat.git \
    --with=pykoclaw-whatsapp@git+https://github.com/akaihola/pykoclaw-whatsapp.git \
    --with=pykoclaw-acp@git+https://github.com/akaihola/pykoclaw-acp.git \
    --with=pykoclaw-matrix@git+https://github.com/akaihola/pykoclaw-matrix.git \
    --with=pykoclaw-slack@git+https://github.com/akaihola/pykoclaw-slack.git \
    --with=pykoclaw-messaging@git+https://github.com/akaihola/pykoclaw-messaging.git
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
pykoclaw chat <name>        # Interactive chat (pykoclaw-chat plugin)
pykoclaw whatsapp run       # WhatsApp listener (pykoclaw-whatsapp plugin)
pykoclaw acp                # ACP server (pykoclaw-acp plugin)
pykoclaw matrix run         # Matrix listener (pykoclaw-matrix plugin)
pykoclaw slack run          # Slack Socket Mode listener (pykoclaw-slack plugin)
pykoclaw send matrix-...    # One-off channel dispatch (pykoclaw-messaging plugin)
```

## Configuration

Settings are read from environment variables with the `PYKOCLAW_` prefix.
`.env` files are loaded in this order (lowest → highest priority):

1. `~/.config/pykoclaw/.env` — global config (respects `XDG_CONFIG_HOME`)
2. `$PYKOCLAW_DATA/.env` — per-workspace override (only when `PYKOCLAW_DATA` env var is set)
3. CWD `.env`
4. Environment variables (always win)

| Variable                                        | Default                   | Description                                                       |
| ----------------------------------------------- | ------------------------- | ----------------------------------------------------------------- |
| `PYKOCLAW_DATA`                                 | `~/.local/share/pykoclaw` | Data directory (database, conversations, history)                 |
| `PYKOCLAW_MODEL`                                | `claude-opus-4-6`         | Claude model to use                                               |
| `PYKOCLAW_CLI_PATH`                             | *(bundled)*               | Path to Claude CLI binary (overrides bundled SDK)                 |
| `BRAVE_API_KEY` or `PYKOCLAW_BRAVE_API_KEY`     | *(unset)*                 | Brave Search API key — enables the `brave_search` MCP tool        |

## Data directory layout

```
~/.local/share/pykoclaw/
  pykoclaw.db                # SQLite database
  .env                       # Per-workspace overrides (loaded when PYKOCLAW_DATA points here)
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
| `transform_response(text, ctx)`     | Post-process agent text for a target channel       |

The `transform_response()` hook is used by plugins such as `pykoclaw-pykofinder`
to rewrite channel-visible output after the agent replies but before
channel-specific delivery. A typical use case is converting local Markdown file
links into Pykofinder viewer URLs like `/f/?path=%2Fabsolute%2Fpath%2Fnote.md`
for channels that cannot open host-local paths directly.

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

Task results are delivered to the workspace default destination when one is
configured. Set it with `set_task_result_destination` to route future task
results to a persistent Matrix/WhatsApp/etc. conversation. You can still use
`target_conversation` on individual tasks to override the default for that one
job.

### Delivery queue

After each task runs, the scheduler writes results to a `delivery_queue` table.
Channel plugins (WhatsApp, ACP, Matrix, Slack) poll this queue and deliver
messages through their native transports. This decouples the scheduler from
channel-specific send logic.

Run the scheduler as a long-lived process:

```bash
pykoclaw scheduler
```

## Plugins

| Package                                                              | Type           | Description                               |
| -------------------------------------------------------------------- | -------------- | ----------------------------------------- |
| [pykoclaw-chat](https://github.com/akaihola/pykoclaw-chat)           | Plugin         | Interactive terminal chat                 |
| [pykoclaw-whatsapp](https://github.com/akaihola/pykoclaw-whatsapp)   | Plugin         | WhatsApp integration                      |
| [pykoclaw-acp](https://github.com/akaihola/pykoclaw-acp)             | Plugin         | Agent Client Protocol (ACP) server        |
| [pykoclaw-matrix](https://github.com/akaihola/pykoclaw-matrix)       | Plugin         | Matrix/Element integration                |
| [pykoclaw-slack](https://github.com/akaihola/pykoclaw-slack)         | Plugin         | Slack Socket Mode gateway                 |
| [pykoclaw-messaging](https://github.com/akaihola/pykoclaw-messaging) | Plugin/library | Shared dispatch plus `pykoclaw send` CLI  |
| [pykoclaw-vision](https://github.com/akaihola/pykoclaw-vision)       | Library        | Shared Gemini image-analysis MCP tooling  |

[Brave Search API]: https://brave.com/search/api/
