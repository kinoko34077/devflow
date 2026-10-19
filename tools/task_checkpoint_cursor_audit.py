"""Read-only bounded Task Checkpoint Cursor audit (#576).

Use only explicit finite Issue IDs or an independently verified eligibility
catalog. Never infer write authorization or a task's checkpoint from prose.
Does not modify GitHub or trigger workflows.
"""
from __future__ import annotations

import argparse
import hashlib
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

def _open_owner_snapshot(read_transport: object, repository: str, *, max_total: int) -> list[int]:
    """Get a bounded, fully-paginated open owner cohort; never count PRs."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")
    if type(max_total) is not int or not 1 <= max_total <= 500:
        raise ValueError("max_total must be 1..500")
    rows = read_transport.get_paginated(f"/repos/{repository}/issues?state=open&per_page=100")
    if not isinstance(rows, list):
        raise ValueError("incomplete issue discovery")
    ids: list[int] = []
    for row in rows:
        if not isinstance(row, dict) or "number" not in row:
            raise ValueError("invalid discovered issue record")
        if "pull_request" in row:
            continue
        n = row["number"]
        if type(n) is not int or n < 1 or row.get("state", "open") != "open":
            raise ValueError("invalid open owner identity")
        ids.append(n)
        if len(ids) > max_total:
            raise ValueError("open owner issue set exceeds total coverage cap")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate discovered issue identities")
    return sorted(ids)


def _cohort_hash(repository: str, issue_ids: Sequence[int]) -> str:
    data = json.dumps({"repository": repository, "issue_ids": list(issue_ids)},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def audit_open_issue_shards(
    read_transport: object,
    repository: str,
    *,
    max_total: int = 500,
    shard_size: int = 50,
    expected: Mapping[int, str | None] | None = None,
    eligible: Mapping[int, bool] | None = None,
) -> dict[str, object]:
    """GET-only bounded >100 cohort, with strict two-pass discovery consistency.

    All shard reports are built before a complete aggregate is exposed. The
    pre/post GET comparison detects cohort churn, but is not an atomic GitHub
    snapshot; no semantic frontier/eligibility is inferred from formatting.
    """
    if type(shard_size) is not int or not 1 <= shard_size <= 100:
        raise ValueError("shard_size must be 1..100")
    first = _open_owner_snapshot(read_transport, repository, max_total=max_total)
    parts = [first[n:n + shard_size] for n in range(0, len(first), shard_size)]
    reports = []
    for i, ids in enumerate(parts):
        result = audit_issue_ids(
            read_transport, repository, ids, expected=expected, eligible=eligible,
        )
        if result["checked"] != len(ids) or not result["coverage_complete_for_explicit_set"]:
            raise ValueError("incomplete shard inspection")
        reports.append({"index": i, "count": len(ids),
                        "issue_ids": ids, "digest": _cohort_hash(repository, ids),
                        "result": result})
    if _open_owner_snapshot(read_transport, repository, max_total=max_total) != first:
        raise ValueError("open issue cohort changed during scan; discard all shards")
    observed = [row for shard in reports for row in shard["result"]["results"]]
    if len(observed) != len(first) or [
        int(str(row["task"]).rsplit("#", 1)[1]) for row in observed
    ] != first:
        raise ValueError("partial, duplicated or out-of-order shard coverage")
    counts = {status: sum(row["status"] == status for row in observed)
              for status in ("PASS", "NORMALIZABLE", "STALE_FRONTIER",
                             "MISSING_ELIGIBLE", "EXEMPT", "NEEDS_EVIDENCE",
                             "TRUST_CONFLICT")}
    frontier_count = sum(bool(row["frontier_verified"]) for row in observed)
    return {
        "schema": "task-checkpoint-cursor-audit.v1",
        "scope": "complete_open_issue_ids_sharded",
        "repository": repository,
        "checked": len(first),
        "discovery_digest": _cohort_hash(repository, first),
        "discovery_rechecked_identical": True,
        "coverage_complete_for_discovered_set": True,
        "eligibility_independently_supplied": (
            sum(n in eligible for n in first) if eligible is not None else 0
        ),
        "frontiers_independently_verified": frontier_count,
        "semantic_coverage_complete": bool(observed) and frontier_count == len(observed),
        "counts": counts,
        "shards": [{"index": shard["index"], "count": shard["count"],
                    "digest": shard["digest"], "issue_ids": shard["issue_ids"]}
                   for shard in reports],
        "results": observed,
        "mutation": False,
        "snapshot_atomic": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="GET-only bounded Cursor inventory")
    parser.add_argument("--repository", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--issue", type=int, action="append")
    group.add_argument("--discover-open", action="store_true")
    group.add_argument("--discover-open-sharded", action="store_true")
    parser.add_argument("--max-issues", type=int, default=100)
    parser.add_argument("--max-total", type=int, default=500)
    parser.add_argument("--shard-size", type=int, default=50)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        parser.error("GITHUB_TOKEN is required for authenticated read-only discovery")
    from tools.maintenance_github import GitHubReadTransport
    transport = GitHubReadTransport(token=token)
    if args.discover_open_sharded:
        report = audit_open_issue_shards(transport, args.repository,
                                         max_total=args.max_total,
                                         shard_size=args.shard_size)
    else:
        issue_ids = (discover_open_issue_ids(transport, args.repository,
                                             max_issues=args.max_issues)
                     if args.discover_open else args.issue)
        report = audit_issue_ids(transport, args.repository, issue_ids)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
