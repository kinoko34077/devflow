"""KAEP v0.2 discovery hint for an existing READ_ONLY owning-Issue request.

This is a pointer-only notice on devflow #503; it never becomes a second
work queue, task authority, provider wake mechanism, or proof of delivery.
Source request and expected GitHub actor must be verified before notification.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.kaep_inbox_reader import InvalidMessage, REPOSITORY, fetch_gh_pages
from tools.kaep_mailbox_codec import matches
from tools.kaep_reply_sender import ACTOR, _mailbox
from tools.kaep_request_sender import send_request
from tools.github_issue_trust import is_trusted_principal

DISCOVERY_REPOSITORY = "kinoko34077/devflow"
DISCOVERY_ISSUE = 503
APPROVED_SUCCESSOR_ISSUE = 789  # Explicitly user-approved public index; NOT an arbitrary target
POINTER_VERSION = "kaep.discovery-pointer.v1"


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def verify_public_source(repository: str) -> None:
    """Fail closed: never publish a private task locator into public #503."""
    if not REPOSITORY.fullmatch(repository):
        _fail("INVALID_TARGET")
    try:
        run = subprocess.run(
            ["gh", "api", f"repos/{repository}", "--method", "GET"],
            capture_output=True, text=True, timeout=20, check=False)
        if run.returncode != 0 or len(run.stdout.encode("utf-8")) > 65536:
            _fail("SOURCE_VISIBILITY_UNVERIFIED")
        meta = json.loads(run.stdout)
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as exc:
        raise InvalidMessage("SOURCE_VISIBILITY_UNVERIFIED") from exc
    if (type(meta) is not dict or meta.get("full_name") != repository
            or type(meta.get("private")) is not bool):
        _fail("SOURCE_VISIBILITY_UNVERIFIED")
    if meta["private"] is not False:
        _fail("SOURCE_NOT_PUBLIC")


def verify_source_request(
    pages: str, *, repository: str, issue: int,
    message_id: str, expected_actor: str,
) -> dict[str, Any]:
    if not REPOSITORY.fullmatch(repository) or type(issue) is not int or issue < 1:
        _fail("INVALID_TARGET")
    if (repository == DISCOVERY_REPOSITORY and issue == DISCOVERY_ISSUE):
        _fail("DISCOVERY_LOOP")
    if not matches(r"msg_[A-Za-z0-9_-]{1,72}", message_id):
        _fail("INVALID_MESSAGE_ID")
    if type(expected_actor) is not str or not ACTOR.fullmatch(expected_actor):
        _fail("INVALID_ACTOR")
    comments, items = _mailbox(pages, repository=repository, issue=issue)
    matches_found = [(cid, msg) for cid, msg in items if msg["message_id"] == message_id]
    if len(matches_found) != 1:
        _fail("SOURCE_MESSAGE_NOT_UNIQUE")
    cid, root = matches_found[0]
    actors = {comment["id"]: comment for comment in comments}
    actor = actors[cid]
    if expected_actor.casefold() == "kinoko34077":
        trusted = is_trusted_principal({
            "user": {"id": actor.get("actor_id"), "login": actor.get("actor_login")}
        })
    else:
        trusted = actor["actor_login"].casefold() == expected_actor.casefold()
    if not trusted:
        _fail("SOURCE_ACTOR_MISMATCH")
    if (root["kind"] != "REQUEST" or root["in_reply_to"] is not None
            or root["recipient"] != "claude-code"
            or root["scope"]["effect"] != "READ_ONLY"
            or root["intent"] not in ("ANALYZE", "REPORT")):
        _fail("SOURCE_NOT_SUPPORTED_REQUEST")
    return {
        "type": POINTER_VERSION,
        "owning_issue": f"https://github.com/{repository}/issues/{issue}",
        "message_id": message_id,
        "comment_id": cid,
    }


def route_request(
    *, repository: str, issue: int, message_id: str,
    expected_source_actor: str, expected_notice_actor: str,
    do_send: bool = False, offline_source_pages: str | None = None,
    offline_discovery_pages: str | None = None,
    discovery_issue: int = DISCOVERY_ISSUE,
) -> dict[str, Any]:
    # Live successor write is permitted ONLY to the concrete, approved #789
    # when explicitly selected by the caller. The default remains legacy #503.
    # Arbitrary IDs remain offline fixtures only; never become live targets.
    if type(discovery_issue) is not int or discovery_issue < 1:
        _fail("INVALID_DISCOVERY_INDEX")
    if discovery_issue not in (DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE):
        if do_send:
            _fail("SUCCESSOR_INDEX_NOT_APPROVED")
        if offline_source_pages is None or offline_discovery_pages is None:
            _fail("SUCCESSOR_REQUIRES_OFFLINE_FIXTURE")
    # Neither old nor new public discovery index can be an original source.
    if repository == DISCOVERY_REPOSITORY and issue in (
            DISCOVERY_ISSUE, APPROVED_SUCCESSOR_ISSUE, discovery_issue):
        _fail("DISCOVERY_LOOP")
    if do_send and (offline_source_pages is not None or offline_discovery_pages is not None):
        _fail("OFFLINE_POST_FORBIDDEN")
    if (offline_source_pages is None) != (offline_discovery_pages is None):
        _fail("INCOMPLETE_OFFLINE_FIXTURE")
    if do_send:
        verify_public_source(repository)
    source = (offline_source_pages if offline_source_pages is not None
              else fetch_gh_pages(repository, issue))
    pointer = verify_source_request(
        source, repository=repository, issue=issue,
        message_id=message_id, expected_actor=expected_source_actor)
    # No payload, task instruction or secrets are copied into the pointer.
    text = json.dumps(pointer, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    result = send_request(
        repository=DISCOVERY_REPOSITORY, issue=discovery_issue,
        recipient="claude-code", intent="REPORT",
        request_key=f"kaep.discovery.{message_id}", request_text=text,
        expect_existing_actor=expected_notice_actor, expected_head=None,
        do_send=do_send, offline_pages=offline_discovery_pages)
    return {
        "status": result["status"],
        "owning_issue": pointer["owning_issue"],
        "source_message_id": pointer["message_id"],
        "source_comment_id": pointer["comment_id"],
        "discovery_issue": f"{DISCOVERY_REPOSITORY}#{discovery_issue}",
        "discovery_comment_id": result["posted_comment_id"],
        "delivery_confirmed": False,
        "agent_woken": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--expect-source-actor", required=True)
    parser.add_argument("--expect-notice-actor", required=True)
    parser.add_argument("--offline-source-pages", type=Path)
    parser.add_argument("--offline-discovery-pages", type=Path)
    parser.add_argument("--discovery-issue", type=int, default=DISCOVERY_ISSUE,
                        help="Default legacy #503; opt-in live successor #789; other IDs offline only")
    parser.add_argument("--send", action="store_true",
                        help="Opt-in, ordinary GitHub Issue comment on the discovery mailbox")
    args = parser.parse_args(argv)
    try:
        result = route_request(
            repository=args.repository, issue=args.issue,
            message_id=args.message_id,
            expected_source_actor=args.expect_source_actor,
            expected_notice_actor=args.expect_notice_actor,
            do_send=args.send, discovery_issue=args.discovery_issue,
            offline_source_pages=args.offline_source_pages.read_text(encoding="utf-8")
            if args.offline_source_pages is not None else None,
            offline_discovery_pages=args.offline_discovery_pages.read_text(encoding="utf-8")
            if args.offline_discovery_pages is not None else None,
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (InvalidMessage, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, InvalidMessage) else "DISCOVERY_IO_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason_code": reason}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
