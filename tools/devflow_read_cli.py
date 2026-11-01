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
from tools.goal_plan_assessment import PlanAssessmentError, assess_plan, parse_plan_json

OPERATIONS = (
    "bootstrap", "work-view", "inbox", "issue-goal-context",
    "assess-issue-plan", "assess-outcome-observation",
)
MAX_INBOX_LIMIT = agent_inbox.MAX_INBOX_TASKS

# Never echo exception text or caller-controlled fields into machine-readable
# diagnostics. Unknown/future core error codes fail back to the generic code.
SAFE_READ_FAILURE_CODES = frozenset({
    "DEVFLOW_READ_UNAVAILABLE",
    "GITHUB_HTTP_401",
    "GITHUB_HTTP_403",
    "GITHUB_HTTP_403_RATE_LIMIT",
    "GITHUB_HTTP_404",
    "GITHUB_HTTP_429",
    "GITHUB_HTTP_OTHER",
    "GITHUB_NETWORK_UNAVAILABLE",
    "GITHUB_INVALID_JSON",
    "GITHUB_REDIRECTED_READ",
    "CONTROL_NOT_FOUND_OR_UNTRUSTED",
    "CONTROL_AMBIGUOUS",
    "CONTROL_SCHEMA_INVALID",
    "CONTROL_REPOSITORY_MISMATCH",
})
SAFE_ARGUMENT_FAILURE_CODES = frozenset({
    "INVALID_REPOSITORY",
    "INVALID_PAGINATION",
    "INBOX_OPTIONS_ON_NON_INBOX_OPERATION",
    "INVALID_RECIPIENT",
    "INVALID_LIMIT",
    "INVALID_OFFSET",
    "INVALID_WORK_STATUS",
    "INVALID_ISSUE_NUMBER",
    "ISSUE_NUMBER_ON_NON_ISSUE_OPERATION",
    "PLAN_ON_NON_ASSESSMENT_OPERATION",
    "OUTCOME_ON_NON_ASSESSMENT_OPERATION",
})


def failure_reason_code(exc: DevflowMCPError | ValueError) -> str:
    """Expose only an enumerated diagnostic; never a raw exception message."""
    if isinstance(exc, DevflowMCPError):
        code = getattr(exc, "reason_code", None)
        return code if code in SAFE_READ_FAILURE_CODES else "DEVFLOW_READ_UNAVAILABLE"
    code = str(exc)
    return code if code in SAFE_ARGUMENT_FAILURE_CODES else "INVALID_ARGUMENTS"


def read_operation(
    service: Any, *, operation: str, repository: str,
    recipient: str = "codex", limit: int = 20, offset: int = 0,
    work_status: str | None = None, issue_number: int | None = None,
    plan: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
) -> Any:
    """Delegate directly to the accepted, read-only MCP core implementation."""
    if plan is not None and operation != "assess-issue-plan":
        raise ValueError("PLAN_ON_NON_ASSESSMENT_OPERATION")
    if outcome is not None and operation != "assess-outcome-observation":
        raise ValueError("OUTCOME_ON_NON_ASSESSMENT_OPERATION")
    if operation in {"issue-goal-context", "assess-issue-plan", "assess-outcome-observation"}:
        if type(issue_number) is not int or issue_number < 1:
            raise ValueError("INVALID_ISSUE_NUMBER")
        if operation == "assess-issue-plan" and plan is None:
            return assess_plan({}, plan)
    elif issue_number is not None:
        raise ValueError("ISSUE_NUMBER_ON_NON_ISSUE_OPERATION")
    elif plan is not None:
        raise ValueError("PLAN_ON_NON_ASSESSMENT_OPERATION")
    if operation == "bootstrap":
        return service.bootstrap_repository(repository)
    if operation == "work-view":
        return service.get_repository_work_view(repository)
    if operation == "inbox":
        return service.get_agent_inbox(
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
    parser.add_argument("--repository", required=True)
    parser.add_argument("--recipient", default="codex")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--work-status", default=None)
    parser.add_argument("--issue-number", type=int, default=None)
    parser.add_argument("--plan-file", default=None, help="JSON file containing a declared plan (assess-issue-plan only).")
    parser.add_argument(
        "--outcome-file", default=None,
        help="JSON file containing a declared outcome observation (assess-outcome-observation only).",
    )
    args = parser.parse_args(argv)

    try:
        plan = None
        if not args.repository.strip():
            raise ValueError("INVALID_REPOSITORY")
        if not 1 <= args.limit <= MAX_INBOX_LIMIT or args.offset < 0:
            raise ValueError("INVALID_PAGINATION")
        if args.operation != "inbox" and (
            args.recipient != "codex" or args.limit != 20
            or args.offset != 0 or args.work_status is not None
        ):
            raise ValueError("INBOX_OPTIONS_ON_NON_INBOX_OPERATION")
        if args.operation == "inbox":
            # Shared with the MCP core: fail before any live GitHub read.
            agent_inbox.validate_inbox_options(
                args.recipient, args.limit, args.offset, args.work_status
            )
        if args.operation in {"issue-goal-context", "assess-issue-plan", "assess-outcome-observation"}:
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
            outcome=outcome if args.operation == "assess-outcome-observation" else None)
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
