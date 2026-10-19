"""Opt-in GET-only comparison of the existing #503 pointer cohort with full originals.

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
    SOURCE_URL, discover_index_shadow,
)
from tools.kaep_inbox_reader import (
    InvalidMessage, fetch_gh_pages, parse_pages,
)
from tools.kaep_mailbox_codec import (
    MARKER, read_mailbox, verify_reply_chain,
)

MAX_SOURCE_ISSUES = 20
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
) -> dict[str, Any]:
    """Compare only verified #503 original-Issue locators, never work supply."""
    if type(max_sources) is not int or not 1 <= max_sources <= MAX_SOURCE_ISSUES:
        raise InvalidMessage("INVALID_SOURCE_LIMIT")

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
    )
    # The source proof path itself must be unblocked before exposing any
    # derived root evidence. Partial and rejected index entries remain unknown.
    result: dict[str, Any] = {
        "schema_version": "kaep.source-roster-shadow.v0.1",
        "status": "BLOCKED",
        "source_mode": "VERIFIED_POINTER_ONLY",
        "recipient": RECIPIENT,
        "source_status": index["status"],
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
    if index["blocked"] or index["truncated"]:
        result["errors"].append({"reason_code": "INDEX_SOURCE_INCOMPLETE"})
        return result

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
                if not c["body"].startswith(MARKER)
                or c["actor_login"].casefold() == expected_source_actor.casefold()
            ]
            decoded = read_mailbox(trusted, task_ref=f"{repo}#{issue}")
            verify_reply_chain([msg for _, msg in decoded])
            github_comments = [
                {"id": c["id"], "body": c["body"],
                 "user": {"login": c["actor_login"]}}
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
            # Fail closed: no successful partial roster claim.
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
        else "PARTIAL_UNKNOWN"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-notice-actor", required=True)
    parser.add_argument("--expect-source-actor", required=True)
    parser.add_argument("--max-sources", type=int, default=MAX_SOURCE_ISSUES)
    parser.add_argument("--task-repository", action="append", default=[],
                        help="Opt in an explicit trusted M3 live TASK repository (up to 2)")
    args = parser.parse_args(argv)
    try:
        if (len(args.task_repository) > MAX_TASK_REPOSITORIES
                or len(set(args.task_repository)) != len(args.task_repository)):
            raise InvalidMessage("INVALID_TASK_REPOSITORY_COUNT")
        service = default_service() if args.task_repository else None
        task_views = [service.get_repository_work_view(repo)
                      for repo in args.task_repository] if service else []
        index_pages = fetch_gh_pages("kinoko34077/devflow", 503)
        output = source_root_shadow(
            index_pages, fetch_source=fetch_gh_pages,
            expected_notice_actor=args.expect_notice_actor,
            expected_source_actor=args.expect_source_actor,
            max_sources=args.max_sources, task_views=task_views,
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
