"""Read-only bounded Task Checkpoint Cursor audit (#576).

Use only explicit finite Issue IDs or an independently verified eligibility
catalog. Never infer write authorization or a task's checkpoint from prose.
Does not modify GitHub or trigger workflows.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Mapping, Sequence

from tools.task_checkpoint_cursor import inspect_cursor_comments


def classify_cursor(
    task: str,
    comments: Sequence[Mapping[str, object]],
    *,
    eligible: bool | None = None,
    verified_first_unfinished: str | None | object = ...,  # unspecified != terminal
) -> dict[str, object]:
    observed = inspect_cursor_comments(comments, task)
    result: dict[str, object] = {
        "task": task, "status": "NEEDS_EVIDENCE",
        "cursor_code": observed.code,
        "warnings": list(observed.warnings),
        "first_unfinished": None,
        "revision": None,
    }
    if observed.code == "NO_MARKER":
        result["status"] = (
            "EXEMPT" if eligible is False else
            "MISSING_ELIGIBLE" if eligible is True else "NEEDS_EVIDENCE"
        )
    elif observed.code != "OK_CURSOR" or observed.cursor is None:
        result["status"] = "TRUST_CONFLICT" if observed.code in (
            "WARN_DUPLICATE_MARKER", "WARN_MALFORMED_MARKER") else "NEEDS_EVIDENCE"
    else:
        c = observed.cursor
        result["revision"] = c.revision
        result["first_unfinished"] = c.first_unfinished
        result["status"] = "NORMALIZABLE" if observed.warnings else "PASS"
        if verified_first_unfinished is not ... and c.first_unfinished != verified_first_unfinished:
            result["status"] = "STALE_FRONTIER"
            result["warnings"] = list(observed.warnings) + ["WARN_CHECKPOINT_DRIFT"]
    return result


def audit_issue_ids(
    read_transport: object, repository: str, issue_ids: Sequence[int],
    *,
    expected: Mapping[int, str | None] | None = None,
    eligible: Mapping[int, bool] | None = None,
) -> dict[str, object]:
    """Bounded API GET collector; issue/pr and comment pages must be complete."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")
    if len(issue_ids) > 100 or len(set(issue_ids)) != len(issue_ids):
        raise ValueError("bounded unique Issue set required (<=100)")
    results = []
    for n in issue_ids:
        if type(n) is not int or n < 1:
            raise ValueError("invalid issue number")
        owner = read_transport.get_json(f"/repos/{repository}/issues/{n}")
        if not isinstance(owner, dict) or owner.get("number") != n or "pull_request" in owner:
            raise ValueError("unexpected Issue identity")
        comments = read_transport.get_paginated(f"/repos/{repository}/issues/{n}/comments?per_page=100")
        if not isinstance(comments, list):
            raise ValueError("incomplete comments")
        kwargs: dict[str, Any] = {"eligible": (eligible or {}).get(n)}
        if expected is not None and n in expected:
            kwargs["verified_first_unfinished"] = expected[n]
        row = classify_cursor(f"{repository}#{n}", comments, **kwargs)
        row["url"] = owner.get("html_url")
        results.append(row)
    counts = {name: sum(row["status"] == name for row in results) for name in (
        "PASS", "NORMALIZABLE", "STALE_FRONTIER", "MISSING_ELIGIBLE",
        "EXEMPT", "NEEDS_EVIDENCE", "TRUST_CONFLICT")}
    return {"schema": "task-checkpoint-cursor-audit.v1", "repository": repository,
            "scope": "explicit_issue_ids_only", "checked": len(results),
            "coverage_complete_for_explicit_set": True, "counts": counts, "results": results,
            "mutation": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="GET-only bounded Cursor inventory")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", type=int, action="append", required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        parser.error("GITHUB_TOKEN is required for authenticated read-only discovery")
    from tools.maintenance_github import GitHubReadTransport
    transport = GitHubReadTransport(token=token)
    report = audit_issue_ids(transport, args.repository, args.issue)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
