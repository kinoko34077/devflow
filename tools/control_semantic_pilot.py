"""Fixed, read-only GitHub source pilot for Control semantic drift (#726).

Only the already-approved PUBLIC subject devflow Control #705 / editor PR #14
is eligible. Uses the existing authenticated local gh CLI (no extra token,
new crawler, scheduler, file writes, or permission). The comparator's
source_verified flags are constructed ONLY after direct successful REST GETs;
a GitHub-shaped URL or caller-supplied claim cannot authorize observation.
No stage beyond merged/closed-unmerged is inferred from PR GET alone.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import subprocess
from typing import Any

from tools.control_semantic_drift import compare_claim

CONTROL_ID = 705
REPOSITORY = "kinoko34077/kinotch-editor-platform"
PR_NUMBER = 14
CONTROL_PATH = "repos/kinoko34077/devflow/issues/705"
PR_PATH = "repos/kinoko34077/kinotch-editor-platform/pulls/14"
CONTROL_URL = "https://github.com/kinoko34077/devflow/issues/705"
PR_URL = "https://github.com/kinoko34077/kinotch-editor-platform/pull/14"
MAX_BYTES = 1_048_576
SHA = re.compile(r"^[0-9a-f]{40}$")
CLAIM = re.compile(
    r"^- Actual \[PR #14\]"
    r"\(https://github\.com/kinoko34077/kinotch-editor-platform/pull/14\)"
    r" is \*\*(MERGED|AWAIT_REVIEW|AWAIT_MERGE|CLOSED_UNMERGED)\*\*(?=[\s(]|$)",
    re.MULTILINE,
)


def _read_json(path: str) -> tuple[dict[str, Any], datetime] | None:
    """Hard-coded GitHub API path, no caller-controlled args or shell."""
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


def _stage(issue: dict[str, Any], pr: dict[str, Any]) -> tuple[str, str] | None:
    if (
        type(issue.get("number")) is not int or issue["number"] != CONTROL_ID
        or issue.get("title") != "[REPO] kinotch-editor-platform"
        or issue.get("state") != "open"
        or issue.get("html_url") != CONTROL_URL
        or type(issue.get("body")) is not str
    ):
        return None
    body = issue["body"]
    sections = re.findall(
        r"^## Next Action[ \t]*\n([\s\S]*?)(?=^## |\Z)", body, re.MULTILINE
    )
    if len(sections) != 1:
        return None
    current = sections[0].split("**HISTORICAL", 1)[0]
    found = CLAIM.findall(current)
    if len(found) != 1:
        return None
    if (
        type(pr.get("number")) is not int or pr["number"] != PR_NUMBER
        or pr.get("html_url") != PR_URL
        or type(pr.get("base")) is not dict
        or type(pr["base"].get("repo")) is not dict
        or pr["base"]["repo"].get("full_name") != REPOSITORY
        or type(pr.get("head")) is not dict
        or type(pr["head"].get("sha")) is not str
        or not SHA.fullmatch(pr["head"]["sha"])
        or pr.get("state") not in ("open", "closed")
    ):
        return None
    if pr["state"] == "closed":
        if type(pr.get("merged_at")) is str and pr["merged_at"]:
            observed = "MERGED"
        elif pr.get("merged_at") is None and pr.get("merged") is False:
            observed = "CLOSED_UNMERGED"
        else:
            return None
    else:
        # "open" alone does not establish review/merge readiness.
        if pr.get("merged_at") is not None or pr.get("merged") is True:
            return None
        observed = "UNKNOWN"
    return found[0], observed


def check_editor_pr14_once() -> dict[str, str]:
    """Read exactly one scoped Control and PR; return only sanitized evidence."""
    unknown = {"status": "UNKNOWN", "reason": "LIVE_SOURCE_OR_CLAIM_NOT_PROVEN"}
    first = _read_json(CONTROL_PATH)
    if first is None:
        return unknown
    second = _read_json(PR_PATH)
    if second is None:
        return unknown
    issue, control_time = first
    pr, observed_time = second
    stage = _stage(issue, pr)
    if stage is None:
        return unknown
    claim_value, actual_value = stage
    iso_control = control_time.isoformat()
    iso_observed = observed_time.isoformat()
    control = {
        "repository": REPOSITORY,
        "subject": REPOSITORY + "#14",
        "dimension": "PR_GATE",
        "value": claim_value,
        "section": "Next Action",
        "is_current": True,
        "source_verified": True,
        "source_url": CONTROL_URL,
        "read_at": iso_control,
    }
    observed = {
        "repository": REPOSITORY,
        "subject": REPOSITORY + "#14",
        "dimension": "PR_GATE",
        "value": actual_value,
        "source_verified": True,
        "source_complete": True,
        "source_url": PR_URL,
        "read_at": iso_observed,
    }
    decision = compare_claim(control, observed)
    return {
        "status": decision["status"],
        "reason": decision["reason"],
        "subject": REPOSITORY + "#14",
        "claimed_stage": claim_value,
        "observed_stage": actual_value,
        "pr_head_sha": pr["head"]["sha"],
        "control_read_at": iso_control,
        "pr_read_at": iso_observed,
        "control_url": CONTROL_URL,
        "pr_url": PR_URL,
    }


if __name__ == "__main__":
    print(json.dumps(check_editor_pr14_once(), ensure_ascii=False, sort_keys=True))
