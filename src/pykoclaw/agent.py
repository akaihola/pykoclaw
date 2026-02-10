import sqlite3
import sys
from pathlib import Path

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


async def run_conversation(name: str, db: sqlite3.Connection, data_dir: Path) -> None:
    conv_dir = data_dir / "conversations" / name
    conv_dir.mkdir(parents=True, exist_ok=True)

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

    async with ClaudeSDKClient(options) as client:
        while True:
            print("> ", end="", flush=True, file=sys.stderr)
            try:
                user_input = input()
            except EOFError:
                break

            if not user_input:
                continue

            await client.query(user_input)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(block.text, end="")
                elif isinstance(message, ResultMessage):
                    upsert_conversation(db, name, message.session_id, str(conv_dir))

            print()
