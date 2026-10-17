"""On-demand KAEP live change candidates from GitHub Issue comments.

No GitHub Search index, Pages build, write, polling timer or extra host.
The latest comment window is NOT a full Issue universe. Reuse the existing
original-Issue validator; preserve unknown/fallback for every result.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import subprocess
import sys
from typing import Any, Callable

from tools import kaep_issue_search_view as search
from tools.kaep_inbox_reader import InvalidMessage, MARKER, REPOSITORY

MAX_REPOSITORIES = 3
MAX_WINDOW = 100
MAX_BYTES = 2_000_000
MAX_SOURCE_ISSUES = 40
API_ISSUE = re.compile(
    r"https://api\.github\.com/repos/(kinoko34077/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)\Z"
)


def _error(code: str) -> None:
    raise InvalidMessage(code)


def read_repository_recent(repository: str, *, since: str | None = None) -> list[dict[str, Any]]:
    """Read latest issue comments using the REST updated index, not Search."""
    if type(repository) is not str or not REPOSITORY.fullmatch(repository):
        _error("INVALID_REPOSITORY")
    path = f"/repos/{repository}/issues/comments?sort=updated&direction=desc&per_page={MAX_WINDOW}&page=1"
    if since is not None:
        if type(since) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", since):
            _error("INVALID_SINCE")
        try:
            parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if parsed.year < 2020:
                _error("INVALID_SINCE")
        except ValueError as exc:
            raise InvalidMessage("INVALID_SINCE") from exc
        path += f"&since={since}"
    try:
        result = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidMessage("LIVE_GITHUB_UNAVAILABLE") from exc
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > MAX_BYTES:
        _error("LIVE_GITHUB_READ_FAILED")
    try:
        obj = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise InvalidMessage("LIVE_INVALID_JSON") from exc
    if type(obj) is not list or len(obj) > MAX_WINDOW:
        _error("LIVE_INVALID_COMMENT_PAGE")
    return obj


def read_live_candidates(
    repositories: list[str], *, recipient: str, expected_actor: str,
    recent_read: Callable[..., list[dict[str, Any]]] = read_repository_recent,
    issue_read: Callable[[str, int], dict[str, Any]] = search.fetch_issue,
    comments_read: Callable[[str, int], str] = search.fetch_gh_pages,
    since: str | None = None,
) -> dict[str, Any]:
    """One live REST comment-window read per repo plus canonical source reads.

    This is a change *candidate window*, not a complete mailbox, claim or
    proof of all current pending work. No persisted cursors or side effects.
    """
    if (type(repositories) is not list or not 1 <= len(repositories) <= MAX_REPOSITORIES
            or len(set(repositories)) != len(repositories)
            or any(type(r) is not str or not REPOSITORY.fullmatch(r) for r in repositories)
            or recipient not in ("all",) + search.RECIPIENTS
            or type(expected_actor) is not str
            or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", expected_actor)):
        _error("INVALID_LIVE_FILTER")

    source_results: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, str]] = []
    counts: dict[str, int] = {}
    for repo in repositories:
        comments = recent_read(repo, since=since)
        if type(comments) is not list or len(comments) > MAX_WINDOW:
            _error("LIVE_INVALID_COMMENT_PAGE")
        counts[repo] = len(comments)
        if len(comments) == MAX_WINDOW:
            warnings.append({"repository": repo, "reason_code": "RECENT_WINDOW_TRUNCATED"})
        issues: dict[int, dict[str, Any]] = {}
        for entry in comments:
            if type(entry) is not dict:
                _error("LIVE_INVALID_COMMENT")
            body = entry.get("body")
            author = entry.get("user")
            issue_url = entry.get("issue_url")
            cid = entry.get("id")
            if (type(body) is not str or type(author) is not dict
                    or type(author.get("login")) is not str
                    or type(cid) is not int or cid <= 0):
                _error("LIVE_INVALID_COMMENT")
            match = API_ISSUE.fullmatch(issue_url) if type(issue_url) is str else None
            if match is None or match.group(1) != repo:
                _error("LIVE_SOURCE_LOCATOR_MISMATCH")
            if not body.startswith(MARKER):
                continue
            # Discovery is independent of claimed sender identity. A bot/third
            # party comment MAY point to a legitimate older root in the same
            # Issue; canonical full-mailbox verification still gates trust.
            num = int(match.group(2))
            issues[num] = {
                "html_url": f"https://github.com/{repo}/issues/{num}",
            }
        source_results[repo] = {
            "items": list(issues.values()),
            "total_count": len(issues),
            "incomplete_results": False,
        }

    result = search.build_search_list(
        repositories, source_results, fetch_original_issue=issue_read,
        fetch_comments=comments_read, expected_actor=expected_actor,
        recipient=recipient, max_candidates=MAX_SOURCE_ISSUES,
    )
    result["schema_version"] = "kaep.live-recent-candidates.v0.1"
    result["kind"] = "REQUEST_TIME_LIVE_GITHUB_READ"
    result["source_coverage"] = "RECENT_COMMENT_WINDOW_NOT_COMPLETE"
    result["observation_basis"] = "GITHUB_REPOSITORY_ISSUE_COMMENTS_UPDATED_DESC"
    result["recent_comments_observed"] = counts
    result["window_limit_per_repository"] = MAX_WINDOW
    result["since"] = since
    result["fresh_for_observed_sources"] = (result["status"] == "BOUNDED_SEARCH_READ" and not warnings)
    result["has_unknown_work"] = True
    result["complete_source_universe"] = False
    result["can_authorize_execution"] = False
    result["fallback_retirement_authorized"] = False
    result["requires_live_original_issue_revalidation"] = True
    result["absence_of_work_proven"] = False
    result["warnings"] = warnings
    if warnings or result["status"] != "BOUNDED_SEARCH_READ":
        result["status"] = "PARTIAL_UNKNOWN"
    else:
        # A successful bounded current read does not imply global inventory.
        result["status"] = "LIVE_WINDOW_READ"
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", action="append", required=True)
    p.add_argument("--recipient", choices=("all",) + search.RECIPIENTS, required=True)
    p.add_argument("--expect-source-actor", default="kinoko34077")
    p.add_argument("--since", default=None, help="ISO 8601 UTC lower boundary")
    args = p.parse_args(argv)
    try:
        output = read_live_candidates(
            args.repository, recipient=args.recipient,
            expected_actor=args.expect_source_actor, since=args.since,
        )
    except (InvalidMessage, ValueError, TypeError, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, InvalidMessage) else "LIVE_SOURCE_UNAVAILABLE"
        output = {
            "schema_version": "kaep.live-recent-candidates.v0.1",
            "status": "BLOCKED", "reason_code": reason,
            "has_unknown_work": True, "complete_source_universe": False,
            "can_authorize_execution": False,
        }
    print(search.machine_json(output))
    # Both live-window partial and hard failures remain nonzero, but emit JSON.
    return 0 if output["status"] == "LIVE_WINDOW_READ" else 2


if __name__ == "__main__":
    sys.exit(main())
