"""B5 read-only source-cohort parity: legacy shadow vs strict live recipient union.

This is a comparison of two *untrusted report files*, NEVER a source-of-truth
reader. Results cannot prove a synchronized snapshot, complete Inbox or work
authority. Neither decoder is replaced by this module.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

from tools.kaep_inbox_reader import InvalidMessage

MAX_REPORT_BYTES = 2_000_000
SHADOW_LIMIT = 20
UNION_LIMIT = 40
MAX_UNION_ROWS = 5000
ISSUE_URL = re.compile(r"https://github\.com/(kinoko34077/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)\Z")
MESSAGE_ID = re.compile(r"msg_[A-Za-z0-9_-]{1,72}\Z")
REASONS = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")


def _deny(reason: str) -> None:
    raise InvalidMessage(reason)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in pairs:
        if k in result:
            _deny("DUPLICATE_REPORT_FIELD")
        result[k] = v
    return result


def _issue_key(url: Any) -> tuple[str, int]:
    m = ISSUE_URL.fullmatch(url) if type(url) is str else None
    if m is None:
        _deny("INVALID_REPORT_ISSUE_URL")
    return m.group(1), int(m.group(2))


def _validate_shadow(doc: Any) -> tuple[dict[tuple[str, int], set[tuple[int, str]]], set[tuple[str, int]], bool]:
    if (type(doc) is not dict
            or doc.get("schema_version") != "kaep.source-roster-shadow.v0.1"
            or doc.get("status") not in ("BOUNDED_CANDIDATE_SOURCE_READ", "PARTIAL_UNKNOWN")
            or doc.get("recipient") != "claude-code"
            or doc.get("read_only") is not True
            or doc.get("has_unknown_work") is not True
            or doc.get("complete_source_universe") is not False
            or doc.get("can_authorize_execution") is not False
            or doc.get("fallback_retirement_authorized") is not False
            or type(doc.get("issues")) is not list
            or len(doc["issues"]) > SHADOW_LIMIT
            or type(doc.get("errors")) is not list
            or len(doc["errors"]) > 100):
        _deny("INVALID_SHADOW_REPORT")
    valid: dict[tuple[str, int], set[tuple[int, str]]] = {}
    covered: set[tuple[str, int]] = set()
    for issue in doc["issues"]:
        if type(issue) is not dict:
            _deny("INVALID_SHADOW_ISSUE")
        key = _issue_key(issue.get("owning_issue"))
        roots = issue.get("roots")
        if (key in covered or type(roots) is not list or len(roots) > 500
                or type(issue.get("root_count")) is not int
                or issue["root_count"] != len(roots)
                or issue.get("source_state") != "AVAILABLE"):
            _deny("INVALID_SHADOW_ISSUE")
        covered.add(key)
        entries: set[tuple[int, str]] = set()
        for root in roots:
            if type(root) is not dict:
                _deny("INVALID_SHADOW_ROOT")
            cid, mid = root.get("source_comment_id"), root.get("source_message_id")
            if (type(cid) is not int or cid <= 0
                    or type(mid) is not str or MESSAGE_ID.fullmatch(mid) is None
                    or (cid, mid) in entries):
                _deny("INVALID_SHADOW_ROOT")
            entries.add((cid, mid))
        valid[key] = entries
    errors = doc["errors"]
    global_unknown = False
    for err in errors:
        if (type(err) is not dict or type(err.get("reason_code")) is not str
                or REASONS.fullmatch(err["reason_code"]) is None):
            _deny("INVALID_SHADOW_ERROR")
        if err.get("owning_issue") is None:
            global_unknown = True
        else:
            key = _issue_key(err["owning_issue"])
            valid.pop(key, None)
    return valid, covered, global_unknown


def _validate_union(doc: Any) -> tuple[dict[tuple[str, int], set[tuple[int, str]]], set[tuple[str, int]], bool]:
    if (type(doc) is not dict
            or doc.get("schema_version") != "kaep.live-union-check.v0.1"
            or doc.get("kind") != "REQUEST_TIME_ORIGINAL_ISSUE_UNION"
            or doc.get("status") not in ("BOUNDED_UNION_READ", "PARTIAL_UNKNOWN")
            or doc.get("recipient") != "claude-code"
            or doc.get("read_only") is not True
            or doc.get("has_unknown_work") is not True
            or doc.get("complete_source_universe") is not False
            or doc.get("can_authorize_execution") is not False
            or doc.get("recipient_pickup_proven") is not False
            or doc.get("fallback_retirement_authorized") is not False
            or type(doc.get("source_candidates")) is not list
            or len(doc["source_candidates"]) > UNION_LIMIT
            or type(doc.get("live_rows")) is not list
            or len(doc["live_rows"]) > MAX_UNION_ROWS
            or type(doc.get("source_errors")) is not list
            or len(doc["source_errors"]) > 100):
        _deny("INVALID_UNION_REPORT")
    valid: dict[tuple[str, int], set[tuple[int, str]]] = {}
    covered: set[tuple[str, int]] = set()
    for c in doc["source_candidates"]:
        if type(c) is not dict:
            _deny("INVALID_UNION_CANDIDATE")
        key = _issue_key(c.get("issue_url"))
        if (c.get("repository") != key[0]
                or type(c.get("issue_number")) is not int or c["issue_number"] != key[1]
                or c.get("grants_work_authority") is not False
                or type(c.get("matching_recipient_roots")) is not int
                or c["matching_recipient_roots"] < 0
                or c.get("source_observation") not in (
                    "ACCEPTED_RECIPIENT_ROOTS", "NO_ACCEPTED_RECIPIENT_ROOT_OBSERVED",
                    "SOURCE_VALIDATION_UNKNOWN")
                or key in covered):
            _deny("INVALID_UNION_CANDIDATE")
        covered.add(key)
        if c["source_observation"] != "SOURCE_VALIDATION_UNKNOWN":
            valid[key] = set()
    for row in doc["live_rows"]:
        if type(row) is not dict:
            _deny("INVALID_UNION_ROOT")
        key = _issue_key(row.get("issue_url"))
        cid, mid = row.get("source_comment_id"), row.get("message_id")
        if (key not in covered or row.get("repository") != key[0]
                or type(row.get("issue_number")) is not int or row["issue_number"] != key[1]
                or type(cid) is not int or cid <= 0
                or row.get("source_url") != f"https://github.com/{key[0]}/issues/{key[1]}#issuecomment-{cid}"
                or type(mid) is not str or MESSAGE_ID.fullmatch(mid) is None
                or row.get("recipient") != "claude-code"
                or row.get("source_validation") != "STRICT_COMPLETE_FOR_CANDIDATE"):
            _deny("INVALID_UNION_ROOT")
        if key not in valid:
            continue  # an invalid original Issue cannot prove parity
        if (cid, mid) in valid[key]:
            _deny("DUPLICATE_UNION_ROOT")
        valid[key].add((cid, mid))
    for c in doc["source_candidates"]:
        key = _issue_key(c["issue_url"])
        if key in valid and c["matching_recipient_roots"] != len(valid[key]):
            _deny("INVALID_UNION_ROOT_COUNT")
    global_unknown = False
    for err in doc["source_errors"]:
        if type(err) is not dict or type(err.get("reason_code")) is not str or REASONS.fullmatch(err["reason_code"]) is None:
            _deny("INVALID_UNION_ERROR")
        url = err.get("owning_issue")
        if url is None:
            global_unknown = True
        else:
            key = _issue_key(url)
            valid.pop(key, None)
    return valid, covered, global_unknown


def compare_reports(shadow: dict[str, Any], union: dict[str, Any]) -> dict[str, Any]:
    """Compare only sources that both reports explicitly checked and validated.

    Different observations may have genuine intervening updates. This tool
    NEVER labels a difference as decoder corruption or actionable work.
    """
    svalid, scovered, sglobal = _validate_shadow(shadow)
    uvalid, ucovered, uglobal = _validate_union(union)
    shared = scovered & ucovered
    matched = sorted(shared & svalid.keys() & uvalid.keys())
    matches, differences = [], []
    for repo, number in matched:
        a, b = svalid[(repo, number)], uvalid[(repo, number)]
        item = {
            "issue_url": f"https://github.com/{repo}/issues/{number}",
            "shadow_root_count": len(a),
            "union_root_count": len(b),
            "shadow_only_root_count": len(a - b),
            "union_only_root_count": len(b - a),
        }
        (matches if a == b else differences).append(item)
    return {
        "schema_version": "kaep.b5-b6-source-parity.v0.1",
        "kind": "READ_ONLY_UNTRUSTED_REPORT_COHORT_COMPARISON",
        "status": "OBSERVED_DISAGREEMENT" if differences else (
            "PARTIAL_UNKNOWN" if (sglobal or uglobal or len(matched) != len(shared)
                                  or shadow["status"] != "BOUNDED_CANDIDATE_SOURCE_READ"
                                  or union["status"] != "BOUNDED_UNION_READ")
            else "BOUNDED_SHARED_SOURCE_MATCH"),
        "recipient": "claude-code",
        "shadow_source_issues_observed": len(scovered),
        "union_source_issues_observed": len(ucovered),
        "shared_issue_count": len(shared),
        "shared_issue_compared": len(matched),
        "shared_issue_unknown": len(shared) - len(matched),
        "shadow_only_issue_count": len(scovered - ucovered),
        "union_only_issue_count": len(ucovered - scovered),
        "same_source_matches": matches,
        "same_source_disagreements": differences,
        "source_universe_proven_complete": False,
        "same_snapshot_proven": False,
        "recipient_pickup_proven": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
        "has_unknown_work": True,
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shadow-report", type=Path, required=True)
    p.add_argument("--union-report", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        def read(path: Path) -> Any:
            raw = path.read_bytes()
            if len(raw) > MAX_REPORT_BYTES:
                _deny("REPORT_TOO_LARGE")
            return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
        out = compare_reports(read(args.shadow_report), read(args.union_report))
    except (InvalidMessage, OSError, ValueError, UnicodeError, RecursionError) as exc:
        out = {
            "status": "BLOCKED",
            "reason_code": str(exc) if isinstance(exc, InvalidMessage) else "INVALID_OR_UNREADABLE_REPORT",
            "has_unknown_work": True, "can_authorize_execution": False,
            "fallback_retirement_authorized": False, "read_only": True,
        }
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0 if out["status"] == "BOUNDED_SHARED_SOURCE_MATCH" else 2


if __name__ == "__main__":
    sys.exit(main())
