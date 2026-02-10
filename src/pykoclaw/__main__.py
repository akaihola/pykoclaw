import asyncio
import os
import sqlite3
from pathlib import Path

import click

from pykoclaw.agent import run_conversation
from pykoclaw.db import init_db, list_conversations, get_all_tasks
from pykoclaw.scheduler import run_scheduler


def _get_db_and_data_dir() -> tuple[sqlite3.Connection, Path]:
    data_dir = Path(os.environ.get("PYKOCLAW_DATA", "")) or (
        Path.home() / ".local" / "share" / "pykoclaw"
    )
    return init_db(data_dir / "pykoclaw.db"), data_dir


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """pykoclaw — Python CLI AI agent"""
    if not ctx.invoked_subcommand:
        click.echo(ctx.get_help())


@main.command()
@click.argument("name")
def chat(name: str) -> None:
    """Start a chat session."""
    db, data_dir = _get_db_and_data_dir()
    asyncio.run(run_conversation(name, db, data_dir))


@main.command()
def scheduler() -> None:
    """Manage scheduled tasks."""
    db, data_dir = _get_db_and_data_dir()
    asyncio.run(run_scheduler(db, data_dir))


@main.command()
def conversations() -> None:
    """View conversation history."""
    db, _ = _get_db_and_data_dir()
    for conv in list_conversations(db):
        name = conv.get("name", "")
        session_id = conv.get("session_id", "")
        created_at = conv.get("created_at", "")
        click.echo(f"{name} | {session_id} | {created_at}")


@main.command()
def tasks() -> None:
    """Manage tasks."""
    db, _ = _get_db_and_data_dir()
    for task in get_all_tasks(db):
        task_id = task.get("id", "")
        conversation = task.get("conversation", "")
        prompt = task.get("prompt", "")
        status = task.get("status", "")
        next_run = task.get("next_run", "")
        prompt_preview = str(prompt)[:50]
        click.echo(
            f"{task_id} | {conversation} | {prompt_preview} | {status} | {next_run}"
        )


if __name__ == "__main__":
    main()
