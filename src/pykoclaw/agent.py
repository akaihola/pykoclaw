import atexit
import re
import readline
import sqlite3
from pathlib import Path

import click
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from pykoclaw.config import settings
from pykoclaw.db import upsert_conversation
from pykoclaw.tools import make_mcp_server


def _setup_readline(history_path: Path) -> None:
    """Configure readline with persistent history."""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        readline.read_history_file(history_path)
    except FileNotFoundError:
        pass
    readline.set_history_length(1000)
    atexit.register(readline.write_history_file, str(history_path))


def _readline_prompt(styled: str) -> str:
    """Wrap ANSI escapes with readline markers so prompt width is correct."""
    return re.sub(r"\x1b\[[0-9;]*m", lambda m: f"\x01{m.group()}\x02", styled)


async def run_conversation(name: str, db: sqlite3.Connection, data_dir: Path) -> None:
    conv_dir = data_dir / "conversations" / name
    conv_dir.mkdir(parents=True, exist_ok=True)

    _setup_readline(data_dir / "history")

    global_claude_md = data_dir / "CLAUDE.md"
    if not global_claude_md.exists():
        global_claude_md.touch()

    conv_claude_md = conv_dir / "CLAUDE.md"
    if not conv_claude_md.exists():
        conv_claude_md.touch()

    global_content = global_claude_md.read_text().strip()
    system_prompt = global_content if global_content else None

    options = ClaudeAgentOptions(
        cwd=str(conv_dir),
        permission_mode="bypassPermissions",
        mcp_servers={"pykoclaw": make_mcp_server(db, name)},
        model=settings.model,
        allowed_tools=[
            "Bash",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "WebSearch",
            "WebFetch",
            "mcp__pykoclaw__*",
        ],
        setting_sources=["project"],
        system_prompt=system_prompt,
    )

    prompt = _readline_prompt(click.style("> ", fg="green", bold=True))

    async with ClaudeSDKClient(options) as client:
        while True:
            try:
                user_input = input(prompt)
            except (EOFError, KeyboardInterrupt):
                click.echo()
                break

            if not user_input:
                continue

            await client.query(user_input)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            click.echo(click.style(block.text, fg="cyan"), nl=False)
                elif isinstance(message, ResultMessage):
                    upsert_conversation(db, name, message.session_id, str(conv_dir))

            click.echo()
