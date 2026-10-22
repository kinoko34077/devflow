"""Opt-in two-phase original KAEP REQUEST + #503 pointer readback (#771).

Reuses the existing, independently verified source and notice writers. GitHub
comments across two Issues are NOT atomic. A partial result must be retried
through the same stable request identity; never infer agent delivery or work
authority from two successful comment posts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.kaep_inbox_reader import InvalidMessage, REPOSITORY, fetch_gh_pages
from tools.kaep_request_sender import send_request
from tools.kaep_route_notice import (
    DISCOVERY_REPOSITORY, DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE,
    route_request, verify_public_source,
)
from tools.kaep_reply_sender import ACTOR, _mailbox

_SUPPORTED_INTENTS = frozenset(("ANALYZE", "REPORT"))
_SOURCE_STORED = frozenset(("SENT_AND_READ_BACK", "ALREADY_SENT"))
_ROUTE_STORED = frozenset(("SENT_AND_READ_BACK", "ALREADY_SENT"))


def _base() -> dict[str, Any]:
    return {
        "schema_version": "kaep.two-phase-source-route.v0.1",
        "recipient": "claude-code",
        "source_comment_id": None,
        "discovery_comment_id": None,
        "source_status": None,
        "route_status": None,
        "has_unknown_work": True,
        "source_universe_complete": False,
        "recipient_pickup_proven": False,
        "delivery_confirmed": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
        "agent_woken": False,
    }


def _discovery_read_preflight(offline_pages: str | None, discovery_issue: int = DISCOVERY_ISSUE) -> None:
    """Prove the current #503 mailbox can be read by the existing strict writer.

    Before the first source POST, reject malformed trusted/untrusted KAEP
    markers, duplicate IDs, broken reply chains, incomplete pagination, and
    transport errors. This does not relax the codec or repair old comments.
    """
    pages = (offline_pages if offline_pages is not None else
             fetch_gh_pages(DISCOVERY_REPOSITORY, discovery_issue))
    _mailbox(pages, repository=DISCOVERY_REPOSITORY, issue=discovery_issue)


def publish_source_and_route(
    *,
    repository: str,
    issue: int,
    intent: str,
    request_key: str,
    request_text: str,
    expected_source_actor: str,
    expected_notice_actor: str,
    expected_head: str | None = None,
    do_send: bool = False,
    discovery_issue: int = DISCOVERY_ISSUE,
    offline_source_pages: str | None = None,
    offline_discovery_pages: str | None = None,
) -> dict[str, Any]:
    """Reconcile two existing writer steps; never silently retry uncertain POSTs.

    No write occurs unless do_send=True and no offline fixture is supplied.
    Return recoverable partial receipt if and only if the source was proved
    stored but route verification failed. A caller may safely retry the same
    stable request_key, using existing source/route idempotency.
    """
    if type(do_send) is not bool:
        raise InvalidMessage("INVALID_SEND_MODE")
    # Never allow a free-form public destination, including for dry-run.
    if (type(discovery_issue) is not int or discovery_issue not in
            (DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE)):
        raise InvalidMessage("DISCOVERY_INDEX_NOT_APPROVED")
    # Route eligibility must be checked before the original Issue POST.
    # Once the source is written an invalid target cannot be rolled back.
    if (type(repository) is not str or REPOSITORY.fullmatch(repository) is None
            or type(issue) is not int or issue < 1):
        raise InvalidMessage("INVALID_TARGET")
    if repository == DISCOVERY_REPOSITORY and issue in (
            DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE):
        raise InvalidMessage("DISCOVERY_LOOP")
    if (type(expected_notice_actor) is not str
            or ACTOR.fullmatch(expected_notice_actor) is None):
        raise InvalidMessage("INVALID_ACTOR")
    if intent not in _SUPPORTED_INTENTS:
        raise InvalidMessage("ROUTE_UNSUPPORTED_INTENT")
    if (offline_source_pages is None) != (offline_discovery_pages is None):
        raise InvalidMessage("INCOMPLETE_OFFLINE_FIXTURE")
    if do_send and offline_source_pages is not None:
        raise InvalidMessage("OFFLINE_POST_FORBIDDEN")
    if do_send:
        # Existing policy: never put a private source Issue locator in the
        # world-readable #503 mailbox. Check BEFORE the first public POST.
        verify_public_source(repository)

    out = _base()
    out["discovery_issue"] = f"{DISCOVERY_REPOSITORY}#{discovery_issue}"
    try:
        # Existing route_request invokes the strict selected-index mailbox writer.
        # That same mailbox MUST be readable before the first original POST;
        # otherwise a known bad index produces a preventable partial write.
        _discovery_read_preflight(offline_discovery_pages, discovery_issue)
    except (InvalidMessage, OSError, UnicodeError) as exc:
        out["status"] = "DISCOVERY_PREFLIGHT_BLOCKED"
        out["reason_code"] = (str(exc) if isinstance(exc, InvalidMessage)
                              else "DISCOVERY_READ_UNAVAILABLE")
        return out

    try:
        src = send_request(
            repository=repository, issue=issue, recipient="claude-code",
            intent=intent, request_key=request_key,
            request_text=request_text,
            expect_existing_actor=expected_source_actor,
            expected_head=expected_head, do_send=do_send,
            offline_pages=offline_source_pages,
        )
    except (InvalidMessage, OSError, UnicodeError):
        # An uncertain response to the first POST may represent a committed
        # comment. No automated retry or speculative pointer publication.
        out["status"] = "SOURCE_NOT_VERIFIED"
        out["reason_code"] = "SOURCE_POST_OR_READBACK_UNVERIFIED"
        return out

    out["source_status"] = src.get("status")
    out["source_comment_id"] = src.get("posted_comment_id")
    out["source_message_id"] = src.get("message_id")
    if out["source_status"] not in _SOURCE_STORED:
        out["status"] = "SOURCE_PREPARED_ONLY" if not do_send else "SOURCE_NOT_VERIFIED"
        return out
    if (type(out["source_comment_id"]) is not int
            or out["source_comment_id"] < 1):
        out["status"] = "SOURCE_NOT_VERIFIED"
        out["reason_code"] = "INVALID_SOURCE_RECEIPT"
        return out

    try:
        notice = route_request(
            repository=repository, issue=issue,
            message_id=out["source_message_id"],
            expected_source_actor=expected_source_actor,
            expected_notice_actor=expected_notice_actor,
            do_send=do_send, discovery_issue=discovery_issue,
            offline_source_pages=offline_source_pages,
            offline_discovery_pages=offline_discovery_pages,
        )
    except (InvalidMessage, OSError, UnicodeError):
        out["status"] = "SOURCE_STORED_ROUTE_UNVERIFIED"
        out["reason_code"] = "ROUTE_POST_OR_READBACK_UNVERIFIED"
        return out

    out["route_status"] = notice.get("status")
    out["discovery_comment_id"] = notice.get("discovery_comment_id")
    if (out["route_status"] in _ROUTE_STORED
            and type(out["discovery_comment_id"]) is int
            and out["discovery_comment_id"] > 0):
        out["status"] = "SOURCE_AND_POINTER_READBACK"
    elif not do_send and out["route_status"] == "PREPARED":
        out["status"] = "SOURCE_STORED_ROUTE_PREPARED"
    else:
        out["status"] = "SOURCE_STORED_ROUTE_UNVERIFIED"
        out["reason_code"] = "INVALID_ROUTE_RECEIPT"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--intent", required=True, choices=sorted(_SUPPORTED_INTENTS))
    parser.add_argument("--request-key", required=True)
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--expect-source-actor", required=True)
    parser.add_argument("--expect-notice-actor", required=True)
    parser.add_argument("--expected-head")
    parser.add_argument("--offline-source-pages", type=Path)
    parser.add_argument("--offline-discovery-pages", type=Path)
    parser.add_argument("--discovery-issue", type=int, default=DISCOVERY_ISSUE,
                        help="Default legacy #503; explicit approved #789 only for successor")
    parser.add_argument("--send", action="store_true", help="Explicitly opt in to two existing Issue POSTs")
    args = parser.parse_args(argv)
    try:
        out = publish_source_and_route(
            repository=args.repository, issue=args.issue,
            intent=args.intent, request_key=args.request_key,
            request_text=args.text_file.read_text(encoding="utf-8"),
            expected_source_actor=args.expect_source_actor,
            expected_notice_actor=args.expect_notice_actor,
            expected_head=args.expected_head,
            do_send=args.send, discovery_issue=args.discovery_issue,
            offline_source_pages=args.offline_source_pages.read_text(encoding="utf-8")
            if args.offline_source_pages else None,
            offline_discovery_pages=args.offline_discovery_pages.read_text(encoding="utf-8")
            if args.offline_discovery_pages else None,
        )
    except (InvalidMessage, OSError, UnicodeError) as exc:
        out = _base()
        out["status"] = "BLOCKED"
        out["reason_code"] = str(exc) if isinstance(exc, InvalidMessage) else "SOURCE_IO_FAILED"
    print(json.dumps(out, ensure_ascii=True, separators=(",", ":")))
    return 0 if out["status"] in (
        "SOURCE_AND_POINTER_READBACK", "SOURCE_PREPARED_ONLY",
        "SOURCE_STORED_ROUTE_PREPARED",
    ) else 2


if __name__ == "__main__":
    sys.exit(main())
