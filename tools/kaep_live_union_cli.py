"""B6 RT4 read-only union of published source locators and live GitHub changes.

Already-active agents can check both older indexed roots and newly updated
KAEP Issues in one bounded strict original-Issue validation pass. Never a
complete work queue, model wake signal or execution authorization.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable

from tools import kaep_live_candidate_cli as cached
from tools import kaep_live_delta_view as delta
from tools import kaep_issue_search_view as strict
from tools.kaep_inbox_reader import InvalidMessage, MARKER

MAX_SOURCES = 40
RECIPIENTS = cached.RECIPIENTS


def _deny(code: str) -> None:
    raise InvalidMessage(code)


def _recent_issue_keys(
    repo: str, comments: list[dict[str, Any]],
) -> set[tuple[str, int]]:
    """Untrusted markers supply locators ONLY. Strict codec runs afterwards."""
    if type(comments) is not list or len(comments) > delta.MAX_WINDOW:
        _deny("INVALID_LIVE_WINDOW")
    sources: set[tuple[str, int]] = set()
    for comment in comments:
        if type(comment) is not dict:
            _deny("INVALID_LIVE_COMMENT")
        author = comment.get("user")
        body, cid, url = (
            comment.get("body"), comment.get("id"), comment.get("issue_url"),
        )
        if (type(body) is not str or type(cid) is not int or cid <= 0
                or type(author) is not dict
                or type(author.get("login")) is not str):
            _deny("INVALID_LIVE_COMMENT")
        matched = delta.API_ISSUE.fullmatch(url) if type(url) is str else None
        if not matched or matched.group(1) != repo:
            _deny("INVALID_LIVE_ISSUE_LOCATOR")
        if body.startswith(MARKER):
            sources.add((repo, int(matched.group(2))))
    return sources


def read_union(
    snapshot: dict[str, Any], *, recipient: str,
    recent_read: Callable[..., list[dict[str, Any]]] = delta.read_repository_recent,
    issue_read: Callable[[str, int], dict[str, Any]] = strict.fetch_issue,
    comments_read: Callable[[str, int], str] = strict.fetch_gh_pages,
    since: str | None = None,
) -> dict[str, Any]:
    """Recheck one deduplicated cohort in canonical original sources.

    No latest-comment window can establish a complete history: old, entirely
    unindexed roots and Issue-only changes remain unknown.
    """
    if recipient not in RECIPIENTS:
        _deny("INVALID_RECIPIENT")
    info = cached.validate_index(snapshot)
    repos = snapshot["repositories"]
    indexed_rows = [r for r in snapshot["rows"] if r["recipient"] == recipient]
    indexed_sources = {(r["repository"], r["issue_number"]) for r in indexed_rows}
    indexed_by_key = {
        (r["repository"], r["issue_number"], r["source_comment_id"], r["message_id"]): r
        for r in indexed_rows
    }
    recent_sources: set[tuple[str, int]] = set()
    counts: dict[str, int] = {}
    warnings: list[dict[str, str]] = []
    for repo in repos:
        comments = recent_read(repo, since=since)
        counts[repo] = len(comments) if type(comments) is list else -1
        recent_sources.update(_recent_issue_keys(repo, comments))
        if len(comments) == delta.MAX_WINDOW:
            warnings.append({"repository": repo, "reason_code": "RECENT_WINDOW_TRUNCATED"})

    all_sources = sorted(indexed_sources | recent_sources)
    # A cap cannot silently drop a known source. Fail closed and retain fallback.
    if len(all_sources) > MAX_SOURCES:
        _deny("UNION_SOURCE_LIMIT")
    locators: dict[str, dict[str, Any]] = {}
    for repo in repos:
        subset = [
            {"html_url": f"https://github.com/{r}/issues/{issue}"}
            for r, issue in all_sources if r == repo
        ]
        locators[repo] = {
            "items": subset, "total_count": len(subset),
            "incomplete_results": False,
        }
    verified = strict.build_search_list(
        repos, locators, fetch_original_issue=issue_read,
        fetch_comments=comments_read, expected_actor="kinoko34077",
        recipient=recipient, max_candidates=MAX_SOURCES,
    )
    current_by_key = {
        (r["repository"], r["issue_number"], r["source_comment_id"], r["message_id"]): r
        for r in verified["rows"]
    }
    out_rows: list[dict[str, Any]] = []
    state_changes = 0
    for key, row in sorted(current_by_key.items()):
        repo, number = key[:2]
        old = indexed_by_key.get(key)
        changed = bool(old and (
            (old.get("issue_state") is not None and old["issue_state"] != row["issue_state"])
            or (old.get("reply_observation") is not None
                and old["reply_observation"] != row["reply_observation"])))
        state_changes += changed
        out_rows.append({
            "repository": repo, "issue_number": number,
            "issue_url": row["issue_url"], "source_url": row["source_url"],
            "source_comment_id": row["source_comment_id"],
            "message_id": row["message_id"],
            "recipient": recipient,
            "issue_state": row["issue_state"],
            "reply_observation": row["reply_observation"],
            "source_validation": row["source_validation"],
            "head_freshness": "NOT_REVALIDATED",
            "source_origin": (
                "BOTH" if (repo, number) in indexed_sources and
                          (repo, number) in recent_sources else
                "INDEXED_SOURCE" if (repo, number) in indexed_sources else
                "LATEST_COMMENT_SOURCE"
            ),
            "changed_from_snapshot": changed,
            "index_presence": "INDEXED_AND_LIVE" if old else "LIVE_ORIGINAL_ONLY",
        })
    # Candidate locators must be visible even when this recipient has zero
    # accepted roots. A locator is a read hint, never a delivered assignment.
    roots_by_issue: dict[tuple[str, int], int] = {}
    for row in out_rows:
        key = (row["repository"], row["issue_number"])
        roots_by_issue[key] = roots_by_issue.get(key, 0) + 1
    failed_issues = {
        err.get("owning_issue") for err in verified["errors"]
        if type(err) is dict and type(err.get("owning_issue")) is str
    }
    global_unknown = any(
        type(err) is not dict or not err.get("owning_issue")
        for err in verified["errors"]
    )
    candidates = []
    for repo, number in all_sources:
        source_url = f"https://github.com/{repo}/issues/{number}"
        count = roots_by_issue.get((repo, number), 0)
        suspect = global_unknown or source_url in failed_issues
        candidates.append({
            "repository": repo,
            "issue_number": number,
            "issue_url": source_url,
            "origin": (
                "BOTH" if (repo, number) in indexed_sources
                          and (repo, number) in recent_sources else
                "INDEXED_SOURCE" if (repo, number) in indexed_sources
                else "LATEST_COMMENT_SOURCE"
            ),
            "matching_recipient_roots": count,
            "source_observation": (
                "SOURCE_VALIDATION_UNKNOWN" if suspect else
                "ACCEPTED_RECIPIENT_ROOTS" if count else
                "NO_ACCEPTED_RECIPIENT_ROOT_OBSERVED"
            ),
            "grants_work_authority": False,
        })

    removed = set(indexed_by_key) - set(current_by_key)
    partial = bool(
        snapshot["status"] != "BOUNDED_SEARCH_READ"
        or verified["status"] != "BOUNDED_SEARCH_READ"
        or verified["errors"] or warnings or removed
    )
    return {
        "schema_version": "kaep.live-union-check.v0.1",
        "status": "PARTIAL_UNKNOWN" if partial else "BOUNDED_UNION_READ",
        "kind": "REQUEST_TIME_ORIGINAL_ISSUE_UNION",
        "recipient": recipient, "observed_at": verified["observed_at"],
        "snapshot_observed_at": snapshot["observed_at"],
        **info,
        "recent_comments_observed": counts,
        "window_limit_per_repository": delta.MAX_WINDOW,
        "indexed_issue_count": len(indexed_sources),
        "recent_marker_issue_count": len(recent_sources),
        "source_issue_count": len(all_sources),
        "source_candidates": candidates,
        "live_original_roots": len(out_rows),
        "new_unindexed_source_issues": len(recent_sources - indexed_sources),
        "new_in_originals": len(set(current_by_key) - set(indexed_by_key)),
        "state_or_reply_changes_from_snapshot": state_changes,
        "cached_rows_not_verified_live": len(removed),
        "live_rows": out_rows,
        "source_errors": [
            {"reason_code": x.get("reason_code", "UNKNOWN"),
             "issue_url": x.get("owning_issue")}
            for x in verified["errors"]
        ],
        "warnings": warnings,
        "source_coverage": "BOUNDED_INDEX_PLUS_LATEST_COMMENTS_NOT_COMPLETE",
        "has_unknown_work": True,
        "complete_source_universe": False,
        "absence_of_work_proven": False,
        "recipient_pickup_proven": False,
        "can_authorize_execution": False,
        "current_head_verified": False,
        "fallback_retirement_authorized": False,
        "requires_action_level_authorization": True,
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", choices=sorted(RECIPIENTS), required=True)
    parser.add_argument("--offline-index", type=Path)
    parser.add_argument("--since", default=None)
    args = parser.parse_args(argv)
    try:
        if args.offline_index is None:
            index = cached.fetch_public_json()
        else:
            raw = args.offline_index.read_bytes()
            if len(raw) > cached.MAX_INDEX_BYTES:
                _deny("PUBLIC_INDEX_TOO_LARGE")
            index = json.loads(raw.decode("utf-8"), object_pairs_hook=cached._unique_pairs)
        result = read_union(index, recipient=args.recipient, since=args.since)
    except (InvalidMessage, OSError, ValueError, UnicodeError, TypeError) as exc:
        result = {
            "schema_version": "kaep.live-union-check.v0.1",
            "status": "BLOCKED",
            "reason_code": str(exc) if isinstance(exc, InvalidMessage) else "UNION_READ_UNAVAILABLE",
            "has_unknown_work": True, "complete_source_universe": False,
            "can_authorize_execution": False, "fallback_retirement_authorized": False,
            "read_only": True,
        }
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0 if result["status"] == "BOUNDED_UNION_READ" else 2


if __name__ == "__main__":
    sys.exit(main())
