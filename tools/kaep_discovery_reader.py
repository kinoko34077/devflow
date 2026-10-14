"""Read-only KAEP v0.2 discovery index validation (no task/Claim authority).

The indexed message is only a pointer. Before reporting it, re-read its owning
Issue and verify that the exact source request and original actor still match.
No raw task payload or untrusted pointer prose is promoted to commands.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Callable, Any

from tools.kaep_inbox_reader import InvalidMessage, fetch_gh_pages
from tools.kaep_mailbox_codec import unique_pairs, matches
from tools.kaep_reply_sender import ACTOR, _mailbox
from tools.kaep_route_notice import (
    DISCOVERY_REPOSITORY, DISCOVERY_ISSUE, POINTER_VERSION,
    verify_source_request,
)

SOURCE_URL = re.compile(
    r"https://github\.com/(kinoko34077/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)\Z")
POINTER_FIELDS = {"type", "owning_issue", "message_id", "comment_id"}
MAX_POINTERS = 20


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def parse_pointer(text: str) -> dict[str, Any] | None:
    # Other ordinary v0.2 REPORT requests on #503 are not routing pointers.
    if POINTER_VERSION not in text:
        return None
    try:
        obj = json.loads(text, object_pairs_hook=unique_pairs)
    except (ValueError, RecursionError, TypeError) as exc:
        raise InvalidMessage("INVALID_DISCOVERY_POINTER") from exc
    if type(obj) is not dict or set(obj) != POINTER_FIELDS or obj["type"] != POINTER_VERSION:
        _fail("INVALID_DISCOVERY_POINTER")
    if type(obj["owning_issue"]) is not str:
        _fail("INVALID_DISCOVERY_POINTER")
    target = SOURCE_URL.fullmatch(obj["owning_issue"])
    if target is None or not matches(r"msg_[A-Za-z0-9_-]{1,72}", obj["message_id"]):
        _fail("INVALID_DISCOVERY_POINTER")
    if type(obj["comment_id"]) is not int or obj["comment_id"] < 1:
        _fail("INVALID_DISCOVERY_POINTER")
    if target.group(1) == DISCOVERY_REPOSITORY and int(target.group(2)) == DISCOVERY_ISSUE:
        _fail("DISCOVERY_LOOP")
    return obj


def discover(
    index_pages: str, *, expected_notice_actor: str,
    expected_source_actor: str, fetch_source: Callable[[str, int], str],
    after_id: int = 0,
) -> list[dict[str, Any]]:
    if type(after_id) is not int or after_id < 0:
        _fail("INVALID_CURSOR")
    if (type(expected_notice_actor) is not str or not ACTOR.fullmatch(expected_notice_actor)
            or type(expected_source_actor) is not str or not ACTOR.fullmatch(expected_source_actor)):
        _fail("INVALID_ACTOR")
    comments, items = _mailbox(
        index_pages, repository=DISCOVERY_REPOSITORY, issue=DISCOVERY_ISSUE)
    actors = {comment["id"]: comment["actor_login"] for comment in comments}
    pointers: list[tuple[int, dict[str, Any]]] = []
    for cid, msg in items:
        if cid <= after_id or msg["recipient"] != "claude-code":
            continue
        if (msg["kind"] != "REQUEST" or msg["intent"] != "REPORT"
                or msg["in_reply_to"] is not None or msg["scope"]["effect"] != "READ_ONLY"):
            continue
        pointer = parse_pointer(msg["payload"]["text"])
        if pointer is None:
            continue
        if actors[cid].casefold() != expected_notice_actor.casefold():
            _fail("UNTRUSTED_DISCOVERY_ACTOR")
        pointers.append((cid, pointer))
        if len(pointers) > MAX_POINTERS:
            _fail("TOO_MANY_DISCOVERY_POINTERS")

    output = []
    source_pages_cache: dict[tuple[str, int], str] = {}
    for index_id, pointer in pointers:
        match = SOURCE_URL.fullmatch(pointer["owning_issue"])
        assert match is not None
        repo, issue = match.group(1), int(match.group(2))
        key = repo, issue
        if key not in source_pages_cache:
            source_pages_cache[key] = fetch_source(repo, issue)
        verified = verify_source_request(
            source_pages_cache[key], repository=repo, issue=issue,
            message_id=pointer["message_id"], expected_actor=expected_source_actor)
        if verified != pointer:
            _fail("DISCOVERY_SOURCE_MISMATCH")
        output.append({
            "index_comment_id": index_id,
            "owning_issue": pointer["owning_issue"],
            "source_comment_id": verified["comment_id"],
            "source_message_id": verified["message_id"],
            "status": "POINTER_SOURCE_VERIFIED_ONLY",
        })
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--expect-notice-actor", required=True)
    parser.add_argument("--expect-source-actor", required=True)
    args = parser.parse_args(argv)
    try:
        records = discover(
            fetch_gh_pages(DISCOVERY_REPOSITORY, DISCOVERY_ISSUE),
            expected_notice_actor=args.expect_notice_actor,
            expected_source_actor=args.expect_source_actor,
            fetch_source=fetch_gh_pages, after_id=args.after_id)
        print(json.dumps({"status": "READ_ONLY", "hints": records},
                         ensure_ascii=False, separators=(",", ":")))
        return 0
    except (InvalidMessage, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, InvalidMessage) else "DISCOVERY_IO_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason_code": reason}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
