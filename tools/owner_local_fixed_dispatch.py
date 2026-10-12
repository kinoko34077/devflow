"""Manually invoked, owner-local, single-target GitHub Actions fallback.

This is NOT an autonomous G1 adapter or an approved, authenticated receipt.
The accepted GitHub connection remains first choice. In particular, invoking
--execute is a separately intentional local action; merely importing or
running this module without it never sends a workflow dispatch.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass

ACTOR = "kinoko34077"
REPOSITORY = "kinoko34077/devflow"
BRANCH = "main"
WORKFLOW = "maintenance-audit.yml"
# Independently reviewed existing workflow bytes at the R1 baseline. Changed
# workflow definitions are *not* implicitly trusted or admitted for dispatch.
WORKFLOW_BLOB_SHA = "e068daf4ce7cf0a3f774d6819d086f7f2d2c47f8"
WORKFLOW_PATH = ".github/workflows/maintenance-audit.yml"
SHA_RE = re.compile(r"[a-f0-9]{40}\Z")


@dataclass(frozen=True)
class Result:
    code: str
    success: bool


def _query(args: tuple[str, ...]) -> str | None:
    """Run a fixed gh read. Never echo captured GitHub stderr or credentials."""
    try:
        completed = subprocess.run(
            ["gh", *args], capture_output=True, text=True,
            timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def preflight(expected_head: str) -> Result:
    if not isinstance(expected_head, str) or SHA_RE.fullmatch(expected_head) is None:
        return Result("HOLD_INVALID_EXPECTED_HEAD", False)
    # The resident gh login must be used; environment-provided bearer values
    # could silently shadow the intended owner-local authenticated identity.
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        return Result("HOLD_ENV_TOKEN_SHADOW", False)
    actor = _query(("api", "user", "--jq", ".login"))
    if actor != ACTOR:
        return Result("HOLD_UNVERIFIED_ACTOR", False)
    head = _query((
        "api", f"repos/{REPOSITORY}/branches/{BRANCH}", "--jq", ".commit.sha",
    ))
    if head != expected_head:
        return Result("HOLD_MAIN_HEAD_CHANGED_OR_UNAVAILABLE", False)
    source_blob = _query((
        "api", f"repos/{REPOSITORY}/contents/{WORKFLOW_PATH}?ref={BRANCH}",
        "--jq", ".sha",
    ))
    if source_blob != WORKFLOW_BLOB_SHA:
        return Result("HOLD_UNREVIEWED_WORKFLOW_SOURCE", False)
    state = _query((
        "api", f"repos/{REPOSITORY}/actions/workflows/{WORKFLOW}",
        "--jq", ".state",
    ))
    if state != "active":
        return Result("HOLD_WORKFLOW_DISABLED_OR_UNAVAILABLE", False)
    return Result("PREFLIGHT_OK_NO_ACTION_TAKEN_ACTIONS_WRITE_UNVERIFIED", True)


def dispatch(expected_head: str) -> Result:
    """Explicit owner-local launch, never proof that the job actually ran."""
    result = preflight(expected_head)
    if not result.success:
        return result
    # Minimize time-of-check-to-time-of-use exposure. This is NOT an atomic
    # SHA pin: GitHub workflow_dispatch uses the named ref and a subsequent
    # run must be checked independently before treating it as accepted work.
    head = _query((
        "api", f"repos/{REPOSITORY}/branches/{BRANCH}", "--jq", ".commit.sha",
    ))
    if head != expected_head:
        return Result("HOLD_HEAD_CHANGED_BEFORE_REQUEST", False)
    try:
        completed = subprocess.run(
            [
                "gh", "workflow", "run", WORKFLOW,
                "--repo", REPOSITORY,
                "--ref", BRANCH,
                "--field", "mode=audit",
                "--field", f"repository={REPOSITORY}",
                "--field", "control=16",
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return Result("HOLD_DISPATCH_OUTCOME_UNKNOWN", False)
    if completed.returncode != 0:
        return Result("HOLD_DISPATCH_DENIED_OR_FAILED", False)
    return Result("REQUEST_SUBMITTED_UNVERIFIED_VERIFY_ACTIONS_RUN", True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed owner-local, no-new-token workflow fallback")
    parser.add_argument("--expected-head", required=True, help="Exactly 40 lowercase hex characters")
    parser.add_argument("--execute", action="store_true", help="Explicitly submit the fixed audit workflow")
    arguments = parser.parse_args(argv)
    outcome = dispatch(arguments.expected_head) if arguments.execute else preflight(arguments.expected_head)
    print(outcome.code)
    return 0 if outcome.success else 2


if __name__ == "__main__":
    sys.exit(main())
