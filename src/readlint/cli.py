"""Noninteractive evaluation commands; login shows approval instructions on stderr."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

from readlint import Readlint, ReadlintError, __version__
from readlint.auth import credentials_path, load_credentials, login


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse messages may echo a mistyped API key. Keep errors input-free.
        raise ValueError(
            "Invalid command or arguments. Run `readlint --help` or `<command> --help`."
        )


def parser() -> argparse.ArgumentParser:
    common = Parser(add_help=False)
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="JSON stdout; JSON errors on stderr",
    )
    common.add_argument(
        "--api-key",
        default=argparse.SUPPRESS,
        help="API key (prefer READLINT_API_KEY to shell history)",
    )
    common.add_argument(
        "--base-url",
        default=argparse.SUPPRESS,
        help="HTTPS API origin; default https://readlint.com",
    )
    common.add_argument(
        "--timeout",
        type=float,
        default=argparse.SUPPRESS,
        help="HTTP timeout in seconds; default 120",
    )
    root = Parser(
        prog="readlint",
        description="Review articles through readlint.com.",
        parents=[common],
    )
    root.add_argument("--version", action="version", version=f"readlint {__version__}")
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands.add_parser(
        "login", parents=[common], help="Approve a device code in the web app"
    )
    commands.add_parser(
        "logout",
        parents=[common],
        help="Remove this local login; revoke keys in the web app",
    )
    commands.add_parser("version", parents=[common], help="Print the installed version")
    commands.add_parser("mcp", parents=[common], help="Serve MCP tools over stdio")
    evaluate = commands.add_parser(
        "evaluate", aliases=["check"], parents=[common], help="Submit Markdown or MDX"
    )
    evaluate.add_argument("file", help="UTF-8 file, or - for stdin")
    evaluate.add_argument("--title")
    evaluate.add_argument("--description", default="")
    evaluate.add_argument(
        "--idempotency-key",
        help="Reuse this key and identical input to recover a timed-out submission",
    )
    permissions = commands.add_parser(
        "agent-permissions",
        parents=[common],
        help="Read the owner's agent billing policy",
    )
    permissions.add_subparsers(
        dest="permissions_command", required=True, parser_class=Parser
    ).add_parser(
        "get",
        parents=[common],
        help="Read permissions; changes require the owner browser",
    )
    listing = commands.add_parser("list", parents=[common], help="List evaluations")
    listing.add_argument("--limit", type=int)
    listing.add_argument("--offset", type=int, default=0)
    for name in ("get", "delete"):
        command = commands.add_parser(
            name, parents=[common], help=f"{name.title()} an evaluation by ID"
        )
        command.add_argument("id")
    return root


def main() -> int:
    machine = "--json" in sys.argv[1:]
    submission_key = None
    try:
        args = parser().parse_args()
        if args.command == "mcp":
            from readlint.mcp import serve

            serve(
                api_key=getattr(args, "api_key", None),
                base_url=getattr(args, "base_url", None),
                timeout=getattr(args, "timeout", 120),
            )
            return 0
        if args.command == "version":
            result = {"version": __version__}
        elif args.command == "logout":
            credentials_path().unlink(missing_ok=True)
            result = {
                "signed_in": False,
                "message": "Local login removed. Revoke its API key at https://readlint.com/app/api-keys.",
            }
        else:
            key = getattr(args, "api_key", None) or os.environ.get("READLINT_API_KEY")
            with Readlint(
                api_key=key,
                base_url=getattr(args, "base_url", None),
                timeout=getattr(args, "timeout", 120),
            ) as client:
                if args.command == "login":
                    login(
                        client,
                        lambda uri, code: print(
                            f"Open {uri}\nCheck and approve code {code}.",
                            file=sys.stderr,
                        ),
                    )
                    result = {"signed_in": True}
                else:
                    if not key:
                        client._api_key = load_credentials(client.base_url)
                    if args.command in {"evaluate", "check"}:
                        article = (
                            sys.stdin.read()
                            if args.file == "-"
                            else Path(args.file).read_text(encoding="utf-8")
                        )
                        submission_key = args.idempotency_key or str(uuid4())
                        print(f"Idempotency key: {submission_key}", file=sys.stderr)
                        result = client.evaluate(
                            article,
                            idempotency_key=submission_key,
                            title=args.title,
                            description=args.description,
                        )
                    elif args.command == "agent-permissions":
                        result = client.get_agent_permissions()
                    elif args.command == "list":
                        result = client.list_evaluations(
                            limit=args.limit, offset=args.offset
                        )
                    elif args.command == "get":
                        result = client.get_evaluation(args.id)
                    else:
                        client.delete_evaluation(args.id)
                        result = {"deleted": True, "id": args.id}
        if machine:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ReadlintError as exc:
        problem = exc.as_dict()
    except (ValueError, OSError, UnicodeError):
        problem = {
            "code": "invalid_input",
            "message": "Check the command, UTF-8 input file, URL and credential file permissions. Run `readlint --help`.",
        }
    except KeyboardInterrupt:
        problem = {
            "code": "interrupted",
            "message": "Interrupted. Reuse the submission key and identical input to check its outcome."
            if submission_key
            else "Interrupted.",
        }
    if submission_key:
        problem["idempotency_key"] = submission_key
    print(
        json.dumps({"error": problem})
        if machine
        else f"{problem['code']}: {problem['message']}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
