"""Opt-in read-only GitHub KAEP search -> strict original-Issue list.

Search is candidate discovery, NOT a complete mailbox or work inventory.
The Project API, runtime, writer, KAEP routing and M3 role source are unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
import re
import subprocess
import sys
from typing import Any, Callable

from tools import agent_inbox, repository_projection
from tools.kaep_issue_list_html import to_html
from tools.kaep_public_index import to_public_index
from tools.kaep_inbox_reader import (
    InvalidMessage, REPOSITORY, fetch_gh_pages, parse_pages,
)
from tools.kaep_mailbox_codec import MARKER, decode_comment, read_mailbox, verify_reply_chain

MAX_REPOSITORIES = 3
MAX_CANDIDATES = 40
SEARCH_PAGE_SIZE = 100
RECIPIENTS = ("claude-code", "chatgpt", "codex", "coordinator")
URL = re.compile(r"https://github\.com/(kinoko34077/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)\Z")


def _fail(reason: str) -> None:
    raise InvalidMessage(reason)


def _gh_json(path: str, *, query: str | None = None) -> dict[str, Any]:
    args = ["gh", "api", "-H", "Accept: application/vnd.github+json"]
    if query is not None:
        args.extend(["-X", "GET", path, "-f", f"q={query}",
                     "-f", f"per_page={SEARCH_PAGE_SIZE}"])
    else:
        args.append(path)
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidMessage("GITHUB_SEARCH_OR_ISSUE_UNAVAILABLE") from exc
    if p.returncode != 0 or len(p.stdout.encode("utf-8")) > 2_000_000:
        _fail("GITHUB_SEARCH_OR_ISSUE_FAILED")
    try:
        obj = json.loads(p.stdout)
    except (ValueError, UnicodeError) as exc:
        raise InvalidMessage("INVALID_GITHUB_JSON") from exc
    if type(obj) is not dict:
        _fail("INVALID_GITHUB_RESPONSE")
    return obj


def search_repository(repository: str) -> dict[str, Any]:
    if not REPOSITORY.fullmatch(repository):
        _fail("INVALID_REPOSITORY")
    return _gh_json("/search/issues", query=(
        f'repo:{repository} is:issue "kaep:message:v0.2" in:comments'
    ))


def fetch_issue(repository: str, number: int) -> dict[str, Any]:
    if not REPOSITORY.fullmatch(repository) or type(number) is not int or number < 1:
        _fail("INVALID_ISSUE")
    return _gh_json(f"/repos/{repository}/issues/{number}")



# Only these two intrinsically non-authoritative presentation defects can be
# quarantined in this read-only list. Never relax the canonical source codec,
# and never quarantine identity, parent-chain, scope or collision failures.
_DISPLAY_ONLY_QUARANTINE = frozenset({"INVALID_WRAPPER", "INVALID_REF"})


def _display_only_trusted_comments(
    trusted: list[dict[str, Any]], *, task_ref: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    usable: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for comment in trusted:
        if not comment["body"].startswith(MARKER):
            usable.append(comment)
            continue
        try:
            decode_comment(comment["body"], task_ref=task_ref)
        except InvalidMessage as exc:
            reason = str(exc)
            if reason not in _DISPLAY_ONLY_QUARANTINE:
                raise
            quarantined.append({
                "comment_id": comment["id"],
                "reason_code": "QUARANTINED_" + reason,
            })
            continue
        usable.append(comment)
    return usable, quarantined


def build_search_list(
    repositories: list[str], search_results: dict[str, dict[str, Any]], *,
    fetch_original_issue: Callable[[str, int], dict[str, Any]],
    fetch_comments: Callable[[str, int], str],
    expected_actor: str,
    recipient: str = "all",
    max_candidates: int = MAX_CANDIDATES,
) -> dict[str, Any]:
    """Use real search *locators*, then revalidate each original source.

    All source fetches are GET-only; payload text is never emitted. Even a
    successful finite candidate read cannot prove GitHub's index exhaustive.
    """
    if (type(repositories) is not list or not 1 <= len(repositories) <= MAX_REPOSITORIES
            or len(repositories) != len(set(repositories))
            or any(type(r) is not str or not REPOSITORY.fullmatch(r)
                   for r in repositories)):
        _fail("INVALID_REPOSITORY_SET")
    if (recipient != "all" and recipient not in RECIPIENTS) or (
        type(max_candidates) is not int or not 1 <= max_candidates <= MAX_CANDIDATES
    ):
        _fail("INVALID_FILTER")
    if type(expected_actor) is not str or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", expected_actor):
        _fail("INVALID_EXPECTED_ACTOR")
    output: dict[str, Any] = {
        "schema_version": "kaep.search-list.v0.1",
        "status": "BOUNDED_SEARCH_READ",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_coverage": "SEARCH_INDEX_NOT_AUTHORITATIVE",
        "repositories": list(repositories),
        "searched_candidates": 0,
        "validated_source_issues": 0,
        "partial_source_issues": 0,
        "unmatched_candidates": 0,
        "rows": [],
        "errors": [],
        "has_unknown_work": True,
        "complete_source_universe": False,
        "head_freshness": "NOT_REVALIDATED",
        "is_authoritative_assignment": False,
        "can_authorize_execution": False,
        "can_replace_manual_active_work": False,
        "fallback_retirement_authorized": False,
        "read_only": True,
    }
    candidates: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for repo in repositories:
        result = search_results.get(repo)
        if (type(result) is not dict or type(result.get("items")) is not list
                or type(result.get("total_count")) is not int
                or type(result.get("incomplete_results")) is not bool):
            output["errors"].append({"repository": repo, "reason_code": "SEARCH_UNAVAILABLE"})
            continue
        if result["incomplete_results"] or result["total_count"] > len(result["items"]):
            output["errors"].append({"repository": repo, "reason_code": "SEARCH_PAGE_INCOMPLETE"})
        if result["total_count"] < len(result["items"]):
            output["errors"].append({"repository": repo, "reason_code": "INVALID_SEARCH_COUNT"})
            continue
        for item in result["items"]:
            if type(item) is not dict or "pull_request" in item:
                output["errors"].append({"repository": repo, "reason_code": "INVALID_SEARCH_ITEM"})
                continue
            url = item.get("html_url")
            match = URL.fullmatch(url) if type(url) is str else None
            if match is None or match.group(1) != repo:
                output["errors"].append({"repository": repo, "reason_code": "SEARCH_LOCATOR_MISMATCH"})
                continue
            key = (repo, int(match.group(2)))
            if key not in seen:
                seen.add(key)
                candidates.append(key)
    output["searched_candidates"] = len(candidates)
    if len(candidates) > max_candidates:
        output["errors"].append({"reason_code": "CANDIDATE_LIMIT"})
        candidates = candidates[:max_candidates]
    for repo, number in candidates:
        url = f"https://github.com/{repo}/issues/{number}"
        try:
            issue = fetch_original_issue(repo, number)
            if (type(issue) is not dict or issue.get("html_url") != url
                    or issue.get("number") != number
                    or issue.get("state") not in ("open", "closed")
                    or "pull_request" in issue):
                _fail("SOURCE_ISSUE_MISMATCH")
            classified = repository_projection.classify_issue(issue)
            pages = parse_pages(fetch_comments(repo, number),
                                repository=repo, issue=number)
            # Enforce the canonical limit on the COMPLETE original mailbox,
            # before excluding bot markers or quarantining malformed markers.
            # Otherwise a large source could evade _issue_messages' limit.
            if len(pages) > agent_inbox.MAX_ISSUE_COMMENTS:
                _fail("ISSUE_COMMENTS_LIMIT")
            # Only the configured GitHub transport actor is an admitted root
            # origin. A bot/outsider marker is evidence of uncertainty, not a
            # source of task authority.
            trusted = [
                {"id": c["id"], "body": c["body"],
                 "user": {"login": c["actor_login"]}}
                for c in pages
                if not c["body"].startswith(MARKER)
                or c["actor_login"].casefold() == expected_actor.casefold()
            ]
            trusted, quarantined = _display_only_trusted_comments(
                trusted, task_ref=f"{repo}#{number}",
            )
            # The unchanged strict codec still verifies every remaining
            # message; parent/collision/actor failure blocks this entire Issue.
            parsed = read_mailbox(trusted, task_ref=f"{repo}#{number}")
            verify_reply_chain([m for _, m in parsed])
            recipients = RECIPIENTS if recipient == "all" else (recipient,)
            verified_roots: list[dict[str, Any]] = []
            for target in recipients:
                roots, _warnings = agent_inbox._issue_messages(
                    trusted, repository=repo, issue_number=number,
                    recipient=target, expected_actor=expected_actor,
                )
                for root in roots:
                    verified_roots.append({
                        "repository": repo, "issue_number": number,
                        "issue_url": url,
                        "source_url": root["source_url"],
                        "title_hint": agent_inbox._safe_untrusted_title(issue.get("title")),
                        "issue_state": issue["state"],
                        "issue_role": classified.record_role or "UNCLASSIFIED",
                        "issue_type": classified.type,
                        "role_source": classified.source_kind,
                        "recipient": target,
                        "intent": root["intent"],
                        "reply_observation": (
                            "UNVERIFIED_DUE_TO_SOURCE_QUARANTINE"
                            if quarantined else root["status"]
                        ),
                        "source_validation": (
                            "PARTIAL_UNKNOWN" if quarantined
                            else "STRICT_COMPLETE_FOR_CANDIDATE"
                        ),
                        "message_id": root["source_message_id"],
                        "source_comment_id": root["source_comment_id"],
                        "head_freshness": "NOT_REVALIDATED",
                        "is_authoritative_assignment": False,
                    })
            if quarantined:
                output["partial_source_issues"] += 1
                for entry in quarantined:
                    output["errors"].append({"owning_issue": url, **entry})
            else:
                output["validated_source_issues"] += 1
                if not verified_roots:
                    output["unmatched_candidates"] += 1
            output["rows"].extend(verified_roots)
        except (InvalidMessage, ValueError, KeyError, TypeError) as exc:
            output["errors"].append({
                "owning_issue": url,
                "reason_code": str(exc) if isinstance(exc, InvalidMessage)
                               else "SOURCE_VALIDATION_FAILED",
            })
        except (OSError, UnicodeError):
            output["errors"].append({
                "owning_issue": url, "reason_code": "SOURCE_READ_UNAVAILABLE",
            })
    output["rows"].sort(
        key=lambda r: (r["repository"], r["issue_number"], r["source_comment_id"])
    )
    if output["errors"]:
        output["status"] = "PARTIAL_UNKNOWN"
    # "BOUNDED_SEARCH_READ" is only a search-candidate read status, never
    # a statement of completeness, current pending work, or routing parity.
    return output


def _cell(value: str) -> str:
    """Escape title/display text without granting Markdown link syntax."""
    return re.sub(r"([\\|`\[\]<>*_!])", r"\\\1", value)


def to_markdown(result: dict[str, Any], *, role: str = "all",
                issue_type: str = "all", state: str = "all",
                reply: str = "all") -> str:
    rows = [
        x for x in result["rows"]
        if (role == "all" or x["issue_role"] == role)
        and (issue_type == "all" or x["issue_type"] == issue_type)
        and (state == "all" or x["issue_state"] == state)
        and (reply == "all" or x["reply_observation"] == reply)
    ]
    lines = [
        "# KAEP source discovery — read-only candidate list",
        "",
        f"Search status: {result['status']} / {result['source_coverage']}",
        f"Observed at (UTC): {result['observed_at']}",
        f"Candidate Issues: {result['searched_candidates']}; "
        f"Strict Issues: {result['validated_source_issues']}; "
        f"Partial Issues: {result['partial_source_issues']}; "
        f"Rows (filtered): {len(rows)}; Errors: {len(result['errors'])}",
        "This is NOT a complete Issue/KAEP inventory, pending work queue, "
        "agent identity, current-HEAD proof, or permission to act.",
        "",
        "| Repository / Issue | Title | State | Role / type (source) | Recipient / intent | Reply observation | Source validation | Original source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for x in rows:
        lines.append(
            f"| {x['repository'].split('/')[-1]} [#{x['issue_number']}]({x['issue_url']})"
            f" | {_cell(x['title_hint'])}"
            f" | {x['issue_state']}"
            f" | {x['issue_role']} / {x['issue_type'] or '-'} ({x['role_source']})"
            f" | {x['recipient']} / {x['intent']}"
            f" | {x['reply_observation']}"
            f" | {x['source_validation']}"
            f" | [comment {x['source_comment_id']}]({x['source_url']}) |"
        )
    if not rows:
        lines.append("| No verified rows in this bounded search/filter | - | - | - | - | - | - | - |")
    if result["errors"]:
        lines.append("")
        lines.append("Errors / unknown: " + ", ".join(
            e["reason_code"] for e in result["errors"]
        ))
    return "\n".join(lines) + "\n"

def machine_json(value: dict[str, Any]) -> str:
    """Emit portable machine JSON even on Windows CP932 consoles."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def console_text(value: str, encoding: str | None) -> str:
    """Preserve displayable characters; escape unsupported ones, never abort."""
    codec = encoding or "utf-8"
    try:
        return value.encode(codec, errors="backslashreplace").decode(codec)
    except LookupError:
        return value.encode("ascii", errors="backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", action="append", required=True)
    parser.add_argument("--expect-source-actor", required=True)
    parser.add_argument("--recipient", choices=("all",) + RECIPIENTS, default="all")
    parser.add_argument("--format", choices=("markdown", "json", "html"), default="markdown")
    parser.add_argument("--public-json-out", default=None,
                        help="Opt-in allowlisted public candidate snapshot alongside HTML")
    parser.add_argument("--public-live", action="store_true",
                        help="Public Pages only: uncredentialed GitHub GET candidates on open/refresh")
    parser.add_argument("--role", default="all")
    parser.add_argument("--issue-type", default="all")
    parser.add_argument("--state", choices=("all", "open", "closed"), default="all")
    parser.add_argument("--reply", default="all")
    args = parser.parse_args(argv)
    try:
        if args.public_live and (args.format != "html" or args.public_json_out is None):
            _fail("PUBLIC_LIVE_REQUIRES_PAIRED_HTML_INDEX")
        if (len(args.repository) > MAX_REPOSITORIES
                or len(set(args.repository)) != len(args.repository)
                or any(not REPOSITORY.fullmatch(r) for r in args.repository)):
            _fail("INVALID_REPOSITORY_SET")
        search_results = {r: search_repository(r) for r in args.repository}
        result = build_search_list(
            args.repository, search_results, fetch_original_issue=fetch_issue,
            fetch_comments=fetch_gh_pages,
            expected_actor=args.expect_source_actor, recipient=args.recipient,
        )
    except (InvalidMessage, OSError, UnicodeError) as exc:
        result = {
            "status": "BLOCKED", "reason_code": (
                str(exc) if isinstance(exc, InvalidMessage)
                else "SOURCE_READ_UNAVAILABLE"
            ), "has_unknown_work": True, "read_only": True,
            "fallback_retirement_authorized": False,
        }
    if args.public_json_out is not None:
        if args.format != "html" or result["status"] == "BLOCKED":
            # Never emit a stale/empty publicly trusted-looking JSON on failure.
            if result["status"] != "BLOCKED":
                print(machine_json({"status": "BLOCKED", "reason_code": "PUBLIC_INDEX_REQUIRES_HTML"}))
            return 2
        try:
            Path(args.public_json_out).write_text(
                machine_json(to_public_index(result)) + "\n", encoding="ascii")
        except (OSError, ValueError):
            # No HTML success must be published without its paired index.
            print(machine_json({"status": "BLOCKED", "reason_code": "PUBLIC_INDEX_WRITE_FAILED"}))
            return 2
    if args.format == "json" or (args.format == "markdown" and result["status"] == "BLOCKED"):
        print(machine_json(result))
    elif args.format == "html":
        # Even blocked reads are an explicit, readable offline diagnostic page.
        print(to_html(result, public_live=args.public_live))
    else:
        display = to_markdown(result, role=args.role, issue_type=args.issue_type,
                              state=args.state, reply=args.reply)
        print(console_text(display, getattr(sys.stdout, "encoding", None)))
    return 0 if result["status"] == "BOUNDED_SEARCH_READ" else 2


if __name__ == "__main__":
    sys.exit(main())
