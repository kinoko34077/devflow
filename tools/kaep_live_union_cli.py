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
from tools.kaep_inbox_reader import InvalidMessage, MARKER, REPOSITORY

MAX_SOURCES = 40
MAX_PUBLIC_MARKER_BYTES = 2_000_000
MAX_PUBLIC_MARKERS = 5000
def _validated_public_marker_hints(data: dict[str, Any]) -> tuple[set[tuple[str, int]], bool]:
    """Untrusted public-owner marker candidate *locations*, not messages.

    Source content is never trusted as routing, recipient, actor or authority.
    """
    if (type(data) is not dict
            or data.get("schema_version") not in (
                "kaep.public-marker-incremental.v0.1",
                "kaep.public-marker-locators.v0.1")
            or data.get("status") not in (
                "BOUNDED_INCREMENTAL_BASELINE", "BOUNDED_INCREMENTAL_READ",
                "BOUNDED_PUBLIC_MARKER_READ", "PARTIAL_UNKNOWN")
            or data.get("owner") != "kinoko34077"
            or data.get("public_only") is not True
            or data.get("can_authorize_execution") is not False
            or data.get("complete_source_universe") is not False
            or type(data.get("locators")) is not list
            or len(data["locators"]) > MAX_PUBLIC_MARKERS):
        _deny("INVALID_MARKER_SOURCE")
    found: set[tuple[str, int]] = set()
    for row in data["locators"]:
        if type(row) is not dict:
            _deny("INVALID_MARKER_LOCATOR")
        repo, number, cid = (
            row.get("repository"), row.get("issue_number"), row.get("comment_id"))
        if (type(repo) is not str or not REPOSITORY.fullmatch(repo)
                or type(number) is not int or number <= 0
                or type(cid) is not int or cid <= 0
                or row.get("locator") != f"{repo.split('/', 1)[1]}#{number}@{cid}"
                or row.get("source_url") !=
                  f"https://github.com/{repo}/issues/{number}#issuecomment-{cid}"
                or row.get("strict_source_validated") is not False
                or row.get("is_authoritative_assignment") is not False):
            _deny("INVALID_MARKER_LOCATOR")
        found.add((repo, number))
    return found, data["status"] == "PARTIAL_UNKNOWN"


RECIPIENTS = cached.RECIPIENTS


def _deny(code: str) -> None:
    raise InvalidMessage(code)


def _recent_issue_keys(
    repo: str, comments: list[dict[str, Any]],
) -> set[tuple[str, int]]:
    """Untrusted markers supply locators ONLY. Strict codec runs afterwards."""
    if type(comments) is not list or len(comments) > delta.MAX_WINDOW * delta.MAX_UPDATED_PAGES:
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
    additional_repositories: tuple[str, ...] = (),
    public_marker_discovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recheck one deduplicated cohort in canonical original sources.

    No latest-comment window can establish a complete history: old, entirely
    unindexed roots and Issue-only changes remain unknown.
    """
    if recipient not in RECIPIENTS:
        _deny("INVALID_RECIPIENT")
    info = cached.validate_index(snapshot)
    # Extra repositories are an explicit caller-selected scope, never
    # discovered or authorized by untrusted public index rows.
    if (type(additional_repositories) is not tuple
            or any(type(r) is not str or not REPOSITORY.fullmatch(r)
                   for r in additional_repositories)
            or len(additional_repositories) != len(set(additional_repositories))
            or any(r in snapshot["repositories"] for r in additional_repositories)
            or len(snapshot["repositories"]) + len(additional_repositories)
               > delta.MAX_REPOSITORIES):
        _deny("INVALID_ADDITIONAL_REPOSITORY_SET")
    repos = list(snapshot["repositories"]) + list(additional_repositories)
    if public_marker_discovery is None:
        public_marker_keys: set[tuple[str, int]] = set()
        marker_partial = False
    else:
        public_marker_keys, marker_partial = _validated_public_marker_hints(
            public_marker_discovery)
    marker_in_scope = public_marker_keys.intersection(
        {(repo, issue) for repo, issue in public_marker_keys if repo in repos})
    marker_out_of_scope = public_marker_keys - marker_in_scope
    indexed_rows = [r for r in snapshot["rows"] if r["recipient"] == recipient]
    indexed_sources = {(r["repository"], r["issue_number"]) for r in indexed_rows}
    indexed_by_key = {
        (r["repository"], r["issue_number"], r["source_comment_id"], r["message_id"]): r
        for r in indexed_rows
    }
    recent_sources: set[tuple[str, int]] = set()
    counts: dict[str, int] = {}
    updated_pages_read: dict[str, int] = {}
    warnings: list[dict[str, str]] = []
    for repo in repos:
        raw = recent_read(repo, since=since)
        if type(raw) is dict:
            comments = raw.get("comments")
            truncated = raw.get("truncated")
            page_count = raw.get("read_pages")
            overlap = raw.get("page_boundary_overlap_count")
            page_limit = raw.get("page_limit")
            if (type(comments) is not list
                    or type(truncated) is not bool
                    or type(page_count) is not int or not 1 <= page_count <= delta.MAX_UPDATED_PAGES
                    or type(page_limit) is not int or page_count > page_limit
                    or page_limit > delta.MAX_UPDATED_PAGES
                    or type(overlap) is not int or overlap < 0
                    or len(comments) > page_count * delta.MAX_WINDOW):
                _deny("INVALID_UPDATED_PAGE_RESULT")
            if overlap:
                warnings.append({"repository": repo, "reason_code": "UPDATED_PAGE_BOUNDARY_OVERLAP"})
        else:
            comments = raw
            if type(comments) is not list or len(comments) > delta.MAX_WINDOW:
                _deny("INVALID_LIVE_WINDOW")
            truncated = len(comments) == delta.MAX_WINDOW
            page_count = 1
        counts[repo] = len(comments)
        updated_pages_read[repo] = page_count
        recent_sources.update(_recent_issue_keys(repo, comments))
        if truncated:
            warnings.append({"repository": repo, "reason_code": "RECENT_WINDOW_TRUNCATED"})

    all_sources = sorted(indexed_sources | recent_sources | marker_in_scope)
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
            "incremental_marker_observed": (repo, number) in marker_in_scope,
            "source_origin": (
                "BOTH" if (repo, number) in indexed_sources and
                          (repo, number) in recent_sources else
                "INDEXED_SOURCE" if (repo, number) in indexed_sources else
                "LATEST_COMMENT_SOURCE" if (repo, number) in recent_sources else
                "INCREMENTAL_MARKER_SOURCE"
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
            "incremental_marker_observed": (repo, number) in marker_in_scope,
            "origin": (
                "BOTH" if (repo, number) in indexed_sources
                          and (repo, number) in recent_sources else
                "INDEXED_SOURCE" if (repo, number) in indexed_sources
                else "LATEST_COMMENT_SOURCE" if (repo, number) in recent_sources
                else "INCREMENTAL_MARKER_SOURCE"
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
        or marker_partial or bool(marker_out_of_scope)
    )
    return {
        "schema_version": "kaep.live-union-check.v0.1",
        "status": "PARTIAL_UNKNOWN" if partial else "BOUNDED_UNION_READ",
        "kind": "REQUEST_TIME_ORIGINAL_ISSUE_UNION",
        "recipient": recipient, "observed_at": verified["observed_at"],
        "snapshot_observed_at": snapshot["observed_at"],
        "repositories_checked": list(repos),
        "explicit_additional_repositories": list(additional_repositories),
        "repository_scope_proven_complete": False,
        **info,
        "recent_comments_observed": counts,
        "updated_comment_pages_read": updated_pages_read,
        "window_limit_per_repository": delta.MAX_WINDOW,
        "indexed_issue_count": len(indexed_sources),
        "recent_marker_issue_count": len(recent_sources),
        "source_issue_count": len(all_sources),
        "public_marker_discovery_used": public_marker_discovery is not None,
        "public_marker_issue_count_in_scope": len(marker_in_scope),
        "public_marker_issue_count_out_of_scope": len(marker_out_of_scope),
        "public_marker_source_partial": marker_partial,
        "public_marker_source_untrusted": True,
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
    parser.add_argument("--additional-repository", action="append", default=[],
                        help="Explicit owner-managed repository to read (max 3 total)")
    parser.add_argument("--offline-index", type=Path)
    parser.add_argument("--public-marker-discovery", type=Path,
                        help="Optional bounded untrusted public marker JSON; canonical Issues are revalidated")
    parser.add_argument("--since", default=None)
    parser.add_argument("--updated-pages", type=int, default=1,
                        choices=range(1, delta.MAX_UPDATED_PAGES + 1),
                        help="Opt-in bounded updated-desc GitHub comment pages (default: 1)")
    args = parser.parse_args(argv)
    try:
        if args.offline_index is None:
            index = cached.fetch_public_json()
        else:
            raw = args.offline_index.read_bytes()
            if len(raw) > cached.MAX_INDEX_BYTES:
                _deny("PUBLIC_INDEX_TOO_LARGE")
            index = json.loads(raw.decode("utf-8"), object_pairs_hook=cached._unique_pairs)
        public_markers = None
        if args.public_marker_discovery is not None:
            raw = args.public_marker_discovery.read_bytes()
            if len(raw) > MAX_PUBLIC_MARKER_BYTES:
                _deny("PUBLIC_MARKER_FILE_TOO_LARGE")
            public_markers = json.loads(raw.decode("utf-8"),
                                        object_pairs_hook=cached._unique_pairs)
        if args.updated_pages == 1:
            recent_reader = delta.read_repository_recent
        else:
            def recent_reader(repository: str, *, since: str | None = None):
                return delta.read_repository_updated_pages(
                    repository, since=since, max_pages=args.updated_pages)
        result = read_union(
            index, recipient=args.recipient, since=args.since,
            recent_read=recent_reader,
            additional_repositories=tuple(args.additional_repository),
            public_marker_discovery=public_markers)
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
