import asyncio
import argparse
import os
from pathlib import Path
from textwrap import dedent

from pykoclaw.agent import run_conversation
from pykoclaw.db import init_db, list_conversations, get_all_tasks
from pykoclaw.scheduler import run_scheduler


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pykoclaw",
        description=dedent(
            """\
            pykoclaw — Python CLI AI agent
            """
        ),
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    chat_parser = subparsers.add_parser("chat", help="Start a chat session")
    chat_parser.add_argument("name", help="Conversation name")

    subparsers.add_parser("scheduler", help="Manage scheduled tasks")
    subparsers.add_parser("conversations", help="View conversation history")
    subparsers.add_parser("tasks", help="Manage tasks")

    args = parser.parse_args()

    data_dir = Path(os.environ.get("PYKOCLAW_DATA", "")) or (
        Path.home() / ".local" / "share" / "pykoclaw"
    )
    db = init_db(data_dir / "pykoclaw.db")

    if args.command == "chat":
        asyncio.run(run_conversation(args.name, db, data_dir))
    elif args.command == "scheduler":
        asyncio.run(run_scheduler(db, data_dir))
    elif args.command == "conversations":
        conversations = list_conversations(db)
        for conv in conversations:
            name = conv.get("name", "")
            session_id = conv.get("session_id", "")
            created_at = conv.get("created_at", "")
            print(f"{name} | {session_id} | {created_at}")
    elif args.command == "tasks":
        tasks = get_all_tasks(db)
        for task in tasks:
            task_id = task.get("id", "")
            conversation = task.get("conversation", "")
            prompt = task.get("prompt", "")
            status = task.get("status", "")
            next_run = task.get("next_run", "")
            prompt_preview = str(prompt)[:50]
            print(
                f"{task_id} | {conversation} | {prompt_preview} | {status} | {next_run}"
            )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
