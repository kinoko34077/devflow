"""B6 P3 same-run *projection*, not a hosted or authoritative Inbox API.

The original Issue/KAEP actor/recipient/reply verification belongs exclusively to
the existing union reader. This module refuses untrusted/malformed union reports,
emits redacted fixed fields only, and never creates execution authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from tools.kaep_inbox_reader import InvalidMessage
from tools.kaep_live_union_cli import RECIPIENTS

SCHEMA = "kaep.agent-current-view.v0.1"
UNION_SCHEMA = "kaep.live-union-check.v0.1"
_REPO = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+\Z")
_MESSAGE = re.compile(r"msg_[A-Za-z0-9_-]{1,72}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")
_ORIGIN = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")
MAX_ROWS = 4000
MAX_SOURCES = 40
MAX_ERRORS = 100
MAX_WARNINGS = 100


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def _issue_url(repo: str, number: int) -> str:
    return f"https://github.com/{repo}/issues/{number}"


def _source_url(repo: str, number: int, cid: int) -> str:
    return f"{_issue_url(repo, number)}#issuecomment-{cid}"


def _timestamp(text: Any, now: datetime) -> tuple[str, int]:
    if type(text) is not str or len(text) > 64:
        _fail("INVALID_AGENT_API_TIMESTAMP")
    try:
        observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            _fail("INVALID_AGENT_API_TIMESTAMP")
        observed = observed.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise InvalidMessage("INVALID_AGENT_API_TIMESTAMP") from exc
    age = int((now - observed).total_seconds())
    if age < -300:
        _fail("AGENT_API_TIMESTAMP_FROM_FUTURE")
    return observed.isoformat(), max(age, 0)


def project_agent_view(union: dict[str, Any], *, now: datetime | None = None,
                       max_fresh_age_seconds: int = 60) -> dict[str, Any]:
    """Project a just-produced read-only strict union result for machine clients.

    A caller MUST NOT accept untrusted files as model-verified source evidence.
    Use this inside the same running CLI after canonical original Issue reads.
    """
    if (type(max_fresh_age_seconds) is not int
            or not 1 <= max_fresh_age_seconds <= 3600
            or type(union) is not dict
            or union.get("schema_version") != UNION_SCHEMA
            or union.get("status") not in ("BOUNDED_UNION_READ", "PARTIAL_UNKNOWN")
            or union.get("kind") != "REQUEST_TIME_ORIGINAL_ISSUE_UNION"
            or union.get("read_only") is not True
            or union.get("has_unknown_work") is not True
            or union.get("complete_source_universe") is not False
            or union.get("can_authorize_execution") is not False
            or union.get("current_head_verified") is not False
            or union.get("recipient_pickup_proven") is not False
            or union.get("fallback_retirement_authorized") is not False):
        _fail("AGENT_API_INVALID_SOURCE")
    recipient = union.get("recipient")
    repos = union.get("repositories_checked")
    rows = union.get("live_rows")
    candidates = union.get("source_candidates")
    errors = union.get("source_errors")
    warnings = union.get("warnings")
    if (recipient not in RECIPIENTS
            or type(repos) is not list or not 1 <= len(repos) <= 3
            or len(set(map(str, repos))) != len(repos)
            or any(type(r) is not str or not _REPO.fullmatch(r) for r in repos)
            or type(rows) is not list or len(rows) > MAX_ROWS
            or type(candidates) is not list or len(candidates) > MAX_SOURCES
            or type(errors) is not list or len(errors) > MAX_ERRORS
            or type(warnings) is not list or len(warnings) > MAX_WARNINGS):
        _fail("AGENT_API_INVALID_SCOPE")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        _fail("AGENT_API_INVALID_CLOCK")
    observed, age = _timestamp(union.get("observed_at"),
                               clock.astimezone(timezone.utc))
    filtered_rows = []
    per_issue: dict[tuple[str, int], int] = {}
    seen: set[tuple[str, int, int, str]] = set()
    for row in rows:
        if type(row) is not dict:
            _fail("AGENT_API_INVALID_ROW")
        repo, number, cid, message = (
            row.get("repository"), row.get("issue_number"),
            row.get("source_comment_id"), row.get("message_id"))
        if (type(repo) is not str or repo not in repos
                or type(number) is not int or number <= 0
                or type(cid) is not int or cid <= 0
                or type(message) is not str or not _MESSAGE.fullmatch(message)
                or row.get("issue_url") != _issue_url(repo, number)
                or row.get("source_url") != _source_url(repo, number, cid)
                or row.get("recipient") != recipient
                or row.get("issue_state") not in ("open", "closed")
                or row.get("source_validation") not in
                    ("STRICT_COMPLETE_FOR_CANDIDATE", "PARTIAL_UNKNOWN")
                or type(row.get("reply_observation")) is not str
                or not _CODE.fullmatch(row["reply_observation"])
                or (repo, number, cid, message) in seen):
            _fail("AGENT_API_INVALID_ROW")
        seen.add((repo, number, cid, message))
        per_issue[(repo, number)] = per_issue.get((repo, number), 0) + 1
        filtered_rows.append({
            "repository": repo, "issue_number": number,
            "issue_url": _issue_url(repo, number),
            "source_url": _source_url(repo, number, cid),
            "source_comment_id": cid, "message_id": message,
            "recipient": recipient, "issue_state": row["issue_state"],
            "reply_observation": row["reply_observation"],
            "source_validation": row["source_validation"],
            "is_authoritative_assignment": False,
        })

    filtered_candidates = []
    seen_issues: set[tuple[str, int]] = set()
    for c in candidates:
        if type(c) is not dict:
            _fail("AGENT_API_INVALID_CANDIDATE")
        repo, number, count, observation = (
            c.get("repository"), c.get("issue_number"),
            c.get("matching_recipient_roots"), c.get("source_observation"))
        if (type(repo) is not str or repo not in repos
                or type(number) is not int or number <= 0
                or c.get("issue_url") != _issue_url(repo, number)
                or c.get("grants_work_authority") is not False
                or type(count) is not int or count < 0
                or count != per_issue.get((repo, number), 0)
                or observation not in ("ACCEPTED_RECIPIENT_ROOTS",
                                       "NO_ACCEPTED_RECIPIENT_ROOT_OBSERVED",
                                       "SOURCE_VALIDATION_UNKNOWN")
                or type(c.get("origin")) is not str
                or not _ORIGIN.fullmatch(c["origin"])
                or (repo, number) in seen_issues):
            _fail("AGENT_API_INVALID_CANDIDATE")
        seen_issues.add((repo, number))
        filtered_candidates.append({
            "repository": repo, "issue_number": number,
            "issue_url": _issue_url(repo, number),
            "matching_recipient_roots": count,
            "source_observation": observation,
            "candidate_origin": c["origin"],
            "grants_work_authority": False,
        })
    if set(per_issue) - seen_issues:
        _fail("AGENT_API_UNMATCHED_ROOT")

    filtered_errors = []
    for e in errors:
        if type(e) is not dict or type(e.get("reason_code")) is not str or not _CODE.fullmatch(e["reason_code"]):
            _fail("AGENT_API_INVALID_ERROR")
        url = e.get("issue_url")
        if url is not None and url not in {_issue_url(r, n) for r, n in seen_issues}:
            _fail("AGENT_API_INVALID_ERROR")
        filtered_errors.append({"reason_code": e["reason_code"], "issue_url": url})
    filtered_warnings = []
    for w in warnings:
        if (type(w) is not dict or w.get("repository") not in repos
                or type(w.get("reason_code")) is not str
                or not _CODE.fullmatch(w["reason_code"])):
            _fail("AGENT_API_INVALID_WARNING")
        filtered_warnings.append({
            "repository": w["repository"], "reason_code": w["reason_code"]})

    source_status = union["status"]
    return {
        "schema_version": SCHEMA,
        "kind": "SAME_RUN_STRICT_SOURCE_OBSERVATION_NOT_HOSTED",
        "status": source_status,
        "recipient": recipient,
        "observed_at": observed,
        "observation_age_seconds": age,
        "observation_within_target_age": age <= max_fresh_age_seconds,
        "freshness_limit_seconds": max_fresh_age_seconds,
        "repositories_checked": list(repos),
        "source_issues_checked": len(filtered_candidates),
        "rows": filtered_rows,
        "candidates": filtered_candidates,
        "source_errors": filtered_errors,
        "warnings": filtered_warnings,
        "has_unknown_work": True,
        "complete_source_universe": False,
        "absence_of_work_proven": False,
        "recipient_pickup_proven": False,
        "current_head_verified": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
        "http_endpoint_deployed": False,
        "requires_original_source_recheck_before_action": True,
        "read_only": True,
    }
