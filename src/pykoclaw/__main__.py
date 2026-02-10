import asyncio
import sqlite3
from pathlib import Path

import click

from pykoclaw.agent import run_conversation
from pykoclaw.config import settings
from pykoclaw.db import init_db, list_conversations, get_all_tasks
from pykoclaw.scheduler import run_scheduler


def _get_db_and_data_dir() -> tuple[sqlite3.Connection, Path]:
    return init_db(settings.db_path), settings.data


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
        click.echo(f"{conv.name} | {conv.session_id} | {conv.created_at}")


@main.command()
def tasks() -> None:
    """Manage tasks."""
    db, _ = _get_db_and_data_dir()
    for task in get_all_tasks(db):
        click.echo(
            f"{task.id} | {task.conversation} | {task.prompt[:50]}"
            f" | {task.status} | {task.next_run}"
        )


if __name__ == "__main__":
    main()
