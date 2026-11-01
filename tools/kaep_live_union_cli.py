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


MAX_PREVIOUS_REPORT_BYTES = 2_000_000
MAX_PREVIOUS_ROWS = 5000


def _validated_previous_report(
    data: dict[str, Any], *, recipient: str, repositories: list[str],
) -> tuple[set[tuple[str, int]], dict[tuple[str, int, int, str], dict[str, str]], bool]:
    """Admit *locators* and self-reported old state, NEVER prior authority.

    Every candidate is fetched again through the existing original-Issue
    verification pipeline. This is not an authenticated or durable cursor.
    """
    if (type(data) is not dict
            or data.get("schema_version") != "kaep.live-union-check.v0.1"
            or data.get("status") not in ("BOUNDED_UNION_READ", "PARTIAL_UNKNOWN")
            or data.get("recipient") != recipient
            or data.get("repositories_checked") != repositories
            or data.get("read_only") is not True
            or data.get("has_unknown_work") is not True
            or data.get("complete_source_universe") is not False
            or data.get("can_authorize_execution") is not False
            or data.get("recipient_pickup_proven") is not False
            or type(data.get("source_candidates")) is not list
            or not len(data["source_candidates"]) <= MAX_SOURCES
            or type(data.get("live_rows")) is not list
            or len(data["live_rows"]) > MAX_PREVIOUS_ROWS):
        _deny("INVALID_PREVIOUS_UNION_REPORT")
    sources: set[tuple[str, int]] = set()
    for row in data["source_candidates"]:
        if type(row) is not dict:
            _deny("INVALID_PREVIOUS_SOURCE")
        repo, number = row.get("repository"), row.get("issue_number")
        if (type(repo) is not str or not REPOSITORY.fullmatch(repo)
                or repo not in repositories or type(number) is not int
                or number <= 0 or row.get("issue_url")
                != f"https://github.com/{repo}/issues/{number}"
                or row.get("grants_work_authority") is not False
                or (repo, number) in sources):
            _deny("INVALID_PREVIOUS_SOURCE")
        sources.add((repo, number))
    old: dict[tuple[str, int, int, str], dict[str, str]] = {}
    for row in data["live_rows"]:
        if type(row) is not dict:
            _deny("INVALID_PREVIOUS_ROOT")
        repo, issue, cid, mid = (
            row.get("repository"), row.get("issue_number"),
            row.get("source_comment_id"), row.get("message_id"),
        )
        key = (repo, issue, cid, mid)
        if (type(repo) is not str or type(issue) is not int
                or (repo, issue) not in sources
                or type(cid) is not int or cid <= 0
                or type(mid) is not str
                or re.fullmatch(r"msg_[A-Za-z0-9_-]{1,72}", mid) is None
                or row.get("recipient") != recipient
                or row.get("issue_url") != f"https://github.com/{repo}/issues/{issue}"
                or row.get("source_url") !=
                   f"https://github.com/{repo}/issues/{issue}#issuecomment-{cid}"
                or row.get("issue_state") not in ("open", "closed")
                or type(row.get("reply_observation")) is not str
                or key in old):
            _deny("INVALID_PREVIOUS_ROOT")
        old[key] = {
            "issue_state": row["issue_state"],
            "reply_observation": row["reply_observation"],
        }
    return sources, old, data["status"] == "PARTIAL_UNKNOWN"

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


def _collect_recent_source_hints(
    repositories: list[str], *,
    recent_read: Callable[..., list[dict[str, Any]]], since: str | None,
) -> tuple[
    set[tuple[str, int]], dict[str, int], dict[str, int], list[dict[str, str]]
]:
    """Interpret bounded updated-comment windows as untrusted source *hints*.

    Keep pagination uncertainty and warning ordering at this boundary.
    This function never validates original sources or grants a work assignment.
    """
    recent_sources: set[tuple[str, int]] = set()
    counts: dict[str, int] = {}
    updated_pages_read: dict[str, int] = {}
    warnings: list[dict[str, str]] = []
    for repo in repositories:
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
    return recent_sources, counts, updated_pages_read, warnings


def _source_origin(
    repo: str, number: int, *,
    indexed_sources: set[tuple[str, int]],
    recent_sources: set[tuple[str, int]],
    marker_in_scope: set[tuple[str, int]],
) -> str:
    """Choose the same precedence for verified roots and locator candidates.

    A provenance label is descriptive only: no trust, coverage or authority.
    """
    key = (repo, number)
    if key in indexed_sources and key in recent_sources:
        return "BOTH"
    if key in indexed_sources:
        return "INDEXED_SOURCE"
    if key in recent_sources:
        return "LATEST_COMMENT_SOURCE"
    if key in marker_in_scope:
        return "INCREMENTAL_MARKER_SOURCE"
    return "PREVIOUS_REPORT_SOURCE"


def _build_source_candidate_ledger(
    sources: list[tuple[str, int]], *, verified_rows: list[dict[str, Any]],
    source_errors: list[Any], indexed_sources: set[tuple[str, int]],
    recent_sources: set[tuple[str, int]],
    marker_in_scope: set[tuple[str, int]],
) -> list[dict[str, Any]]:
    """Show every bounded locator, without claiming a delivered assignment.

    Candidate visibility and uncertainty are a display contract separate from
    recipient root verification: a source with no matching roots still appears.
    Global source uncertainty dominates issue-specific observations.
    """
    roots_by_issue: dict[tuple[str, int], int] = {}
    for row in verified_rows:
        key = (row["repository"], row["issue_number"])
        roots_by_issue[key] = roots_by_issue.get(key, 0) + 1
    failed_issues = {
        err.get("owning_issue") for err in source_errors
        if type(err) is dict and type(err.get("owning_issue")) is str
    }
    global_unknown = any(
        type(err) is not dict or not err.get("owning_issue")
        for err in source_errors
    )
    candidates = []
    for repo, number in sources:
        source_url = f"https://github.com/{repo}/issues/{number}"
        count = roots_by_issue.get((repo, number), 0)
        suspect = global_unknown or source_url in failed_issues
        candidates.append({
            "repository": repo,
            "issue_number": number,
            "issue_url": source_url,
            "incremental_marker_observed": (repo, number) in marker_in_scope,
            "origin": _source_origin(
                repo, number, indexed_sources=indexed_sources,
                recent_sources=recent_sources, marker_in_scope=marker_in_scope,
            ),
            "matching_recipient_roots": count,
            "source_observation": (
                "SOURCE_VALIDATION_UNKNOWN" if suspect else
                "ACCEPTED_RECIPIENT_ROOTS" if count else
                "NO_ACCEPTED_RECIPIENT_ROOT_OBSERVED"
            ),
            "grants_work_authority": False,
        })
    return candidates


def _project_verified_union_rows(
    current_by_key: dict[tuple[str, int, int, str], dict[str, Any]], *,
    indexed_by_key: dict[tuple[str, int, int, str], dict[str, Any]],
    prior_rows: dict[tuple[str, int, int, str], dict[str, str]],
    recipient: str,
    indexed_sources: set[tuple[str, int]],
    recent_sources: set[tuple[str, int]],
    marker_in_scope: set[tuple[str, int]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Project strict verified roots and compare two different baselines.

    A search-index snapshot may omit earlier state/observation fields, while
    a validated previous report supplies both. Do not unify their semantics.
    No Issue read, mailbox decode, authority decision or report status here.
    """
    out_rows: list[dict[str, Any]] = []
    state_changes = 0
    previous_changes = 0
    for key, row in sorted(current_by_key.items()):
        repo, number = key[:2]
        old = indexed_by_key.get(key)
        changed = bool(old and (
            (old.get("issue_state") is not None and old["issue_state"] != row["issue_state"])
            or (old.get("reply_observation") is not None
                and old["reply_observation"] != row["reply_observation"])))
        state_changes += changed
        previous = prior_rows.get(key)
        changed_previous = bool(previous and (
            previous["issue_state"] != row["issue_state"]
            or previous["reply_observation"] != row["reply_observation"]))
        previous_changes += changed_previous
        out_rows.append({
            "changed_from_previous_report": changed_previous,
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
            "source_origin": _source_origin(
                repo, number, indexed_sources=indexed_sources,
                recent_sources=recent_sources, marker_in_scope=marker_in_scope,
            ),
            "changed_from_snapshot": changed,
            "index_presence": "INDEXED_AND_LIVE" if old else "LIVE_ORIGINAL_ONLY",
        })
    return out_rows, state_changes, previous_changes


def read_union(
    snapshot: dict[str, Any], *, recipient: str,
    recent_read: Callable[..., list[dict[str, Any]]] = delta.read_repository_recent,
    issue_read: Callable[[str, int], dict[str, Any]] = strict.fetch_issue,
    comments_read: Callable[[str, int], str] = strict.fetch_gh_pages,
    since: str | None = None,
    additional_repositories: tuple[str, ...] = (),
    public_marker_discovery: dict[str, Any] | None = None,
    previous_report: dict[str, Any] | None = None,
    scoped_repository: str | None = None,
) -> dict[str, Any]:
    """Recheck one deduplicated cohort in canonical original sources.

    No latest-comment window can establish a complete history: old, entirely
    unindexed roots and Issue-only changes remain unknown.
    """
    if recipient not in RECIPIENTS:
        _deny("INVALID_RECIPIENT")
    info = cached.validate_index(snapshot)
    # Optional Workspace consumer scope is a strict subset of a fully validated
    # public snapshot (or one explicitly requested extra repo). No other
    # repository's original Issue is read or returned.
    if scoped_repository is not None and (
        type(scoped_repository) is not str
        or not REPOSITORY.fullmatch(scoped_repository)
        or additional_repositories
        or public_marker_discovery is not None
        or previous_report is not None
    ):
        _deny("INVALID_SCOPED_REPOSITORY")
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
    if scoped_repository is None:
        repos = list(snapshot["repositories"]) + list(additional_repositories)
        effective_additional = list(additional_repositories)
    else:
        repos = [scoped_repository]
        effective_additional = (
            [scoped_repository] if scoped_repository not in snapshot["repositories"]
            else []
        )
    if public_marker_discovery is None:
        public_marker_keys: set[tuple[str, int]] = set()
        marker_partial = False
    else:
        public_marker_keys, marker_partial = _validated_public_marker_hints(
            public_marker_discovery)
    marker_in_scope = public_marker_keys.intersection(
        {(repo, issue) for repo, issue in public_marker_keys if repo in repos})
    marker_out_of_scope = public_marker_keys - marker_in_scope
    if previous_report is None:
        prior_source_keys: set[tuple[str, int]] = set()
        prior_rows: dict[tuple[str, int, int, str], dict[str, str]] = {}
        previous_partial = False
    else:
        prior_source_keys, prior_rows, previous_partial = _validated_previous_report(
            previous_report, recipient=recipient, repositories=repos)
    indexed_rows = [
        r for r in snapshot["rows"]
        if r["recipient"] == recipient and r["repository"] in repos
    ]
    indexed_sources = {(r["repository"], r["issue_number"]) for r in indexed_rows}
    indexed_by_key = {
        (r["repository"], r["issue_number"], r["source_comment_id"], r["message_id"]): r
        for r in indexed_rows
    }
    recent_sources, counts, updated_pages_read, warnings = (
        _collect_recent_source_hints(
            repos, recent_read=recent_read, since=since,
        )
    )

    all_sources = sorted(indexed_sources | recent_sources | marker_in_scope | prior_source_keys)
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
        source_workers=2,
    )
    current_by_key = {
        (r["repository"], r["issue_number"], r["source_comment_id"], r["message_id"]): r
        for r in verified["rows"]
    }
    out_rows, state_changes, previous_changes = _project_verified_union_rows(
        current_by_key,
        indexed_by_key=indexed_by_key, prior_rows=prior_rows,
        recipient=recipient, indexed_sources=indexed_sources,
        recent_sources=recent_sources, marker_in_scope=marker_in_scope,
    )
    candidates = _build_source_candidate_ledger(
        all_sources, verified_rows=out_rows,
        source_errors=verified["errors"],
        indexed_sources=indexed_sources, recent_sources=recent_sources,
        marker_in_scope=marker_in_scope,
    )

    removed = set(indexed_by_key) - set(current_by_key)
    missing_previous = set(prior_rows) - set(current_by_key)
    partial = bool(
        snapshot["status"] != "BOUNDED_SEARCH_READ"
        or verified["status"] != "BOUNDED_SEARCH_READ"
        or verified["errors"] or warnings or removed
        or marker_partial or bool(marker_out_of_scope)
        or previous_partial or bool(missing_previous)
    )
    return {
        "schema_version": "kaep.live-union-check.v0.1",
        "status": "PARTIAL_UNKNOWN" if partial else "BOUNDED_UNION_READ",
        "kind": "REQUEST_TIME_ORIGINAL_ISSUE_UNION",
        "recipient": recipient, "observed_at": verified["observed_at"],
        "snapshot_observed_at": snapshot["observed_at"],
        "repositories_checked": list(repos),
        "explicit_additional_repositories": effective_additional,
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
        "previous_report_used": previous_report is not None,
        "previous_report_source_count": len(prior_source_keys),
        "previous_report_partial": previous_partial,
        "previous_report_state_or_reply_changes": previous_changes,
        "previous_report_roots_missing_live": len(missing_previous),
        "new_source_issue_count_vs_previous": len(set(all_sources) - prior_source_keys)
            if previous_report is not None else 0,
        "previous_report_state_comparison_untrusted": True,
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
    parser.add_argument("--response-format", choices=("union", "agent-api"), default="union",
                        help="Default union JSON or same-call allowlisted Agent API JSON; no HTTP server")
    parser.add_argument("--additional-repository", action="append", default=[],
                        help="Explicit owner-managed repository to read (max 3 total)")
    parser.add_argument("--offline-index", type=Path)
    parser.add_argument("--public-marker-discovery", type=Path,
                        help="Optional bounded untrusted public marker JSON; canonical Issues are revalidated")
    parser.add_argument("--previous-report", type=Path,
                        help="Optional prior union JSON: revalidate its original Issues, compare old states")
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
        prior = None
        if args.previous_report is not None:
            raw = args.previous_report.read_bytes()
            if len(raw) > MAX_PREVIOUS_REPORT_BYTES:
                _deny("PREVIOUS_REPORT_FILE_TOO_LARGE")
            prior = json.loads(raw.decode("utf-8"),
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
            public_marker_discovery=public_markers,
            previous_report=prior)
        if args.response_format == "agent-api":
            from tools.kaep_agent_api_projection import project_agent_view
            result = project_agent_view(result)
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
