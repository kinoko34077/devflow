"""B6-D read-only: published KAEP candidate GET -> LIVE canonical original Issue audit.

The Pages JSON is a NON-authoritative locator cache. This tool never starts a
model, sends PING, changes an Issue or grants recipient work. It reuses the
existing exact original-Issue search-list validator, not a new KAEP codec.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

from tools.kaep_inbox_reader import InvalidMessage, RECIPIENTS, fetch_gh_pages
from tools.kaep_issue_list_html import _safe_link
from tools.kaep_issue_search_view import build_search_list, fetch_issue

PUBLIC_INDEX_URL = "https://kinoko34077.github.io/devflow/kaep/index.json"
MAX_INDEX_BYTES = 1_000_000
MAX_CANDIDATE_ISSUES = 40
MAX_ROWS = 4000
SCHEMA = "kaep.public-source-index.v1"
MESSAGE = re.compile(r"msg_[A-Za-z0-9_-]{1,72}\Z")
REPOSITORY = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+\Z")


def _block(code: str) -> None:
    raise InvalidMessage(code)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = {}
    for k, value in pairs:
        if k in out:
            _block("DUPLICATE_INDEX_FIELD")
        out[k] = value
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def fetch_public_json() -> dict[str, Any]:
    """Uncredentialed HTTPS GET of exactly one pinned Pages candidate index."""
    request = urllib.request.Request(
        PUBLIC_INDEX_URL, headers={"Accept": "application/json",
                                   "User-Agent": "KiNoTch-devflow-KAEP-readonly/1"},
        method="GET",
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=15) as response:
            if response.status != 200:
                _block("PUBLIC_INDEX_HTTP_FAILED")
            size = response.headers.get("Content-Length")
            if size and (not size.isdigit() or int(size) > MAX_INDEX_BYTES):
                _block("PUBLIC_INDEX_TOO_LARGE")
            blob = response.read(MAX_INDEX_BYTES + 1)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise InvalidMessage("PUBLIC_INDEX_READ_UNAVAILABLE") from exc
    if len(blob) > MAX_INDEX_BYTES:
        _block("PUBLIC_INDEX_TOO_LARGE")
    try:
        return json.loads(blob.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, InvalidMessage):
            raise
        raise InvalidMessage("INVALID_PUBLIC_INDEX_JSON") from exc


def validate_index(index: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Treat every published field as untrusted; never turn it into authority."""
    if type(index) is not dict or index.get("schema_version") != SCHEMA:
        _block("INVALID_PUBLIC_INDEX_SCHEMA")
    if (index.get("kind") != "NON_AUTHORITATIVE_CANDIDATE_SNAPSHOT"
            or index.get("status") not in ("BOUNDED_SEARCH_READ", "PARTIAL_UNKNOWN")
            or index.get("has_unknown_work") is not True
            or index.get("complete_source_universe") is not False
            or index.get("can_authorize_execution") is not False
            or index.get("fallback_retirement_authorized") is not False
            or index.get("requires_live_original_issue_revalidation") is not True):
        _block("PUBLIC_INDEX_FALSE_AUTHORITY")
    repos, rows = index.get("repositories"), index.get("rows")
    if (type(repos) is not list or not 1 <= len(repos) <= 3
            or len(set(map(str, repos))) != len(repos)
            or any(type(r) is not str or not REPOSITORY.fullmatch(r) for r in repos)
            or type(rows) is not list or len(rows) > MAX_ROWS):
        _block("INVALID_PUBLIC_INDEX_SCOPE")
    timestamp = index.get("observed_at")
    try:
        when = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError("not timezone aware")
        when = when.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidMessage("INVALID_PUBLIC_INDEX_TIMESTAMP") from exc
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (now - when).total_seconds()
    if age < -300:
        _block("PUBLIC_INDEX_FROM_FUTURE")
    for row in rows:
        if type(row) is not dict:
            _block("INVALID_PUBLIC_INDEX_ROW")
        repo, issue, cid = (row.get("repository"), row.get("issue_number"),
                            row.get("source_comment_id"))
        if (type(repo) is not str or repo not in repos
                or type(issue) is not int or issue < 1
                or type(cid) is not int or cid < 1
                or row.get("recipient") not in RECIPIENTS
                or type(row.get("message_id")) is not str
                or not MESSAGE.fullmatch(row["message_id"])):
            _block("INVALID_PUBLIC_INDEX_ROW")
        url = f"https://github.com/{repo}/issues/{issue}"
        comment = f"{url}#issuecomment-{cid}"
        if (row.get("issue_url") != url or row.get("source_url") != comment
                or not _safe_link(url, source=False)
                or not _safe_link(comment, source=True)):
            _block("INVALID_PUBLIC_INDEX_LOCATOR")
    return {"snapshot_age_seconds": round(max(age, 0)),
            "snapshot_stale": age > 300, "candidate_row_count": len(rows)}


def read_live_candidate_cohort(
    index: dict[str, Any], *, recipient: str,
    fetch_live_issue: Callable[[str, int], dict[str, Any]],
    fetch_live_comments: Callable[[str, int], str],
    now: datetime | None = None,
) -> dict[str, Any]:
    if recipient not in RECIPIENTS:
        _block("INVALID_RECIPIENT")
    info = validate_index(index, now=now)
    chosen = [row for row in index["rows"] if row["recipient"] == recipient]
    candidates = sorted({(row["repository"], row["issue_number"]) for row in chosen})
    if len(candidates) > MAX_CANDIDATE_ISSUES:
        _block("CANDIDATE_LIMIT")
    grouped: dict[str, dict[str, Any]] = {}
    for repo in index["repositories"]:
        these = [{"html_url": f"https://github.com/{r}/issues/{i}"}
                 for r, i in candidates if r == repo]
        grouped[repo] = {
            "items": these, "total_count": len(these),
            "incomplete_results": False,
        }
    # Native build_search_list uses EXACT current original Issue identity,
    # paginated canonical actor+KAEP codec, reply chain, bounds and quarantine.
    live = build_search_list(
        index["repositories"], grouped,
        fetch_original_issue=fetch_live_issue,
        fetch_comments=fetch_live_comments,
        expected_actor="kinoko34077",
        recipient=recipient,
        max_candidates=MAX_CANDIDATE_ISSUES,
    )
    cached_keys = {
        (row["repository"], row["issue_number"],
         row["source_comment_id"], row["message_id"]) for row in chosen
    }
    current_keys = {
        (row["repository"], row["issue_number"],
         row["source_comment_id"], row["message_id"]) for row in live["rows"]
    }
    # Cached presence and present live candidates are observations, not
    # new/overdue work assignment. Never include raw payload from the source.
    live_rows = [{
        "repository": row["repository"],
        "issue_number": row["issue_number"],
        "issue_url": row["issue_url"],
        "source_url": row["source_url"],
        "source_comment_id": row["source_comment_id"],
        "message_id": row["message_id"],
        "recipient": row["recipient"],
        "reply_observation": row["reply_observation"],
        "issue_role": row["issue_role"],
        "issue_state": row["issue_state"],
        "source_validation": row["source_validation"],
        "head_freshness": "NOT_REVALIDATED",
        "index_presence": (
            "INDEXED_AND_LIVE" if (
                row["repository"], row["issue_number"], row["source_comment_id"],
                row["message_id"]) in cached_keys else "LIVE_ORIGINAL_ONLY"
        ),
    } for row in live["rows"]]
    partial = bool(live["errors"] or live["status"] != "BOUNDED_SEARCH_READ"
                   or index["status"] != "BOUNDED_SEARCH_READ"
                   or cached_keys - current_keys)
    return {
        "schema_version": "kaep.live-candidate-check.v0.1",
        "status": "PARTIAL_UNKNOWN" if partial else "BOUNDED_LIVE_CANDIDATE_READ",
        "recipient": recipient,
        "observed_at": live["observed_at"],
        "source_index_observed_at": index["observed_at"],
        **info,
        "candidate_issues": len(candidates),
        "live_original_roots": len(current_keys),
        "indexed_rows_for_recipient": len(cached_keys),
        "new_in_live_originals": len(current_keys - cached_keys),
        "index_rows_not_verified_live": len(cached_keys - current_keys),
        "live_rows": live_rows,
        "source_errors": [
            {"reason_code": row.get("reason_code", "UNKNOWN"),
             "issue_url": row.get("owning_issue")} for row in live["errors"]
        ],
        "source_coverage": "PUBLIC_INDEX_LOCATORS_ONLY",
        "complete_source_universe": False,
        "has_unknown_work": True,
        "can_authorize_execution": False,
        "recipient_pickup_proven": False,
        "current_head_verified": False,
        "fallback_retirement_authorized": False,
        "requires_action_level_authorization": True,
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", choices=sorted(RECIPIENTS), required=True)
    parser.add_argument("--offline-index", type=Path,
                        help="Offline source fixture; otherwise pinned public HTTPS GET")
    args = parser.parse_args(argv)
    try:
        if args.offline_index is not None:
            raw = args.offline_index.read_bytes()
            if len(raw) > MAX_INDEX_BYTES:
                _block("PUBLIC_INDEX_TOO_LARGE")
            index = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
        else:
            index = fetch_public_json()
        out = read_live_candidate_cohort(
            index, recipient=args.recipient,
            fetch_live_issue=fetch_issue,
            fetch_live_comments=fetch_gh_pages,
        )
    except (InvalidMessage, ValueError, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, InvalidMessage) else "CANDIDATE_READ_UNAVAILABLE"
        out = {"status": "BLOCKED", "reason_code": reason,
               "has_unknown_work": True, "can_authorize_execution": False,
               "fallback_retirement_authorized": False, "read_only": True}
    print(json.dumps(out, ensure_ascii=True, separators=(",", ":")))
    return 0 if out["status"] == "BOUNDED_LIVE_CANDIDATE_READ" else 2


if __name__ == "__main__":
    sys.exit(main())
