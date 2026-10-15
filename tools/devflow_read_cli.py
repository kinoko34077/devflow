"""Read-only Devflow bootstrap, work view and Agent Inbox without MCP tool registration.

Uses the same live Devflow service as the stdio MCP server. Does not schedule,
claim, mutate GitHub state or treat incomplete data as an empty work inventory.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from tools.devflow_mcp_core import DevflowMCPError, default_service

OPERATIONS = ("bootstrap", "work-view", "inbox")
MAX_INBOX_LIMIT = 100


def read_operation(
    service: Any, *, operation: str, repository: str,
    recipient: str = "codex", limit: int = 20, offset: int = 0,
    work_status: str | None = None,
) -> Any:
    """Delegate directly to the accepted, read-only MCP core implementation."""
    if operation == "bootstrap":
        return service.bootstrap_repository(repository)
    if operation == "work-view":
        return service.get_repository_work_view(repository)
    if operation == "inbox":
        return service.get_agent_inbox(
            repository, recipient, limit=limit, offset=offset,
            work_status=work_status)
    raise ValueError("INVALID_OPERATION")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--recipient", default="codex")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--work-status", default=None)
    args = parser.parse_args(argv)

    try:
        if not args.repository.strip():
            raise ValueError("INVALID_REPOSITORY")
        if not 1 <= args.limit <= MAX_INBOX_LIMIT or args.offset < 0:
            raise ValueError("INVALID_PAGINATION")
        if args.operation != "inbox" and (
            args.recipient != "codex" or args.limit != 20
            or args.offset != 0 or args.work_status is not None
        ):
            raise ValueError("INBOX_OPTIONS_ON_NON_INBOX_OPERATION")
        result = read_operation(
            default_service(), operation=args.operation,
            repository=args.repository, recipient=args.recipient,
            limit=args.limit, offset=args.offset,
            work_status=args.work_status)
        # Preserve the native MCP core's exact data, including partial/unknown
        # coverage diagnostics and null-valued unavailable sources.
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (DevflowMCPError, ValueError) as exc:
        # Do not expose GitHub response bodies, headers, private Issues or tokens.
        reason = str(exc) if isinstance(exc, ValueError) else "DEVFLOW_READ_UNAVAILABLE"
        print(json.dumps({"status": "BLOCKED", "reason_code": reason}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
