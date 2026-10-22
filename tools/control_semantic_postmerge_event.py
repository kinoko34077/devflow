"""Read-only native devflow post-merge Control PR semantic event check (#726).

This is an event-triggered, *one-repository* adapter around the existing
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


def _result(status: str, reason: str, number: int | None = None) -> dict[str, str]:
    answer = {"status": status, "reason": reason}
    if type(number) is int and number > 0:
        answer["subject"] = f"{REPOSITORY}#{number}"
    return answer


def _event_number(event: Any, repository_env: str) -> tuple[int | None, str]:
    if type(event) is not dict or repository_env != REPOSITORY:
        return None, "UNTRUSTED_REPOSITORY_OR_EVENT"
    if event.get("action") != "closed":
        return None, "NOT_A_CLOSED_PR_EVENT"
    repo = event.get("repository")
    pr = event.get("pull_request")
    if type(repo) is not dict or repo.get("full_name") != REPOSITORY:
        return None, "UNTRUSTED_REPOSITORY_OR_EVENT"
    if type(pr) is not dict:
        return None, "MISSING_PR_EVENT"
    number = pr.get("number")
    if type(number) is not int or number < 1 or number > 1_000_000_000:
        return None, "INVALID_PR_NUMBER"
    if pr.get("html_url") != f"https://github.com/{REPOSITORY}/pull/{number}":
        return None, "INVALID_PR_IDENTITY"
    base = pr.get("base")
    if type(base) is not dict or type(base.get("repo")) is not dict:
        return None, "INVALID_PR_BASE"
    if base["repo"].get("full_name") != REPOSITORY:
        return None, "INVALID_PR_BASE"
    # Non-merged close is not this pilot's acceptance target.
    if pr.get("merged") is False:
        return number, "CLOSED_UNMERGED_NOT_IN_SCOPE"
    if pr.get("merged") is not True:
        return None, "MERGED_FACT_NOT_PROVEN"
    if type(pr.get("merged_at")) is not str or not pr["merged_at"]:
        return None, "MERGED_FACT_NOT_PROVEN"
    return number, "MERGED_EVENT_VERIFIED"


def _current_next_action(issue: dict[str, Any]) -> str | None:
    if (
        type(issue.get("number")) is not int
        or issue.get("number") != CONTROL_NUMBER
        or issue.get("title") != "[REPO] devflow"
        or issue.get("html_url") != CONTROL_URL
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



OWNER_MARKER = re.compile(
    r"^Owning-Issue: https://github\.com/kinoko34077/devflow/issues/"
    r"([1-9][0-9]{0,8})[ \t]*$", re.MULTILINE,
)


def _owner_reconciliation_candidate(
    current: str, number: int, merged_at: str,
) -> dict[str, str]:
    """Human-authored ownership yields a read-only review candidate, not proof."""
    receipt = pilot._read_json(f"repos/kinoko34077/devflow/pulls/{number}")
    if receipt is None:
        return _result("UNKNOWN", "PR_SOURCE_READ_FAILED", number)
    pr, _time = receipt
    if (
        type(pr.get("number")) is not int or pr["number"] != number
        or pr.get("html_url") != f"https://github.com/{REPOSITORY}/pull/{number}"
        or pr.get("state") != "closed"
        or pr.get("merged") is not True
        or pr.get("merged_at") != merged_at
        or type(pr.get("base")) is not dict
        or type(pr["base"].get("repo")) is not dict
        or pr["base"]["repo"].get("full_name") != REPOSITORY
    ):
        return _result("UNKNOWN", "MERGED_PR_SOURCE_NOT_PROVEN", number)
    body = pr.get("body")
    if body is None:
        body = ""
    if type(body) is not str:
        return _result("UNKNOWN", "INVALID_PR_OWNER_METADATA", number)
    markers = OWNER_MARKER.findall(body)
    if not markers:
        if "Owning-Issue:" in body:
            return _result("UNKNOWN", "UNCANONICAL_OWNER_MARKER", number)
        return _result("NOT_APPLICABLE", "NO_PR_OR_OWNER_REFERENCE", number)
    if len(markers) != 1 or body.count("Owning-Issue:") != 1:
        return _result("UNKNOWN", "AMBIGUOUS_OWNER_MARKER", number)
    owner = int(markers[0])
    owner_receipt = pilot._read_json(
        f"repos/kinoko34077/devflow/issues/{owner}"
    )
    if owner_receipt is None:
        return _result("UNKNOWN", "OWNER_ISSUE_READ_FAILED", number)
    issue, _at = owner_receipt
    if (
        type(issue.get("number")) is not int or issue["number"] != owner
        or issue.get("html_url")
        != f"https://github.com/kinoko34077/devflow/issues/{owner}"
        or issue.get("state") != "open"
        or type(issue.get("pull_request")) is dict
    ):
        return _result("UNKNOWN", "OWNER_ISSUE_IDENTITY_NOT_PROVEN", number)
    exact_link = f"https://github.com/kinoko34077/devflow/issues/{owner}"
    mentioned = (
        exact_link in current
        or re.search(rf"(?<![A-Za-z0-9])#{owner}(?![0-9])", current)
        is not None
    )
    if not mentioned:
        return _result("UNKNOWN", "OWNER_NOT_IN_CURRENT_CONTROL", number)
    answer = _result(
        "RECONCILIATION_REVIEW_REQUIRED", "OWNER_ACTIVE_WITHOUT_PR_LINK", number
    )
    answer["owner_issue_url"] = exact_link
    return answer



def check_native_postmerge_once(
    event: dict[str, Any], repository_env: str
) -> dict[str, str]:
    number, event_reason = _event_number(event, repository_env)
    if number is None:
        return _result("UNKNOWN", event_reason)
    if event_reason == "CLOSED_UNMERGED_NOT_IN_SCOPE":
        return _result("NOT_APPLICABLE", event_reason, number)
    receipt = pilot._read_json("repos/kinoko34077/devflow/issues/16")
    if receipt is None:
        return _result("UNKNOWN", "CANONICAL_CONTROL_READ_FAILED", number)
    issue, _stamp = receipt
    current = _current_next_action(issue)
    if current is None:
        return _result("UNKNOWN", "CURRENT_CONTROL_NOT_PROVEN", number)
    exact_link = (
        f"[PR #{number}](https://github.com/kinoko34077/devflow/pull/{number})"
    )
    if exact_link not in current:
        # A loose but exact-number PR reference cannot safely be skipped.
        if re.search(rf"\bPR\s*#{number}(?!\d)", current):
            return _result("UNKNOWN", "UNCANONICAL_CURRENT_PR_REFERENCE", number)
        # No reference is NOT confirmation that the Control is consistent.
        return _owner_reconciliation_candidate(
            current, number, event["pull_request"]["merged_at"]
        )
    checked = pilot.check_pr_transition_once(CONTROL_NUMBER, REPOSITORY, number)
    if checked.get("status") == "UNKNOWN":
        checked["reason"] = "EXPLICIT_REFERENCE_BUT_STAGE_NOT_PROVEN"
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Devflow read-only merged-PR Control check")
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args(argv)
    try:
        if Path(args.event_path).stat().st_size > EVENT_MAX_BYTES:
            raise ValueError("event too large")
        event = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        result = _result("UNKNOWN", "EVENT_UNAVAILABLE_OR_INVALID")
    else:
        result = check_native_postmerge_once(event, args.repository)
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
