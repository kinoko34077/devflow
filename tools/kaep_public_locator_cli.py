"""Read-only, public-only KAEP marker locator discovery for one GitHub owner.

Only emits public owner repository / Issue / comment IDs. Markers are untrusted
search hints, NOT validated KAEP requests, recipient pickup or authority.
No token, Issue body, comment body, title, private repo or agent execution output.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
from typing import Any, Callable

from tools.kaep_inbox_reader import InvalidMessage, MARKER
from tools.kaep_live_delta_view import API_ISSUE

OWNER = "kinoko34077"
PAGE_SIZE = 100
MAX_REPO_PAGES = 5
MAX_COMMENT_PAGES = 100
MAX_API_CALLS = 2000
MAX_LOCATORS = 5000
MAX_RESPONSE_BYTES = 4_000_000
REPO_NAME = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+\Z")


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def _gh_get(path: str) -> Any:
    """Use existing gh authentication only, with a generated GET-only path."""
    if not path.startswith("/users/kinoko34077/repos?") and not (
        path.startswith("/repos/kinoko34077/")
        and "/issues/comments?" in path
    ):
        _fail("INVALID_PUBLIC_GITHUB_PATH")
    try:
        run = subprocess.run(
            ["gh", "api", "--method", "GET", "-H",
             "Accept: application/vnd.github+json", path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidMessage("PUBLIC_GITHUB_GET_UNAVAILABLE") from exc
    if run.returncode or len(run.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
        _fail("PUBLIC_GITHUB_GET_FAILED")
    try:
        return json.loads(run.stdout)
    except ValueError as exc:
        raise InvalidMessage("INVALID_GITHUB_JSON") from exc


def discover(
    *, fetch: Callable[[str], Any] = _gh_get,
    max_repo_pages: int = 3,
    max_comment_pages: int = 40,
    max_api_calls: int = 350,
) -> dict[str, Any]:
    """Enumerate public owner repos and page through their Issue comments.

    All bounds are explicit. A truncated or unstable public read is never an
    empty authoritative inbox. The content of KAEP messages is never emitted.
    """
    if (type(max_repo_pages) is not int or not 1 <= max_repo_pages <= MAX_REPO_PAGES
            or type(max_comment_pages) is not int
            or not 1 <= max_comment_pages <= MAX_COMMENT_PAGES
            or type(max_api_calls) is not int
            or not max_repo_pages <= max_api_calls <= MAX_API_CALLS):
        _fail("INVALID_SCAN_BOUNDS")
    calls = 0
    repos: list[str] = []
    repo_set: set[str] = set()
    incomplete: list[dict[str, Any]] = []
    repo_enumeration_complete = False
    for page in range(1, max_repo_pages + 1):
        if calls >= max_api_calls:
            incomplete.append({"scope": "PUBLIC_REPOSITORIES",
                               "next_page": page, "reason_code": "API_BUDGET"})
            break
        calls += 1
        path = f"/users/{OWNER}/repos?type=owner&per_page={PAGE_SIZE}&page={page}"
        try:
            data = fetch(path)
            if type(data) is not list or len(data) > PAGE_SIZE:
                _fail("INVALID_PUBLIC_REPOSITORY_PAGE")
            for item in data:
                if type(item) is not dict:
                    _fail("INVALID_PUBLIC_REPOSITORY_PAGE")
                full = item.get("full_name")
                account = item.get("owner")
                if (type(full) is not str or not REPO_NAME.fullmatch(full)
                        or type(account) is not dict
                        or account.get("id") != 79015263
                        or account.get("login") != OWNER
                        or item.get("private") is not False):
                    _fail("INVALID_PUBLIC_REPOSITORY_PAGE")
                if full not in repo_set:
                    repos.append(full)
                    repo_set.add(full)
        except (InvalidMessage, ValueError, TypeError, OSError):
            incomplete.append({"scope": "PUBLIC_REPOSITORIES",
                               "next_page": page, "reason_code": "REPOSITORY_READ_UNKNOWN"})
            break
        if len(data) < PAGE_SIZE:
            repo_enumeration_complete = True
            break
        if page == max_repo_pages:
            incomplete.append({"scope": "PUBLIC_REPOSITORIES",
                               "next_page": page + 1, "reason_code": "REPOSITORY_PAGE_CAP"})
    locators: list[dict[str, Any]] = []
    found: set[tuple[str, int, int]] = set()
    scanned_repos = 0
    for idx, repo in enumerate(repos):
        repo_finished = False
        for page in range(1, max_comment_pages + 1):
            if calls >= max_api_calls:
                incomplete.extend(
                    {"scope": name, "next_page": (page if n == idx else 1),
                     "reason_code": "API_BUDGET"}
                    for n, name in enumerate(repos[idx:], start=idx)
                )
                break
            calls += 1
            path = (f"/repos/{repo}/issues/comments?sort=created&direction=desc"
                    f"&per_page={PAGE_SIZE}&page={page}")
            try:
                comments = fetch(path)
                if type(comments) is not list or len(comments) > PAGE_SIZE:
                    _fail("INVALID_PUBLIC_COMMENT_PAGE")
                for comment in comments:
                    if type(comment) is not dict:
                        _fail("INVALID_PUBLIC_COMMENT")
                    body, cid, source = (comment.get("body"), comment.get("id"),
                                         comment.get("issue_url"))
                    match = API_ISSUE.fullmatch(source) if type(source) is str else None
                    if (type(body) is not str or type(cid) is not int or cid < 1
                            or match is None or match.group(1) != repo):
                        _fail("INVALID_PUBLIC_COMMENT")
                    if not body.startswith(MARKER):
                        continue
                    issue = int(match.group(2))
                    key = (repo, issue, cid)
                    if key in found:
                        continue
                    found.add(key)
                    if len(found) > MAX_LOCATORS:
                        _fail("PUBLIC_LOCATOR_LIMIT")
                    url = f"https://github.com/{repo}/issues/{issue}"
                    locators.append({
                        "locator": f"{repo.split('/', 1)[1]}#{issue}@{cid}",
                        "repository": repo, "issue_number": issue,
                        "comment_id": cid, "source_url": f"{url}#issuecomment-{cid}",
                        "strict_source_validated": False,
                        "is_authoritative_assignment": False,
                    })
            except (InvalidMessage, ValueError, TypeError, OSError):
                incomplete.append({"scope": repo, "next_page": page,
                                   "reason_code": "COMMENT_PAGE_UNKNOWN"})
                break
            if len(comments) < PAGE_SIZE:
                repo_finished = True
                break
            if page == max_comment_pages:
                incomplete.append({"scope": repo, "next_page": page + 1,
                                   "reason_code": "COMMENT_PAGE_CAP"})
        if repo_finished:
            scanned_repos += 1
        if calls >= max_api_calls:
            # If the inner loop already marked current+remaining scopes,
            # avoid duplicating their budget diagnostics here.
            if any(gap["reason_code"] == "API_BUDGET" for gap in incomplete):
                break
            # The just-scanned repository may be complete, but all later
            # repositories are still unread. Never silently omit them.
            if idx + 1 < len(repos):
                incomplete.extend(
                    {"scope": name, "next_page": 1,
                     "reason_code": "API_BUDGET"}
                    for name in repos[idx + 1:]
                )
            break
    locators.sort(key=lambda x: (
        x["repository"], x["issue_number"], x["comment_id"]))
    complete_pages = repo_enumeration_complete and not incomplete
    return {
        "schema_version": "kaep.public-marker-locators.v0.1",
        "kind": "UNTRUSTED_PUBLIC_KAEP_MARKER_DISCOVERY",
        "status": "BOUNDED_PUBLIC_MARKER_READ" if complete_pages else "PARTIAL_UNKNOWN",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "owner": OWNER, "public_only": True, "read_only": True,
        "repository_enumeration_complete": repo_enumeration_complete,
        "repository_count_observed": len(repos),
        "repositories_with_all_comment_pages_read": scanned_repos,
        "api_requests_used": calls,
        "comment_page_limit_per_repo": max_comment_pages,
        "api_request_limit": max_api_calls,
        "locators": locators, "locator_count": len(locators),
        "incomplete_scopes": incomplete,
        "complete_comment_pages_for_observed_public_repos": complete_pages,
        "complete_source_universe": False,
        "has_unknown_work": True, "absence_of_work_proven": False,
        "recipient_pickup_proven": False, "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
        "requires_strict_original_issue_validation": True,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--format", choices=("lines", "json"), default="lines")
    p.add_argument("--max-repo-pages", type=int, default=3)
    p.add_argument("--max-comment-pages", type=int, default=40)
    p.add_argument("--max-api-calls", type=int, default=350)
    args = p.parse_args(argv)
    try:
        result = discover(max_repo_pages=args.max_repo_pages,
                          max_comment_pages=args.max_comment_pages,
                          max_api_calls=args.max_api_calls)
    except (InvalidMessage, OSError, ValueError, TypeError):
        result = {"schema_version": "kaep.public-marker-locators.v0.1",
                  "status": "BLOCKED", "reason_code": "PUBLIC_SCAN_UNAVAILABLE",
                  "read_only": True, "has_unknown_work": True,
                  "complete_source_universe": False,
                  "can_authorize_execution": False, "locators": []}
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    else:
        for row in result["locators"]:
            print(row["locator"])
        print(f"# {result['status']}; discovered={len(result['locators'])}; "
              f"public_repos={result.get('repository_count_observed', 0)}; "
              f"fully_scanned_repos={result.get('repositories_with_all_comment_pages_read', 0)}; "
              f"incomplete_scopes={len(result.get('incomplete_scopes', []))}; "
              "untrusted_markers_only=true; no_work_proven=false")
        for gap in result.get("incomplete_scopes", []):
            print(f"# UNKNOWN {gap['scope']} page={gap['next_page']} "
                  f"reason={gap['reason_code']}")
    return 0 if result["status"] == "BOUNDED_PUBLIC_MARKER_READ" else 2


if __name__ == "__main__":
    sys.exit(main())
