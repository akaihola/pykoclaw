import asyncio
from pathlib import Path

import click

from pykoclaw.config import settings
from pykoclaw.db import DbConnection, init_db, list_conversations, get_all_tasks
from pykoclaw.plugins import load_plugins, run_db_migrations
from pykoclaw.scheduler import run_scheduler


def _get_db_and_data_dir() -> tuple[DbConnection, Path]:
    return init_db(settings.db_path), settings.data


class _PluginGroup(click.Group):
    _plugins_loaded = False

    def _ensure_plugins(self) -> None:
        if self._plugins_loaded:
            return
        self._plugins_loaded = True
        plugins = load_plugins()
        db, _ = _get_db_and_data_dir()
        run_db_migrations(db, plugins)
        for plugin in plugins:
            plugin.register_commands(self)

    def list_commands(self, ctx: click.Context) -> list[str]:
        self._ensure_plugins()
        return super().list_commands(ctx)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        self._ensure_plugins()
        return super().get_command(ctx, cmd_name)


@click.group(cls=_PluginGroup, invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """pykoclaw — Python CLI AI agent"""
    if not ctx.invoked_subcommand:
        click.echo(ctx.get_help())


@main.command()
def scheduler() -> None:
    """Run the task scheduler daemon (polls every 60s for due tasks)."""
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
    """List all scheduled tasks and their status."""
    db, _ = _get_db_and_data_dir()
    all_tasks = get_all_tasks(db)
    if not all_tasks:
        click.echo("No scheduled tasks.")
        return
    click.echo(
        f"{'ID':<10} {'Conversation':<30} {'Prompt':<50} {'Status':<10} {'Next Run'}"
    )
    click.echo("-" * 110)
    for task in all_tasks:
        click.echo(
            f"{task.id:<10} {task.conversation:<30} {task.prompt[:50]:<50}"
            f" {task.status:<10} {task.next_run}"
        )


if __name__ == "__main__":
    main()
