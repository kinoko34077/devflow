"""Read-only native devflow post-merge Control PR semantic event check (#726).

This is an event-triggered, source-scoped adapter around the existing
source-backed semantic PR reader. No GitHub mutation, new credential, local
persistence, scheduler, general multi-repo hook, or implicit readiness claim.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from tools import control_semantic_pilot as pilot

REPOSITORY = "kinoko34077/devflow"
CONTROL_NUMBER = 16
CONTROL_URL = "https://github.com/kinoko34077/devflow/issues/16"
EVENT_MAX_BYTES = 1_048_576


def _result(status: str, reason: str, number: int | None = None, repository: str = REPOSITORY) -> dict[str, str]:
    answer = {"status": status, "reason": reason}
    if type(number) is int and number > 0:
        answer["subject"] = f"{repository}#{number}"
    return answer


def _event_number(event: Any, repository_env: str, expected_repository: str = REPOSITORY) -> tuple[int | None, str]:
    if type(event) is not dict or repository_env != expected_repository:
        return None, "UNTRUSTED_REPOSITORY_OR_EVENT"
    if event.get("action") != "closed":
        return None, "NOT_A_CLOSED_PR_EVENT"
    repo = event.get("repository")
    pr = event.get("pull_request")
    if type(repo) is not dict or repo.get("full_name") != expected_repository:
        return None, "UNTRUSTED_REPOSITORY_OR_EVENT"
    if type(pr) is not dict:
        return None, "MISSING_PR_EVENT"
    number = pr.get("number")
    if type(number) is not int or number < 1 or number > 1_000_000_000:
        return None, "INVALID_PR_NUMBER"
    if pr.get("html_url") != f"https://github.com/{expected_repository}/pull/{number}":
        return None, "INVALID_PR_IDENTITY"
    base = pr.get("base")
    if type(base) is not dict or type(base.get("repo")) is not dict:
        return None, "INVALID_PR_BASE"
    if base["repo"].get("full_name") != expected_repository:
        return None, "INVALID_PR_BASE"
    # Non-merged close is not this pilot's acceptance target.
    if pr.get("merged") is False:
        return number, "CLOSED_UNMERGED_NOT_IN_SCOPE"
    if pr.get("merged") is not True:
        return None, "MERGED_FACT_NOT_PROVEN"
    if type(pr.get("merged_at")) is not str or not pr["merged_at"]:
        return None, "MERGED_FACT_NOT_PROVEN"
    return number, "MERGED_EVENT_VERIFIED"


def _current_next_action(issue: dict[str, Any], control_id: int = CONTROL_NUMBER, repository: str = REPOSITORY) -> str | None:
    if (
        type(issue.get("number")) is not int
        or issue.get("number") != control_id
        or issue.get("title") != f"[REPO] {repository.partition(chr(47))[2]}"
        or issue.get("html_url") != f"https://github.com/kinoko34077/devflow/issues/{control_id}"
        or issue.get("state") != "open"
        or type(issue.get("body")) is not str
    ):
        return None
    sections = re.findall(
        r"^## Next Action[ \t]*\n([\s\S]*?)(?=^## |\Z)",
        issue["body"],
        re.MULTILINE,
    )
    if len(sections) != 1:
        return None
    return sections[0].split("**HISTORICAL", 1)[0]



# Reuse the existing PR template's single "- Owning-Issue:" field.
# Accept legacy unbulleted owner lines but never guess owner from loose prose.
OWNER_LINE = re.compile(
    r"^(?:- )?Owning-Issue:[ \t]*([^\r\n]*)\r?$", re.MULTILINE,
)
OWNER_VALUE = re.compile(
    r"(?:#(?P<relative>[1-9][0-9]{0,8})|"
    r"https://github\.com/(?P<absolute_repo>kinoko34077/[A-Za-z0-9_.-]{1,100})"
    r"/issues/(?P<absolute_number>[1-9][0-9]{0,8}))"
)


def _parse_owner_issue(value: str, caller_repository: str) -> tuple[str, int] | None:
    """GitHub relative #N names the *caller* Issue, never devflow by default."""
    marker = OWNER_VALUE.fullmatch(value)
    if marker is None:
        return None
    if marker.group("relative") is not None:
        return (caller_repository, int(marker.group("relative")))
    absolute = marker.group("absolute_repo")
    # No arbitrary GitHub account/repository issue fetches from user PR text.
    if absolute not in (caller_repository, REPOSITORY):
        return None
    return (absolute, int(marker.group("absolute_number")))


def _owner_reconciliation_candidate(
    current: str, number: int, merged_at: str, repository: str = REPOSITORY,
) -> dict[str, str]:
    """Human-authored ownership yields a read-only review candidate, not proof."""
    receipt = pilot._read_json(f"repos/{repository}/pulls/{number}")
    if receipt is None:
        return _result("UNKNOWN", "PR_SOURCE_READ_FAILED", number, repository)
    pr, _time = receipt
    if (
        type(pr.get("number")) is not int or pr["number"] != number
        or pr.get("html_url") != f"https://github.com/{repository}/pull/{number}"
        or pr.get("state") != "closed"
        or pr.get("merged") is not True
        or pr.get("merged_at") != merged_at
        or type(pr.get("base")) is not dict
        or type(pr["base"].get("repo")) is not dict
        or pr["base"]["repo"].get("full_name") != repository
    ):
        return _result("UNKNOWN", "MERGED_PR_SOURCE_NOT_PROVEN", number, repository)
    body = pr.get("body")
    if body is None:
        body = ""
    if type(body) is not str:
        return _result("UNKNOWN", "INVALID_PR_OWNER_METADATA", number, repository)
    declarations = [part.strip() for part in OWNER_LINE.findall(body)]
    # Empty template placeholders are not evidence of ownership.
    # Ignore inline code/prose mentioning the field name entirely.
    filled = [part for part in declarations if part]
    if not filled:
        return _result("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE", number, repository)
    if len(filled) != 1:
        return _result("UNKNOWN", "AMBIGUOUS_OWNER_MARKER", number, repository)
    scoped_owner = _parse_owner_issue(filled[0], repository)
    if scoped_owner is None:
        return _result("UNKNOWN", "UNCANONICAL_OWNER_MARKER", number, repository)
    owner_repository, owner = scoped_owner
    owner_receipt = pilot._read_json(
        f"repos/{owner_repository}/issues/{owner}"
    )
    if owner_receipt is None:
        return _result("UNKNOWN", "OWNER_ISSUE_READ_FAILED", number, repository)
    issue, _at = owner_receipt
    if (
        type(issue.get("number")) is not int or issue["number"] != owner
        or issue.get("html_url")
        != f"https://github.com/{owner_repository}/issues/{owner}"
        or issue.get("state") != "open"
        or type(issue.get("pull_request")) is dict
    ):
        return _result("UNKNOWN", "OWNER_ISSUE_IDENTITY_NOT_PROVEN", number, repository)
    exact_link = f"https://github.com/{owner_repository}/issues/{owner}"
    explicit_url = (
        re.search(re.escape(exact_link) + r"(?=$|[\s)\],;.!?])", current)
        is not None
    )
    if owner_repository == REPOSITORY:
        # Control lives in devflow; bare #N there means a devflow Issue.
        scoped_text = (
            re.search(
                rf"(?<![A-Za-z0-9])(?:devflow)?#{owner}(?![0-9])",
                current,
            ) is not None
        )
    else:
        # A caller-local #N must not accidentally match devflow's #N.
        repo_name = owner_repository.split("/", 1)[1]
        scoped_text = (
            re.search(
                rf"(?<![A-Za-z0-9_./-])(?:{re.escape(owner_repository)}|"
                rf"{re.escape(repo_name)})#{owner}(?![0-9])",
                current,
            ) is not None
        )
    mentioned = explicit_url or scoped_text
    if not mentioned:
        return _result("UNKNOWN", "OWNER_NOT_IN_CURRENT_CONTROL", number, repository)
    answer = _result(
        "RECONCILIATION_REVIEW_REQUIRED", "OWNER_ACTIVE_WITHOUT_PR_LINK", number, repository
    )
    answer["owner_issue_url"] = exact_link
    return answer



def check_native_postmerge_once(
    event: dict[str, Any], repository_env: str, control_id: int = CONTROL_NUMBER
) -> dict[str, str]:
    if not pilot._scope(control_id, repository_env, 1):
        return _result("UNKNOWN", "OUT_OF_SCOPE_REPOSITORY_OR_CONTROL")
    number, event_reason = _event_number(event, repository_env, repository_env)
    if number is None:
        return _result("UNKNOWN", event_reason)
    if event_reason == "CLOSED_UNMERGED_NOT_IN_SCOPE":
        return _result("NOT_APPLICABLE", event_reason, number, repository_env)
    receipt = pilot._read_json(f"repos/kinoko34077/devflow/issues/{control_id}")
    if receipt is None:
        return _result("UNKNOWN", "CANONICAL_CONTROL_READ_FAILED", number, repository_env)
    issue, _stamp = receipt
    current = _current_next_action(issue, control_id, repository_env)
    if current is None:
        return _result("UNKNOWN", "CURRENT_CONTROL_NOT_PROVEN", number, repository_env)
    exact_link = (
        f"[PR #{number}](https://github.com/{repository_env}/pull/{number})"
    )
    if exact_link not in current:
        # A loose but exact-number PR reference cannot safely be skipped.
        if re.search(rf"\bPR\s*#{number}(?!\d)", current):
            return _result("UNKNOWN", "UNCANONICAL_CURRENT_PR_REFERENCE", number, repository_env)
        # No reference is NOT confirmation that the Control is consistent.
        return _owner_reconciliation_candidate(
            current, number, event["pull_request"]["merged_at"], repository_env
        )
    checked = pilot.check_pr_transition_once(control_id, repository_env, number)
    if checked.get("status") == "UNKNOWN":
        checked["reason"] = "EXPLICIT_REFERENCE_BUT_STAGE_NOT_PROVEN"
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Devflow read-only merged-PR Control check")
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--control", type=int, default=CONTROL_NUMBER)
    args = parser.parse_args(argv)
    try:
        if Path(args.event_path).stat().st_size > EVENT_MAX_BYTES:
            raise ValueError("event too large")
        event = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        result = _result("UNKNOWN", "EVENT_UNAVAILABLE_OR_INVALID")
    else:
        result = check_native_postmerge_once(event, args.repository, args.control)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] in ("ALIGNED", "NOT_APPLICABLE"):
        return 0
    if result["status"] == "POTENTIAL_MISMATCH":
        return 2
    if result["status"] == "RECONCILIATION_REVIEW_REQUIRED":
        return 4
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
