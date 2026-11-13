"""Opt-in GET-only comparison of an approved discovery index with full originals.

Only strict SOURCE-VERIFIED #503 pointers may admit an Issue. Reads every
READ_ONLY claude-code root inside that bounded source Issue, including roots
which lack a pointer. Does not discover Issues absent from the index, schedule
agents, infer current HEAD, grant authority, or retire the manual fallback.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Any

from tools.devflow_mcp_core import DevflowMCPError, default_service

from tools import agent_inbox
from tools.kaep_discovery_reader import (
    SOURCE_URL, discover_index_shadow, MAX_SHADOW_BATCHES,
)
from tools.kaep_route_notice import (
    DISCOVERY_REPOSITORY, DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE,
)
from tools.kaep_inbox_reader import (
    InvalidMessage, fetch_gh_pages, parse_pages,
)
from tools.kaep_mailbox_codec import (
    MARKER, has_kaep_marker, read_mailbox, verify_reply_chain,
)
from tools.kaep_mailbox_support import matching_actor

MAX_SOURCE_ISSUES = 20  # unchanged default for old callers
MAX_OPT_IN_SOURCE_ISSUES = 40  # bounded explicit expansion only
RECIPIENT = "claude-code"
MAX_TASK_REPOSITORIES = 2


def trusted_m3_task_locators(views: list[dict[str, Any]]) -> set[str]:
    """Admit ONLY already classified CURRENT machine TASK records, no title scan.

    The caller supplies actual native get_repository_work_view results, not
    arbitrary Issue prose, Project display data or user-declared TASK labels.
    This only identifies candidate source Issues for GET-side observation.
    """
    if type(views) is not list or len(views) > MAX_TASK_REPOSITORIES:
        raise InvalidMessage("INVALID_TASK_VIEW_COUNT")
    sources: set[str] = set()
    seen_repos: set[str] = set()
    for view in views:
        if type(view) is not dict:
            raise InvalidMessage("INVALID_TASK_VIEW")
        repository = view.get("repository")
        rows = view.get("task_records")
        observed = view.get("observed_task_view")
        if (type(repository) is not str
                or SOURCE_URL.fullmatch(f"https://github.com/{repository}/issues/1") is None
                or repository in seen_repos
                or view.get("source_status") != "AVAILABLE"
                or view.get("source_freshness") != "CURRENT"
                or type(rows) is not list
                or type(observed) is not dict
                or type(view.get("machine_task_count")) is not int
                or view["machine_task_count"] != len(rows)
                or type(observed.get("known_task_count")) is not int
                or observed["known_task_count"] != len(rows)):
            raise InvalidMessage("UNTRUSTED_OR_INCOMPLETE_TASK_VIEW")
        seen_repos.add(repository)
        for record in rows:
            if type(record) is not dict:
                raise InvalidMessage("INVALID_TASK_SOURCE")
            number = record.get("issue_number")
            url = record.get("url")
            if (type(number) is not int or number < 1
                    or type(url) is not str
                    or url != f"https://github.com/{repository}/issues/{number}"
                    or record.get("record_role") != "TASK"
                    or record.get("state") != "open"
                    or url in sources):
                raise InvalidMessage("INVALID_TASK_SOURCE")
            sources.add(url)
    return sources


def source_root_shadow(
    index_pages: str, *,
    fetch_source: Callable[[str, int], str],
    expected_notice_actor: str,
    expected_source_actor: str,
    max_sources: int = MAX_SOURCE_ISSUES,
    task_views: list[dict[str, Any]] | None = None,
    discovery_issue: int = DISCOVERY_ISSUE,
    isolate_invalid_wrapper: bool = False,
    isolate_invalid_ref: bool = False,
    index_after_id: int = 0,
    index_batches: int = MAX_SHADOW_BATCHES,
) -> dict[str, Any]:
    """Compare one strictly verified approved-index cohort, never work supply."""
    if (type(discovery_issue) is not int or discovery_issue not in
            (DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE)):
        raise InvalidMessage("DISCOVERY_INDEX_NOT_APPROVED")
    if type(isolate_invalid_wrapper) is not bool or type(isolate_invalid_ref) is not bool:
        raise InvalidMessage("INVALID_DIAGNOSTIC_MODE")
    if isolate_invalid_ref and not isolate_invalid_wrapper:
        raise InvalidMessage("INVALID_DIAGNOSTIC_MODE")
    if type(max_sources) is not int or not 1 <= max_sources <= MAX_OPT_IN_SOURCE_ISSUES:
        raise InvalidMessage("INVALID_SOURCE_LIMIT")
    if (type(index_after_id) is not int or index_after_id < 0
            or type(index_batches) is not int
            or not 1 <= index_batches <= MAX_SHADOW_BATCHES):
        raise InvalidMessage("INVALID_INDEX_WINDOW")
    window_explicit = index_after_id > 0 or index_batches < MAX_SHADOW_BATCHES
    if window_explicit and not isolate_invalid_wrapper:
        raise InvalidMessage("INDEX_WINDOW_REQUIRES_DIAGNOSTIC")

    source_cache: dict[tuple[str, int], str] = {}

    def bounded_fetch(repo: str, issue: int) -> str:
        key = (repo, issue)
        if key not in source_cache:
            if len(source_cache) >= max_sources:
                raise InvalidMessage("CANDIDATE_LIMIT")
            source_cache[key] = fetch_source(repo, issue)
        return source_cache[key]

    index = discover_index_shadow(
        index_pages, expected_notice_actor=expected_notice_actor,
        expected_source_actor=expected_source_actor, fetch_source=bounded_fetch,
        index_issue=discovery_issue,
        after_id=index_after_id, max_batches=index_batches,
        additional_forbidden_issue=(
            APPROVED_SUCCESSOR_ISSUE if discovery_issue == DISCOVERY_ISSUE
            else DISCOVERY_ISSUE
        ),
        diagnostic_scan_after_blocked=isolate_invalid_wrapper,
        diagnostic_isolate_invalid_ref=isolate_invalid_ref,
    )
    # The source proof path itself must be unblocked before exposing any
    # derived root evidence. Partial and rejected index entries remain unknown.
    result: dict[str, Any] = {
        "schema_version": "kaep.source-roster-shadow.v0.1",
        "discovery_issue": f"{DISCOVERY_REPOSITORY}#{discovery_issue}",
        "status": "BLOCKED",
        "source_mode": "VERIFIED_POINTER_ONLY",
        "diagnostic_isolation_enabled": isolate_invalid_wrapper,
        "diagnostic_invalid_ref_enabled": isolate_invalid_ref,
        "isolated_invalid_wrapper_sources": 0,
        "isolated_invalid_ref_sources": 0,
        "recipient": RECIPIENT,
        "source_status": index["status"],
        "index_window_explicit": window_explicit,
        "index_after_id": index_after_id,
        "index_batches_limit": index_batches,
        "index_scanned_batches": index["scanned_batches"],
        # Strict safe cursor and non-durable diagnostic scan location differ.
        "index_safe_after_id": index["next_after_id"],
        "index_scan_exhausted": index["index_scan_exhausted"],
        "index_next_diagnostic_after_id": None,
        "index_hint_count": len(index["hints"]),
        "candidate_issue_count": len(source_cache),
        "issues": [],
        "errors": [],
        "rejected_index_count": len(index["rejected"]),
        "blocked_index_count": len(index["blocked"]),
        # Preserve public, bounded blocker IDs/reason codes so a failed shadow
        # is diagnosable without repeating broad authenticated source reads.
        # This NEVER releases unverified roots or changes the cursor.
        "index_blockers": [
            {
                "index_comment_id": b["index_comment_id"],
                "reason_code": b["reason_code"]
                if (type(b.get("reason_code")) is str
                    and 1 <= len(b["reason_code"]) <= 80
                    and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                            for c in b["reason_code"]))
                else "SOURCE_VALIDATION_ERROR",
            }
            for b in index["blocked"]
            if type(b) is dict and type(b.get("index_comment_id")) is int
            and b["index_comment_id"] > 0
        ],
        "index_truncated": index["truncated"],
        "has_unknown_work": True,
        "complete_source_universe": False,
        "head_freshness": "NOT_REVALIDATED",
        "recipient_pickup_verified": False,
        "can_authorize_execution": False,
        "can_replace_manual_active_work": False,
        "fallback_retirement_authorized": False,
        "read_only": True,
    }
    allowed = ({"INVALID_WRAPPER", "INVALID_REF"} if isolate_invalid_ref
               else {"INVALID_WRAPPER"})
    fatal_blocker = any(
        b.get("reason_code") not in allowed for b in index["blocked"]
    )
    if index["blocked"] or index["truncated"]:
        result["errors"].append({"reason_code": "INDEX_SOURCE_INCOMPLETE"})
        # An explicitly bounded comment window may return only independently
        # verified source roots; all unexamined comments remain unknown.
        # The default complete strict scan and cap/identity/transport failure
        # behavior are unchanged. No window may advance the safe cursor past
        # a failed original.
        if (not isolate_invalid_wrapper or fatal_blocker
                or index["status"] not in ("PARTIAL_BLOCKED", "BOUNDED_TRUNCATED")
                or (index["status"] == "BOUNDED_TRUNCATED"
                    and not window_explicit)):
            return result
        result["isolated_invalid_wrapper_sources"] += sum(
            b.get("reason_code") == "INVALID_WRAPPER" for b in index["blocked"]
        )
        result["isolated_invalid_ref_sources"] += sum(
            b.get("reason_code") == "INVALID_REF" for b in index["blocked"]
        )
    try:
        task_sources = trusted_m3_task_locators(task_views or [])
    except InvalidMessage as exc:
        result["errors"].append({"reason_code": str(exc)})
        return result
    if task_views:
        result["source_mode"] = "VERIFIED_POINTER_AND_TRUSTED_M3_TASK"
    # Every TASK root is a source *candidate*, not a validated KAEP REQUEST.
    # Bound and fetch through the same verified Issue cache before parsing.
    try:
        for url in sorted(task_sources):
            match = SOURCE_URL.fullmatch(url)
            if match is None:
                raise InvalidMessage("INVALID_TASK_SOURCE")
            bounded_fetch(match.group(1), int(match.group(2)))
    except (InvalidMessage, OSError, UnicodeError):
        result["errors"].append({"reason_code": "TASK_SOURCE_READ_BLOCKED"})
        return result
    result["candidate_issue_count"] = len(source_cache)
    index_by_issue: dict[str, set[tuple[int, str]]] = {}
    for hint in index["hints"]:
        index_by_issue.setdefault(hint["owning_issue"], set()).add(
            (hint["source_comment_id"], hint["source_message_id"])
        )
    for url in task_sources:
        index_by_issue.setdefault(url, set())
    # A strictly verified source is admitted even if its enclosing Issue is
    # UNCLASSIFIED. The locator is evidence to READ, never task authority.
    for url in sorted(index_by_issue):
        match = SOURCE_URL.fullmatch(url)
        if match is None:
            result["errors"].append({"reason_code": "INVALID_SOURCE_LOCATOR"})
            return result
        repo, issue = match.group(1), int(match.group(2))
        try:
            all_comments = parse_pages(
                source_cache[(repo, issue)], repository=repo, issue=issue
            )
            # Exclude outsider-authored KAEP marker data before canonical
            # reply-chain validation, as the accepted Agent Inbox does.
            trusted = [
                c for c in all_comments
                if not has_kaep_marker(c["body"])
                or matching_actor(c, expected_source_actor)
            ]
            decoded = read_mailbox(trusted, task_ref=f"{repo}#{issue}")
            verify_reply_chain([msg for _, msg in decoded])
            github_comments = [
                {"id": c["id"], "body": c["body"],
                 "user": {"id": c.get("actor_id"),
                          "login": c["actor_login"]}}
                for c in all_comments
            ]
            roots, warnings = agent_inbox._issue_messages(
                github_comments, repository=repo, issue_number=issue,
                recipient=RECIPIENT, expected_actor=expected_source_actor,
            )
        except (InvalidMessage, ValueError, KeyError) as exc:
            result["errors"].append({
                "owning_issue": url, "reason_code":
                str(exc) if isinstance(exc, InvalidMessage)
                else "SOURCE_MAILBOX_UNAVAILABLE",
            })
            # Only the explicit non-authoritative diagnostic may continue
            # after one malformed wrapper, never after identity/replay errors.
            if isolate_invalid_wrapper and str(exc) in (
                {"INVALID_WRAPPER", "INVALID_REF"} if isolate_invalid_ref
                else {"INVALID_WRAPPER"}
            ):
                # Quarantine this whole original, never its individual roots.
                counter = ("isolated_invalid_ref_sources" if str(exc) == "INVALID_REF"
                           else "isolated_invalid_wrapper_sources")
                result[counter] += 1
                continue
            return result
        observed = set()
        items: list[dict[str, Any]] = []
        for root in roots:
            key = (root["source_comment_id"], root["source_message_id"])
            observed.add(key)
            items.append({
                "source_comment_id": key[0],
                "source_message_id": key[1],
                "comparison": ("INDEXED_AND_ORIGINAL" if key in index_by_issue[url]
                               else "ORIGINAL_ONLY"),
                "expected_head": root["expected_head"],
                "head_freshness": "NOT_REVALIDATED",
                "reply_observation": root["status"],
            })
        missing_pointer_origins = index_by_issue[url] - observed
        if missing_pointer_origins:
            result["errors"].append({
                "owning_issue": url, "reason_code": "INDEX_ONLY_INVALID",
            })
            return result
        result["issues"].append({
            "owning_issue": url,
            "provenance": ([ "VERIFIED_POINTER" ] if index_by_issue[url] else [])
                          + ([ "TRUSTED_M3_TASK" ] if url in task_sources else []),
            "not_covered_by_task_classification": url not in task_sources,
            "source_state": "AVAILABLE",
            "root_count": len(items),
            "original_only_count": sum(
                1 for item in items if item["comparison"] == "ORIGINAL_ONLY"
            ),
            "warnings": warnings,
            "roots": items,
        })
    result["status"] = (
        "BOUNDED_CANDIDATE_SOURCE_READ"
        if not index["rejected"] and not result["errors"]
        and not isolate_invalid_wrapper
        else "PARTIAL_UNKNOWN"
    )
    # Only a fully processed, nonfatal diagnostic window may advertise the
    # next scan-only location. Source/actor/parent/cap failures above return
    # without this field, preventing a caller from skipping a blocked window.
    if (window_explicit and not fatal_blocker
            and not index["index_scan_exhausted"]):
        result["index_next_diagnostic_after_id"] = (
            index["last_scanned_index_comment_id"]
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-notice-actor", required=True)
    parser.add_argument("--expect-source-actor", required=True)
    parser.add_argument("--max-sources", type=int, default=MAX_SOURCE_ISSUES,
                        help="Verified #503/M3 original Issue cap; default 20, explicit maximum 40")
    parser.add_argument("--discovery-issue", type=int, default=DISCOVERY_ISSUE,
                        help="Default legacy #503; explicit approved successor #789")
    parser.add_argument("--isolate-invalid-wrapper", action="store_true",
                        help="Diagnostic-only partial original read beyond known malformed "
                             "historical wrapper; never grants completeness or authority")
    parser.add_argument("--isolate-invalid-ref", action="store_true",
                        help="Diagnostic-only whole-Issue INVALID_REF exclusion; requires "
                             "--isolate-invalid-wrapper, never accepts invalid roots")
    parser.add_argument("--index-after-id", type=int, default=0,
                        help="Diagnostic-only index comment start (exclusive); not durable")
    parser.add_argument("--index-batches", type=int, default=MAX_SHADOW_BATCHES,
                        help="Diagnostic-only number of 20-comment batches (1..10)")
    parser.add_argument("--task-repository", action="append", default=[],
                        help="Opt in an explicit trusted M3 live TASK repository (up to 2)")
    args = parser.parse_args(argv)
    try:
        if args.discovery_issue not in (DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE):
            raise InvalidMessage("DISCOVERY_INDEX_NOT_APPROVED")
        if args.isolate_invalid_ref and not args.isolate_invalid_wrapper:
            raise InvalidMessage("INVALID_DIAGNOSTIC_MODE")
        if (args.index_after_id < 0 or not 1 <= args.index_batches <= MAX_SHADOW_BATCHES):
            raise InvalidMessage("INVALID_INDEX_WINDOW")
        if (args.index_after_id or args.index_batches != MAX_SHADOW_BATCHES) and not args.isolate_invalid_wrapper:
            raise InvalidMessage("INDEX_WINDOW_REQUIRES_DIAGNOSTIC")
        if (len(args.task_repository) > MAX_TASK_REPOSITORIES
                or len(set(args.task_repository)) != len(args.task_repository)):
            raise InvalidMessage("INVALID_TASK_REPOSITORY_COUNT")
        service = default_service() if args.task_repository else None
        task_views = [service.get_repository_work_view(repo)
                      for repo in args.task_repository] if service else []
        index_pages = fetch_gh_pages(DISCOVERY_REPOSITORY, args.discovery_issue)
        output = source_root_shadow(
            index_pages, fetch_source=fetch_gh_pages,
            expected_notice_actor=args.expect_notice_actor,
            expected_source_actor=args.expect_source_actor,
            max_sources=args.max_sources, task_views=task_views,
            discovery_issue=args.discovery_issue,
            isolate_invalid_wrapper=args.isolate_invalid_wrapper,
            isolate_invalid_ref=args.isolate_invalid_ref,
            index_after_id=args.index_after_id,
            index_batches=args.index_batches,
        )
    except (InvalidMessage, DevflowMCPError, OSError, UnicodeError) as exc:
        # No raw GitHub stderr, messages, prompts or credential data in errors.
        output = {
            "status": "BLOCKED", "reason_code":
            str(exc) if isinstance(exc, InvalidMessage)
            else "SOURCE_READ_UNAVAILABLE",
            "read_only": True, "has_unknown_work": True,
            "fallback_retirement_authorized": False,
        }
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0 if output["status"] == "BOUNDED_CANDIDATE_SOURCE_READ" else 2


if __name__ == "__main__":
    sys.exit(main())
