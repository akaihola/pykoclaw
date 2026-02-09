import argparse
from textwrap import dedent


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

    subparsers.add_parser("chat", help="Start a chat session")
    subparsers.add_parser("scheduler", help="Manage scheduled tasks")
    subparsers.add_parser("conversations", help="View conversation history")
    subparsers.add_parser("tasks", help="Manage tasks")

    args = parser.parse_args()

    if args.command == "chat":
        print("not implemented yet")
    elif args.command == "scheduler":
        print("not implemented yet")
    elif args.command == "conversations":
        print("not implemented yet")
    elif args.command == "tasks":
        print("not implemented yet")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
