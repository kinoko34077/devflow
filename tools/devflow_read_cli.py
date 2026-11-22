"""Read-only Devflow Goal Context, bootstrap, work view and Agent Inbox without MCP tool registration.

Uses the same live Devflow service as the stdio MCP server. Does not schedule,
claim, mutate GitHub state or treat incomplete data as an empty work inventory.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from tools import agent_inbox
from tools.devflow_mcp_core import DevflowMCPError, default_service
from tools.devflow_read_errors import SAFE_READ_FAILURE_CODES, SAFE_ARGUMENT_FAILURE_CODES, failure_reason_code
from tools.goal_plan_assessment import PlanAssessmentError, assess_plan, parse_plan_json

OPERATIONS = (
    "portfolio", "human-portfolio", "bootstrap", "work-view", "scoped-task", "inbox", "workspace", "issue-goal-context",
    "assess-issue-plan", "assess-outcome-observation",
)
MAX_INBOX_LIMIT = agent_inbox.MAX_INBOX_TASKS

def read_operation(
    service: Any, *, operation: str, repository: str | None = None,
    recipient: str = "codex", limit: int = MAX_INBOX_LIMIT, offset: int = 0,
    work_status: str | None = None, issue_number: int | None = None,
    plan: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
    include_recent_kaep: bool = False,
    include_published_supply: bool = False,
) -> Any:
    """Delegate directly to the accepted, read-only MCP core implementation."""
    if operation == "portfolio":
        if repository is not None:
            raise ValueError("REPOSITORY_ON_PORTFOLIO_OPERATION")
        if (recipient != "codex" or limit != MAX_INBOX_LIMIT or offset != 0
                or work_status is not None):
            raise ValueError("INBOX_OPTIONS_ON_NON_INBOX_OPERATION")
    elif type(repository) is not str or not repository.strip():
        raise ValueError("INVALID_REPOSITORY")
    if plan is not None and operation != "assess-issue-plan":
        raise ValueError("PLAN_ON_NON_ASSESSMENT_OPERATION")
    if outcome is not None and operation != "assess-outcome-observation":
        raise ValueError("OUTCOME_ON_NON_ASSESSMENT_OPERATION")
    if type(include_recent_kaep) is not bool or (include_recent_kaep and operation != "workspace"):
        raise ValueError("INVALID_RECENT_DISCOVERY_OPTION")
    if type(include_published_supply) is not bool or (include_published_supply and operation != "workspace"):
        raise ValueError("INVALID_SUPPLY_OBSERVATION_OPTION")
    if operation in {"scoped-task", "issue-goal-context", "assess-issue-plan", "assess-outcome-observation"}:
        if type(issue_number) is not int or issue_number < 1:
            raise ValueError("INVALID_ISSUE_NUMBER")
        if operation == "assess-issue-plan" and plan is None:
            return assess_plan({}, plan)
    elif issue_number is not None:
        raise ValueError("ISSUE_NUMBER_ON_NON_ISSUE_OPERATION")
    elif plan is not None:
        raise ValueError("PLAN_ON_NON_ASSESSMENT_OPERATION")
    if operation == "portfolio":
        return service.get_portfolio_projection()
    if operation == "human-portfolio":
        return service.get_human_portfolio(repository)
    if operation == "bootstrap":
        return service.bootstrap_repository(repository)
    if operation == "work-view":
        return service.get_repository_work_view(repository)
    if operation == "scoped-task":
        return service.get_scoped_task_read(repository, issue_number)
    if operation == "inbox":
        return service.get_agent_inbox(
            repository, recipient, limit=limit, offset=offset,
            work_status=work_status)
    if operation == "workspace":
        if include_recent_kaep or include_published_supply:
            return service.get_agent_workspace(
                repository, recipient, limit=limit, offset=offset,
                work_status=work_status,
                include_recent_kaep=include_recent_kaep,
                include_published_supply=include_published_supply)
        return service.get_agent_workspace(
            repository, recipient, limit=limit, offset=offset,
            work_status=work_status)
    if operation == "issue-goal-context":
        return service.get_issue_goal_context(repository, issue_number)
    if operation == "assess-issue-plan":
        return service.assess_issue_plan(repository, issue_number, plan)
    if operation == "assess-outcome-observation":
        return service.assess_outcome_observation(repository, issue_number, outcome)
    raise ValueError("INVALID_OPERATION")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--repository", default=None)
    parser.add_argument("--recipient", default="codex")
    parser.add_argument(
        "--limit", type=int, default=MAX_INBOX_LIMIT,
        help=f"TASK Issues per page (1..{MAX_INBOX_LIMIT}; default {MAX_INBOX_LIMIT}).",
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        help="Zero-based offset (>= 0); continue with next_offset only when truncated is true.",
    )
    parser.add_argument("--work-status", default=None)
    parser.add_argument(
        "--include-recent-kaep", action="store_true",
        help="Workspace only: opt-in bounded B6 updated-comment original-source GET",
    )
    parser.add_argument(
        "--include-published-supply", action="store_true",
        help="Workspace only: observe published Control candidates, not Claim eligibility",
    )
    parser.add_argument("--issue-number", type=int, default=None)
    parser.add_argument("--plan-file", default=None, help="JSON file containing a declared plan (assess-issue-plan only).")
    parser.add_argument(
        "--outcome-file", default=None,
        help="JSON file containing a declared outcome observation (assess-outcome-observation only).",
    )
    args = parser.parse_args(argv)

    try:
        plan = None
        if args.operation == "portfolio":
            if args.repository is not None:
                raise ValueError("REPOSITORY_ON_PORTFOLIO_OPERATION")
        elif args.repository is None or not args.repository.strip():
            raise ValueError("INVALID_REPOSITORY")
        if not 1 <= args.limit <= MAX_INBOX_LIMIT or args.offset < 0:
            raise ValueError("INVALID_PAGINATION")
        if args.include_recent_kaep and args.operation != "workspace":
            raise ValueError("INVALID_RECENT_DISCOVERY_OPTION")
        if args.include_published_supply and args.operation != "workspace":
            raise ValueError("INVALID_SUPPLY_OBSERVATION_OPTION")
        if args.operation not in {"inbox", "workspace"} and (
            args.recipient != "codex" or args.limit != MAX_INBOX_LIMIT
            or args.offset != 0 or args.work_status is not None
        ):
            raise ValueError("INBOX_OPTIONS_ON_NON_INBOX_OPERATION")
        if args.operation in {"inbox", "workspace"}:
            # Shared with the MCP core: fail before any live GitHub read.
            agent_inbox.validate_inbox_options(
                args.recipient, args.limit, args.offset, args.work_status
            )
        if args.operation in {"scoped-task", "issue-goal-context", "assess-issue-plan", "assess-outcome-observation"}:
            if args.issue_number is None or args.issue_number < 1:
                raise ValueError("INVALID_ISSUE_NUMBER")
        elif args.issue_number is not None:
            raise ValueError("ISSUE_NUMBER_ON_NON_ISSUE_OPERATION")
        if args.operation == "assess-issue-plan":
            if args.plan_file is None:
                plan = None
            else:
                try:
                    with open(args.plan_file, encoding="utf-8") as plan_file:
                        plan = parse_plan_json(plan_file.read(100_001))
                except (OSError, PlanAssessmentError, UnicodeDecodeError):
                    plan = None
        elif args.plan_file is not None:
            raise ValueError("PLAN_ON_NON_ASSESSMENT_OPERATION")
        outcome = None
        if args.operation == "assess-outcome-observation":
            if args.outcome_file is not None:
                try:
                    with open(args.outcome_file, encoding="utf-8") as evidence_file:
                        raw = evidence_file.read(100_001)
                    if len(raw) <= 100_000:
                        packet = json.loads(raw, object_pairs_hook=_unique_object)
                        outcome = packet if isinstance(packet, dict) else None
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    outcome = None
        elif args.outcome_file is not None:
            raise ValueError("OUTCOME_ON_NON_ASSESSMENT_OPERATION")
        if args.operation == "assess-issue-plan" and plan is None:
            print(json.dumps(assess_plan({}, None), ensure_ascii=True, separators=(",", ":")))
            return 0
        result = read_operation(
            default_service(), operation=args.operation,
            repository=args.repository, recipient=args.recipient,
            limit=args.limit, offset=args.offset,
            work_status=args.work_status, issue_number=args.issue_number,
            plan=plan if args.operation == "assess-issue-plan" else None,
            outcome=outcome if args.operation == "assess-outcome-observation" else None,
            include_recent_kaep=args.include_recent_kaep,
            include_published_supply=args.include_published_supply)
        # Preserve the native MCP core's exact data, including partial/unknown
        # coverage diagnostics and null-valued unavailable sources.
        # JSON semantics are unchanged; ASCII escapes prevent cp932 stdout
        # from raising UnicodeEncodeError on non-ASCII Issue content.
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
        return 0
    except (DevflowMCPError, ValueError) as exc:
        # Do not expose GitHub response bodies, headers, private Issues or tokens.
        print(json.dumps({"status": "BLOCKED", "reason_code": failure_reason_code(exc)}))
        return 2


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


if __name__ == "__main__":
    sys.exit(main())
