"""GET-only per-original KAEP source-to-approved-index pointer audit (Issue #771).

Do not infer all-source coverage, pending work, recipient pickup, or permission
from a finite source/index observation. Reuse existing canonical wire decoders.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from tools.kaep_discovery_reader import parse_pointer
from tools.kaep_inbox_reader import InvalidMessage, fetch_gh_pages, parse_pages
from tools.kaep_mailbox_codec import (
    MARKER, decode_comment, read_mailbox,
)
from tools.kaep_route_notice import (
    DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE, DISCOVERY_REPOSITORY,
    verify_source_request,
)
from tools.kaep_mailbox_support import ACTOR, matching_actor

MAX_INDEX_COMMENTS = 500


def audit_route(
    source_pages: str,
    index_pages: str,
    *,
    repository: str,
    issue: int,
    message_id: str,
    expected_source_actor: str,
    expected_notice_actor: str,
    discovery_issue: int = DISCOVERY_ISSUE,
) -> dict[str, Any]:
    """Verify one original request and observe exact matching stored pointers.

    The source is verified independently before index matching. Only an
    actually matched, strict owner-authored pointer is affirmative evidence.
    Unrecognized/invalid index messages prohibit a negative completeness
    conclusion; they never become valid pointers.
    """
    if (type(discovery_issue) is not int or discovery_issue not in
            (DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE)):
        raise InvalidMessage("DISCOVERY_INDEX_NOT_APPROVED")
    if repository == DISCOVERY_REPOSITORY and issue in (
            DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE):
        raise InvalidMessage("DISCOVERY_LOOP")
    source = verify_source_request(
        source_pages, repository=repository, issue=issue,
        message_id=message_id, expected_actor=expected_source_actor,
    )
    comments = parse_pages(
        index_pages, repository=DISCOVERY_REPOSITORY, issue=discovery_issue,
    )
    if len(comments) > MAX_INDEX_COMMENTS:
        raise InvalidMessage("DISCOVERY_INDEX_TOO_LARGE")
    if (type(expected_notice_actor) is not str
            or ACTOR.fullmatch(expected_notice_actor) is None):
        raise InvalidMessage("INVALID_NOTICE_ACTOR")

    matches: list[int] = []
    warnings: list[dict[str, Any]] = []
    index_messages: list[dict[str, Any]] = []
    for comment in comments:
        body = comment["body"]
        if not body.startswith(MARKER):
            continue
        cid = comment["id"]
        if not matching_actor(comment, expected_notice_actor):
            warnings.append({"index_comment_id": cid, "reason_code": "UNTRUSTED_DISCOVERY_ACTOR"})
            continue
        try:
            msg = decode_comment(
                body, task_ref=f"{DISCOVERY_REPOSITORY}#{discovery_issue}",
            )
            index_messages.append({"id": cid, "body": body})
            # Only the already accepted discovery REQUEST envelope is
            # considered, never arbitrary JSON in a comment or Issue title.
            if (msg["recipient"] != "claude-code" or msg["kind"] != "REQUEST"
                    or msg["intent"] != "REPORT" or msg["in_reply_to"] is not None
                    or msg["scope"]["effect"] != "READ_ONLY"):
                continue
            pointer = parse_pointer(msg["payload"]["text"])
            if pointer is None:
                continue
            if pointer == source:
                matches.append(cid)
            elif (pointer["owning_issue"] == source["owning_issue"]
                  and pointer["message_id"] == source["message_id"]):
                warnings.append({
                    "index_comment_id": cid,
                    "reason_code": "DISCOVERY_SOURCE_MISMATCH",
                })
        except InvalidMessage as exc:
            warnings.append({
                "index_comment_id": cid, "reason_code": str(exc),
            })

    # Reuse the full canonical replay/collision check when no invalid index
    # marker was seen. In a partial observation never suppress errors.
    if not warnings:
        try:
            read_mailbox(
                [{"id": row["id"], "body": row["body"]} for row in index_messages],
                task_ref=f"{DISCOVERY_REPOSITORY}#{discovery_issue}",
            )
        except InvalidMessage as exc:
            warnings.append({"reason_code": str(exc)})

    # Even a positive exact match never proves *all* source Issues, current
    # HEAD, or a recipient session. Unverified index entries remain UNKNOWN.
    status = (
        "PARTIAL_UNKNOWN" if warnings else
        "EXACT_POINTER_OBSERVED" if matches else
        "EXACT_POINTER_NOT_OBSERVED"
    )
    return {
        "schema_version": "kaep.source-route-audit.v0.1",
        "discovery_issue": f"{DISCOVERY_REPOSITORY}#{discovery_issue}",
        "status": status,
        "owning_issue": source["owning_issue"],
        "source_comment_id": source["comment_id"],
        "source_message_id": source["message_id"],
        "pointer_comment_ids": sorted(set(matches)),
        "exact_pointer_observed": bool(matches),
        "index_comments_observed": len(comments),
        "index_warnings": warnings,
        "has_unknown_work": True,
        "complete_source_universe": False,
        "current_head_verified": False,
        "recipient_pickup_proven": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--expect-source-actor", required=True)
    parser.add_argument("--expect-notice-actor", required=True)
    parser.add_argument("--discovery-issue", type=int, default=DISCOVERY_ISSUE,
                        help="Default legacy #503; explicitly approved successor #789")
    args = parser.parse_args(argv)
    try:
        # Reject arbitrary index targets before any network GET.
        if args.discovery_issue not in (DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE):
            raise InvalidMessage("DISCOVERY_INDEX_NOT_APPROVED")
        original = fetch_gh_pages(args.repository, args.issue)
        index = fetch_gh_pages(DISCOVERY_REPOSITORY, args.discovery_issue)
        out = audit_route(
            original, index, repository=args.repository,
            issue=args.issue, message_id=args.message_id,
            expected_source_actor=args.expect_source_actor,
            expected_notice_actor=args.expect_notice_actor,
            discovery_issue=args.discovery_issue,
        )
    except (InvalidMessage, ValueError, OSError, UnicodeError) as exc:
        out = {
            "status": "BLOCKED",
            "reason_code": str(exc) if isinstance(exc, InvalidMessage)
            else "SOURCE_OR_INDEX_READ_UNAVAILABLE",
            "read_only": True, "has_unknown_work": True,
            "can_authorize_execution": False,
            "fallback_retirement_authorized": False,
        }
    print(json.dumps(out, ensure_ascii=True, separators=(",", ":")))
    return 0 if out["status"] == "EXACT_POINTER_OBSERVED" else 2


if __name__ == "__main__":
    sys.exit(main())

