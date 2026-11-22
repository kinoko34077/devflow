"""Native read-only KAEP Agent Inbox CLI for existing user-managed check-ins.

Fetches a bounded explicit repository set via the accepted Devflow MCP core.
Does not start/poll Claude itself, schedule timers, send KAEP, or claim work.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from tools.agent_inbox import MAX_INBOX_TASKS
from tools.devflow_mcp_core import DevflowMCPError, default_service, normalize_repository
from tools.devflow_read_errors import failure_reason_code

MAX_REPOSITORIES = 5


def read_checkin(
    service: Any, *, repositories: list[str],
    recipient: str, work_status: str | None, limit: int,
    offset: int, pending_only: bool,
) -> dict[str, Any]:
    if not isinstance(repositories, list) or not 1 <= len(repositories) <= MAX_REPOSITORIES:
        raise ValueError("INVALID_REPOSITORY_COUNT")
    # Short and fully qualified names resolve to the same managed repository.
    # Reject duplicate identities before the first live GitHub read.
    normalized = [normalize_repository(repository) for repository in repositories]
    if len(normalized) != len(set(normalized)):
        raise ValueError("DUPLICATE_REPOSITORY")
    results: list[dict[str, Any]] = []
    for repository in repositories:
        result = service.get_agent_inbox(
            repository, recipient, work_status=work_status,
            limit=limit, offset=offset)
        if pending_only:
            # Diagnostic failures MUST remain visible even under a pending-only filter.
            result["issues"] = [
                item for item in result["issues"]
                if item.get("requests") is None
                or any(req["status"] in ("PENDING_REPLY", "ACK_OBSERVED")
                       for req in item["requests"])
            ]
        results.append(result)
    degraded = any(x["has_unknown_work"] for x in results)
    return {
        "schema_version": "kaep.agent-inbox.checkin.v0.1",
        "status": "INCOMPLETE_OR_UNKNOWN" if degraded else "READ_ONLY",
        "recipient": recipient, "repositories": results,
        "checked_repository_count": len(results),
        "can_authorize_execution": False,
        "can_modify_checkin_schedule": False,
        "has_unknown_work": degraded,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", action="append", dest="repositories",
                        help="Explicit managed repo; repeat 1–5 times (default: devflow)")
    parser.add_argument("--recipient", default="claude-code")
    parser.add_argument("--work-status", default=None)
    parser.add_argument(
        "--limit", type=int, default=MAX_INBOX_TASKS,
        help=f"TASK Issues per page (1..{MAX_INBOX_TASKS}; default {MAX_INBOX_TASKS}).",
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        help="Zero-based offset (>= 0); continue with next_offset only when truncated is true.",
    )
    parser.add_argument("--pending-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = read_checkin(
            default_service(),
            repositories=args.repositories or ["kinoko34077/devflow"],
            recipient=args.recipient, work_status=args.work_status,
            limit=args.limit, offset=args.offset,
            pending_only=args.pending_only)
        # ASCII escaping preserves all Unicode Issue content on cp932 consoles.
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
        return 0
    except (DevflowMCPError, ValueError) as exc:
        # Fixed status, no raw secrets/private Issue text in errors.
        # Preserve the existing generic core-error contract and only emit
        # allowlisted ValueError codes; never echo arbitrary exception text.
        reason = ("DEVFLOW_READ_UNAVAILABLE" if isinstance(exc, DevflowMCPError)
                  else failure_reason_code(exc))
        print(json.dumps({"status": "BLOCKED", "reason_code": reason}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
