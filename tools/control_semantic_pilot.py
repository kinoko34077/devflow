"""Bounded producer-owned GitHub PR/Control comparison for devflow #726.

Explicit one-Control/one-PR read-only check at a producer's transition/exit.
This reuses the M1 compare_claim semantics. GitHub CLI is existing local
authentication, NOT an identity grant by this module. Never auto-edit a
Control, mint a completed review/check or run a fleet scan. Without an
unambiguous current Control claim, the result is UNKNOWN, not an accusation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
from typing import Any

from tools.control_semantic_drift import compare_claim

CONTROL_ID = 705  # Historical accepted no-args pilot default
REPOSITORY = "kinoko34077/kinotch-editor-platform"
PR_NUMBER = 14
CONTROL_PATH = "repos/kinoko34077/devflow/issues/705"
PR_PATH = "repos/kinoko34077/kinotch-editor-platform/pulls/14"
CONTROL_URL = "https://github.com/kinoko34077/devflow/issues/705"
PR_URL = "https://github.com/kinoko34077/kinotch-editor-platform/pull/14"
MAX_BYTES = 1_048_576
SHA = re.compile(r"^[0-9a-f]{40}$")
REPO_NAME = re.compile(r"^kinoko34077/[A-Za-z0-9_.-]{1,100}$")
# Unlike review readiness, OPEN only states API PR.state; no gate inferred.
STAGES = r"MERGED|CLOSED_UNMERGED|AWAIT_REVIEW|AWAIT_MERGE|OPEN"
CLAIM = re.compile(
    r"^- Actual \[PR #14\]"
    r"\(https://github\.com/kinoko34077/kinotch-editor-platform/pull/14\)"
    rf" is \*\*(?:{STAGES})(?=[*])\*\*(?=[\s(]|$)", re.MULTILINE
)


def _read_json(path: str) -> tuple[dict[str, Any], datetime] | None:
    """Only a validated owner-specific GitHub REST path, shell disabled."""
    try:
        result = subprocess.run(
            ["gh", "api", "--method", "GET", path],
            capture_output=True, timeout=12, check=False,
        )
        stamp = datetime.now(timezone.utc)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or len(result.stdout) > MAX_BYTES:
        return None
    try:
        parsed = json.loads(result.stdout)
    except (UnicodeDecodeError, ValueError):
        return None
    return (parsed, stamp) if type(parsed) is dict else None


def _scope(control_id: object, repository: object, pr_number: object) -> bool:
    return (
        type(control_id) is int and 1 <= control_id <= 1_000_000_000
        and type(pr_number) is int and 1 <= pr_number <= 1_000_000_000
        and type(repository) is str
        and REPO_NAME.fullmatch(repository) is not None
        and not repository.endswith(".")
        and ".." not in repository
    )


def _claim_pattern(repository: str, pr_number: int) -> re.Pattern[str]:
    url = f"https://github.com/{repository}/pull/{pr_number}"
    return re.compile(
        rf"^- (?:Actual )?\[PR #{pr_number}\]\({re.escape(url)}\)"
        rf" is \*\*(?P<stage>{STAGES})"
        r"(?:, [^*\r\n]{1,72})?\*\*(?=[\s(]|$)",
        re.MULTILINE,
    )


def _stage(
    issue: dict[str, Any], pr: dict[str, Any],
    *, control_id: int = CONTROL_ID,
    repository: str = REPOSITORY, pr_number: int = PR_NUMBER,
) -> tuple[str, str] | None:
    if not _scope(control_id, repository, pr_number):
        return None
    control_url = f"https://github.com/kinoko34077/devflow/issues/{control_id}"
    pr_url = f"https://github.com/{repository}/pull/{pr_number}"
    repo_name = repository.split("/", 1)[1]
    if (
        type(issue.get("number")) is not int or issue["number"] != control_id
        or issue.get("title") != f"[REPO] {repo_name}"
        or issue.get("state") != "open"
        or issue.get("html_url") != control_url
        or type(issue.get("body")) is not str
    ):
        return None
    sections = re.findall(
        r"^## Next Action[ \t]*\n([\s\S]*?)(?=^## |\Z)",
        issue["body"], re.MULTILINE,
    )
    if len(sections) != 1:
        return None
    current = sections[0].split("**HISTORICAL", 1)[0]
    found = _claim_pattern(repository, pr_number).findall(current)
    if len(found) != 1:
        return None
    if (
        type(pr.get("number")) is not int or pr["number"] != pr_number
        or pr.get("html_url") != pr_url
        or type(pr.get("base")) is not dict
        or type(pr["base"].get("repo")) is not dict
        or pr["base"]["repo"].get("full_name") != repository
        or type(pr.get("head")) is not dict
        or type(pr["head"].get("sha")) is not str
        or not SHA.fullmatch(pr["head"]["sha"])
        or pr.get("state") not in ("open", "closed")
    ):
        return None
    if pr["state"] == "closed":
        if pr.get("merged") is True and (
            type(pr.get("merged_at")) is str and pr["merged_at"]
        ):
            observed = "MERGED"
        elif pr.get("merged") is False and pr.get("merged_at") is None:
            observed = "CLOSED_UNMERGED"
        else:
            return None
    else:
        # OPEN is an objectively observed GitHub state, NOT "review ready".
        if pr.get("merged_at") is not None or pr.get("merged") is not False:
            return None
        observed = "OPEN"
    return found[0], observed


def check_pr_transition_once(
    control_id: int, repository: str, pr_number: int,
) -> dict[str, str]:
    """Two authenticated GETs maximum; read-only advisory with safe UNKNOWN."""
    unknown = {"status": "UNKNOWN", "reason": "LIVE_SOURCE_OR_CLAIM_NOT_PROVEN"}
    if not _scope(control_id, repository, pr_number):
        return unknown
    control_path = f"repos/kinoko34077/devflow/issues/{control_id}"
    pr_path = f"repos/{repository}/pulls/{pr_number}"
    control_url = f"https://github.com/kinoko34077/devflow/issues/{control_id}"
    pr_url = f"https://github.com/{repository}/pull/{pr_number}"
    first = _read_json(control_path)
    if first is None:
        return unknown
    second = _read_json(pr_path)
    if second is None:
        return unknown
    issue, control_time = first
    pr, observed_time = second
    stage = _stage(
        issue, pr, control_id=control_id,
        repository=repository, pr_number=pr_number,
    )
    if stage is None:
        return unknown
    claim_value, actual_value = stage
    iso_control, iso_observed = control_time.isoformat(), observed_time.isoformat()
    control = {
        "repository": repository,
        "subject": repository + f"#{pr_number}",
        "dimension": "PR_GATE",
        "value": claim_value,
        "section": "Next Action",
        "is_current": True,
        "source_verified": True,
        "source_url": control_url,
        "read_at": iso_control,
    }
    observed = {
        "repository": repository,
        "subject": repository + f"#{pr_number}",
        "dimension": "PR_GATE",
        "value": actual_value,
        "source_verified": True,
        "source_complete": True,
        "source_url": pr_url,
        "read_at": iso_observed,
    }
    decision = compare_claim(control, observed)
    return {
        "status": decision["status"],
        "reason": decision["reason"],
        "subject": repository + f"#{pr_number}",
        "claimed_stage": claim_value,
        "observed_stage": actual_value,
        "pr_head_sha": pr["head"]["sha"],
        "control_read_at": iso_control,
        "pr_read_at": iso_observed,
        "control_url": control_url,
        "pr_url": pr_url,
    }


def check_editor_pr14_once() -> dict[str, str]:
    """Legacy fixed-scope pilot; now uses the same transition-time reader."""
    return check_pr_transition_once(CONTROL_ID, REPOSITORY, PR_NUMBER)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Read-only scoped PR/Control stage discrepancy check."
    )
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--control", type=int, default=CONTROL_ID)
    parser.add_argument("--pr", type=int, default=PR_NUMBER)
    args = parser.parse_args()
    print(json.dumps(
        check_pr_transition_once(args.control, args.repository, args.pr),
        ensure_ascii=False, sort_keys=True,
    ))
