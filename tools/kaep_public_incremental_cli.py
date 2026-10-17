"""Opt-in incremental public-owner KAEP locator reader, never a trusted inbox.

First read: reuse the full bounded public locator scan and record per-repository
head comment IDs. Later reads stop at the *exact* prior head; missing anchors,
failed repos and bounds prevent cursor advancement. No server, scheduler, write
to GitHub, credentials, source text or assignment.
"""
from __future__ import annotations

import argparse
import os
import stat
import tempfile
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from tools import kaep_public_locator_cli as locator
from tools.kaep_inbox_reader import InvalidMessage, MARKER
from tools.kaep_live_delta_view import API_ISSUE

CURSOR_SCHEMA = "kaep.public-marker-head-cursor.v0.1"
RESULT_SCHEMA = "kaep.public-marker-incremental.v0.1"
MAX_OWNER_REPOS = 300
MAX_CURSOR_BYTES = 131_072
_NOT_FOUND = object()


def _deny(code: str) -> None:
    raise InvalidMessage(code)


def validate_cursor(cursor: dict[str, Any]) -> dict[str, int]:
    """Untrusted checkpoint is a bounded scan accelerator only."""
    if (type(cursor) is not dict
            or set(cursor) != {"schema_version", "owner", "public_only", "heads"}
            or cursor.get("schema_version") != CURSOR_SCHEMA
            or cursor.get("owner") != locator.OWNER
            or cursor.get("public_only") is not True
            or type(cursor.get("heads")) is not dict
            or len(cursor["heads"]) > MAX_OWNER_REPOS):
        _deny("INVALID_PUBLIC_CURSOR")
    for name, head in cursor["heads"].items():
        if (type(name) is not str or not locator.REPO_NAME.fullmatch(name)
                or type(head) is not int or head < 0):
            _deny("INVALID_PUBLIC_CURSOR")
    return dict(cursor["heads"])


def _checkpoint(heads: dict[str, int]) -> dict[str, Any]:
    return {
        "schema_version": CURSOR_SCHEMA, "owner": locator.OWNER,
        "public_only": True, "heads": dict(sorted(heads.items())),
    }


def _basic(status: str, mode: str, requests: int, repo_count: int,
           locators: list[dict[str, Any]], incomplete: list[dict[str, Any]],
           checkpoint: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "kind": "UNTRUSTED_PUBLIC_MARKER_CHANGE_CANDIDATES",
        "status": status, "mode": mode,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "owner": locator.OWNER, "public_only": True, "read_only": True,
        "repository_count_observed": repo_count, "api_requests_used": requests,
        "locators": sorted(locators, key=lambda x: (x["repository"], x["issue_number"],
                                                   x["comment_id"])),
        "locator_count": len(locators),
        "incomplete_scopes": incomplete,
        "next_cursor": checkpoint,
        "cursor_advanced": checkpoint is not None,
        "has_unknown_work": True,
        "complete_source_universe": False,
        "absence_of_work_proven": False,
        "recipient_pickup_proven": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
        "requires_strict_original_issue_validation": True,
        "comment_edits_tracked": False,
        "issue_state_changes_tracked": False,
    }


def discover_incremental(
    *, prior: dict[str, Any] | None = None,
    fetch: Callable[[str], Any] = locator._gh_get,
    max_repo_pages: int = 3, max_comment_pages: int = 40,
    max_api_calls: int = 350,
) -> dict[str, Any]:
    """Full initial baseline then request-time incremental read with no state IO."""
    if (type(max_repo_pages) is not int or not 1 <= max_repo_pages <= locator.MAX_REPO_PAGES
            or type(max_comment_pages) is not int
            or not 1 <= max_comment_pages <= locator.MAX_COMMENT_PAGES
            or type(max_api_calls) is not int
            or not max_repo_pages <= max_api_calls <= locator.MAX_API_CALLS):
        _deny("INVALID_SCAN_BOUNDS")
    previous = None if prior is None else validate_cursor(prior)
    if previous is None:
        heads: dict[str, int] = {}
        def capture(path: str) -> Any:
            data = fetch(path)
            if "/issues/comments?" in path and path.endswith("&page=1"):
                name = path[len("/repos/"):].split("/issues/comments?", 1)[0]
                if type(data) is list and len(data) <= locator.PAGE_SIZE:
                    heads[name] = data[0].get("id") if data else 0
            return data
        baseline = locator.discover(
            fetch=capture, max_repo_pages=max_repo_pages,
            max_comment_pages=max_comment_pages, max_api_calls=max_api_calls)
        complete = (baseline["status"] == "BOUNDED_PUBLIC_MARKER_READ"
                    and len(heads) == baseline["repository_count_observed"]
                    and all(type(v) is int and v >= 0 for v in heads.values()))
        missing = [] if complete else (
            [{"scope": "PUBLIC_BASELINE", "reason_code": "INCOMPLETE_BASELINE"}])
        return _basic(
            "BOUNDED_INCREMENTAL_BASELINE" if complete else "PARTIAL_UNKNOWN",
            "BASELINE", baseline["api_requests_used"],
            baseline["repository_count_observed"], baseline["locators"],
            baseline["incomplete_scopes"] + missing,
            _checkpoint(heads) if complete else None,
        )

    calls = 0
    repositories: list[str] = []
    seen: set[str] = set()
    incomplete: list[dict[str, Any]] = []
    enumeration_complete = False
    for page in range(1, max_repo_pages + 1):
        if calls >= max_api_calls:
            incomplete.append({"scope": "PUBLIC_REPOSITORIES", "next_page": page,
                               "reason_code": "API_BUDGET"})
            break
        calls += 1
        path = (f"/users/{locator.OWNER}/repos?type=owner"
                f"&per_page={locator.PAGE_SIZE}&page={page}")
        try:
            result = fetch(path)
            if type(result) is not list or len(result) > locator.PAGE_SIZE:
                _deny("INVALID_PUBLIC_REPOSITORY_PAGE")
            for item in result:
                if (type(item) is not dict
                        or type(item.get("full_name")) is not str
                        or not locator.REPO_NAME.fullmatch(item["full_name"])
                        or type(item.get("owner")) is not dict
                        or item["owner"].get("login") != locator.OWNER
                        or item.get("private") is not False):
                    _deny("INVALID_PUBLIC_REPOSITORY_PAGE")
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    repositories.append(name)
        except (InvalidMessage, ValueError, TypeError, OSError):
            incomplete.append({"scope": "PUBLIC_REPOSITORIES", "next_page": page,
                               "reason_code": "REPOSITORY_READ_UNKNOWN"})
            break
        if len(result) < locator.PAGE_SIZE:
            enumeration_complete = True
            break
        if page == max_repo_pages:
            incomplete.append({"scope": "PUBLIC_REPOSITORIES", "next_page": page + 1,
                               "reason_code": "REPOSITORY_PAGE_CAP"})

    for disappeared in sorted(set(previous) - seen):
        incomplete.append({"scope": disappeared, "next_page": 1,
                           "reason_code": "PREVIOUS_PUBLIC_REPOSITORY_MISSING"})

    found: set[tuple[str, int, int]] = set()
    links: list[dict[str, Any]] = []
    observed_heads: dict[str, int] = {}
    for idx, repo in enumerate(repositories):
        old = previous.get(repo, _NOT_FOUND)
        finished = False
        current_head = _NOT_FOUND
        for page in range(1, max_comment_pages + 1):
            if calls >= max_api_calls:
                incomplete.extend(
                    {"scope": r, "next_page": page if i == idx else 1,
                     "reason_code": "API_BUDGET"}
                    for i, r in enumerate(repositories[idx:], start=idx))
                break
            calls += 1
            path = (f"/repos/{repo}/issues/comments?sort=created&direction=desc"
                    f"&per_page={locator.PAGE_SIZE}&page={page}")
            try:
                comments = fetch(path)
                if type(comments) is not list or len(comments) > locator.PAGE_SIZE:
                    _deny("INVALID_PUBLIC_COMMENT_PAGE")
                if current_head is _NOT_FOUND:
                    current_head = comments[0].get("id") if comments else 0
                if type(current_head) is not int or current_head < 0:
                    _deny("INVALID_PUBLIC_COMMENT")
                anchor_seen = False
                for item in comments:
                    if type(item) is not dict:
                        _deny("INVALID_PUBLIC_COMMENT")
                    body, cid, src = item.get("body"), item.get("id"), item.get("issue_url")
                    matched = API_ISSUE.fullmatch(src) if type(src) is str else None
                    if (type(body) is not str or type(cid) is not int or cid < 1
                            or matched is None or matched.group(1) != repo):
                        _deny("INVALID_PUBLIC_COMMENT")
                    if old is not _NOT_FOUND and old > 0 and cid == old:
                        anchor_seen = True
                        break
                    if not body.startswith(MARKER):
                        continue
                    issue = int(matched.group(2))
                    key = (repo, issue, cid)
                    if key in found:
                        continue
                    found.add(key)
                    if len(found) > locator.MAX_LOCATORS:
                        _deny("PUBLIC_LOCATOR_LIMIT")
                    url = f"https://github.com/{repo}/issues/{issue}"
                    links.append({
                        "locator": f"{repo.split('/', 1)[1]}#{issue}@{cid}",
                        "repository": repo, "issue_number": issue, "comment_id": cid,
                        "source_url": f"{url}#issuecomment-{cid}",
                        "strict_source_validated": False,
                        "is_authoritative_assignment": False,
                    })
                if anchor_seen or (
                    len(comments) < locator.PAGE_SIZE
                    and (old is _NOT_FOUND or old == 0)):
                    finished = True
                    break
                if len(comments) < locator.PAGE_SIZE:
                    incomplete.append({"scope": repo, "next_page": page,
                                       "reason_code": "PRIOR_COMMENT_HEAD_MISSING"})
                    break
                if page == max_comment_pages:
                    incomplete.append({"scope": repo, "next_page": page + 1,
                                       "reason_code": "COMMENT_PAGE_CAP"})
            except (InvalidMessage, TypeError, ValueError, OSError):
                incomplete.append({"scope": repo, "next_page": page,
                                   "reason_code": "COMMENT_PAGE_UNKNOWN"})
                break
        if finished:
            observed_heads[repo] = current_head
        if calls >= max_api_calls:
            break
    complete = (enumeration_complete and not incomplete and
                len(observed_heads) == len(repositories))
    return _basic(
        "BOUNDED_INCREMENTAL_READ" if complete else "PARTIAL_UNKNOWN",
        "INCREMENTAL", calls, len(repositories), links, incomplete,
        _checkpoint(observed_heads) if complete else None,
    )


def _read_cursor_file(path: Path) -> tuple[dict[str, Any], bytes]:
    """Read only a regular local cursor, never follow the final symlink."""
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        _deny("INVALID_PUBLIC_CURSOR_FILE")
    raw = path.read_bytes()
    if not 0 < len(raw) <= MAX_CURSOR_BYTES:
        _deny("INVALID_PUBLIC_CURSOR_FILE")
    def pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, val in pairs:
            if key in out:
                _deny("DUPLICATE_PUBLIC_CURSOR_FIELD")
            out[key] = val
        return out
    obj = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_unique)
    validate_cursor(obj)
    return obj, raw


def _persist_cursor_file(path: Path, cursor: dict[str, Any],
                         old: bytes | None) -> None:
    """Atomic replace after a same-run unchanged-file check. No scheduling."""
    validate_cursor(cursor)
    payload = (json.dumps(cursor, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("ascii")
    if len(payload) > MAX_CURSOR_BYTES:
        _deny("INVALID_PUBLIC_CURSOR")
    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=".kaep-public-cursor-", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        # Detect another writer or substitution before replacing a read cursor.
        if path.is_symlink():
            _deny("CURSOR_CHANGED_ON_DISK")
        if path.exists():
            if old is None or path.read_bytes() != old:
                _deny("CURSOR_CHANGED_ON_DISK")
        elif old is not None:
            _deny("CURSOR_CHANGED_ON_DISK")
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--cursor-in", type=Path, default=None,
                       help="Read untrusted prior cursor JSON; no local file is written")
    group.add_argument("--state-file", type=Path, default=None,
                       help="Opt-in regular local cursor file; atomically update only after full successful read")
    p.add_argument("--format", choices=("json", "lines"), default="json")
    p.add_argument("--max-repo-pages", type=int, default=3)
    p.add_argument("--max-comment-pages", type=int, default=40)
    p.add_argument("--max-api-calls", type=int, default=350)
    args = p.parse_args(argv)
    try:
        previous = None
        old_state_raw = None
        if args.state_file is not None and args.state_file.exists():
            previous, old_state_raw = _read_cursor_file(args.state_file)
        if args.cursor_in is not None:
            data = args.cursor_in.read_bytes()
            if len(data) > MAX_CURSOR_BYTES:
                _deny("INVALID_PUBLIC_CURSOR")
            def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                out: dict[str, Any] = {}
                for key, val in pairs:
                    if key in out:
                        _deny("DUPLICATE_PUBLIC_CURSOR_FIELD")
                    out[key] = val
                return out
            previous = json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs)
        result = discover_incremental(
            prior=previous, max_repo_pages=args.max_repo_pages,
            max_comment_pages=args.max_comment_pages,
            max_api_calls=args.max_api_calls)
        if args.state_file is not None and result["next_cursor"] is not None:
            try:
                _persist_cursor_file(args.state_file, result["next_cursor"], old_state_raw)
                result["local_cursor_persisted"] = True
            except (InvalidMessage, OSError, ValueError, TypeError):
                result["status"] = "PARTIAL_UNKNOWN"
                result["next_cursor"] = None
                result["cursor_advanced"] = False
                result["local_cursor_persisted"] = False
                result["incomplete_scopes"].append({
                    "scope": "LOCAL_CURSOR", "reason_code": "LOCAL_CURSOR_WRITE_FAILED"})
    except (InvalidMessage, ValueError, TypeError, OSError, UnicodeError):
        result = {
            "schema_version": RESULT_SCHEMA, "status": "BLOCKED",
            "reason_code": "PUBLIC_INCREMENTAL_READ_BLOCKED",
            "locators": [], "next_cursor": None, "cursor_advanced": False,
            "has_unknown_work": True, "complete_source_universe": False,
            "can_authorize_execution": False,
        }
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    else:
        for item in result["locators"]:
            print(item["locator"])
        print(f"# {result['status']}; new_markers={len(result['locators'])}; "
              f"repo_count={result.get('repository_count_observed', 0)}; "
              f"unknown_scopes={len(result.get('incomplete_scopes', []))}; "
              "no_work_proven=false; all_untrusted=true")
    return 0 if result["status"] in (
        "BOUNDED_INCREMENTAL_READ", "BOUNDED_INCREMENTAL_BASELINE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
