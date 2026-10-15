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
        "frontier_verified": verified_first_unfinished is not ...,
    }
    # An untrusted marker is an identity/provenance anomaly, not
    # presentation drift. Never call it NORMALIZABLE or recommend blind
    # initialization of a new trusted marker on that evidence.
    unsafe_marker = "WARN_UNTRUSTED_MARKER" in observed.warnings
    if observed.code == "NO_MARKER":
        result["status"] = (
            "TRUST_CONFLICT" if unsafe_marker else
            "EXEMPT" if eligible is False else
            "MISSING_ELIGIBLE" if eligible is True else "NEEDS_EVIDENCE"
        )
    elif observed.code != "OK_CURSOR" or observed.cursor is None:
        result["status"] = "TRUST_CONFLICT" if observed.code in (
            "WARN_DUPLICATE_MARKER", "WARN_MALFORMED_MARKER") or unsafe_marker else "NEEDS_EVIDENCE"
    else:
        c = observed.cursor
        result["revision"] = c.revision
        result["first_unfinished"] = c.first_unfinished
        result["status"] = (
            "TRUST_CONFLICT" if unsafe_marker else
            "NORMALIZABLE" if observed.warnings and all(w in (
                "WARN_NORMALIZED", "WARN_IGNORED_ANNOTATION") for w in observed.warnings)
            else "NEEDS_EVIDENCE" if observed.warnings else "PASS"
        )
        if verified_first_unfinished is not ... and c.first_unfinished != verified_first_unfinished:
            # Record semantic drift without hiding an existing provenance
            # conflict; the latter requires trusted-human reconciliation first.
            if result["status"] != "TRUST_CONFLICT":
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
    semantic_verified = sum(bool(row["frontier_verified"]) for row in results)
    counts = {name: sum(row["status"] == name for row in results) for name in (
        "PASS", "NORMALIZABLE", "STALE_FRONTIER", "MISSING_ELIGIBLE",
        "EXEMPT", "NEEDS_EVIDENCE", "TRUST_CONFLICT")}
    return {"schema": "task-checkpoint-cursor-audit.v1", "repository": repository,
            "scope": "explicit_issue_ids_only", "checked": len(results),
            "coverage_complete_for_explicit_set": True,
            "frontiers_independently_verified": semantic_verified,
            "semantic_coverage_complete": semantic_verified == len(results),
            "counts": counts, "results": results,
            "mutation": False}



def discover_open_issue_ids(read_transport: object, repository: str, *, max_issues: int = 100) -> list[int]:
    """Discover *all* open owner Issues within a hard bounded limit.

    No silent truncated-pool PASS: oversized fleets need repository-scoped
    partitioning or an explicitly larger reviewed budget.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")
    if not 1 <= max_issues <= 100:
        raise ValueError("max_issues must be 1..100")
    rows = read_transport.get_paginated(f"/repos/{repository}/issues?state=open&per_page=100")
    if not isinstance(rows, list):
        raise ValueError("incomplete issue discovery")
    owners = [row for row in rows if isinstance(row, dict) and "pull_request" not in row]
    if len(owners) > max_issues:
        raise ValueError("issue set exceeds capped coverage; no partial PASS")
    ids = []
    for row in owners:
        n = row.get("number")
        if type(n) is not int or n < 1:
            raise ValueError("invalid discovered issue identity")
        ids.append(n)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate discovered issue identities")
    return ids

def main() -> int:
    parser = argparse.ArgumentParser(description="GET-only bounded Cursor inventory")
    parser.add_argument("--repository", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--issue", type=int, action="append")
    group.add_argument("--discover-open", action="store_true")
    parser.add_argument("--max-issues", type=int, default=100)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        parser.error("GITHUB_TOKEN is required for authenticated read-only discovery")
    from tools.maintenance_github import GitHubReadTransport
    transport = GitHubReadTransport(token=token)
    issue_ids = (discover_open_issue_ids(transport, args.repository, max_issues=args.max_issues)
                 if args.discover_open else args.issue)
    report = audit_issue_ids(transport, args.repository, issue_ids)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
