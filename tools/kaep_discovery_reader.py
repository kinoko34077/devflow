"""Read-only, bounded KAEP v0.2 discovery index with source revalidation.

A malformed/untrusted *index comment* is quarantined, not promoted to task
authority and not allowed to starve following messages. Incomplete GitHub
pagination and unavailable or inconsistent owning-Issue mailboxes still fail
closed; this does not loosen the shared KAEP codec or Claim protections.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Callable, Any

from tools.kaep_inbox_reader import InvalidMessage, fetch_gh_pages, parse_pages
from tools.kaep_mailbox_codec import (
    MARKER, decode_comment, fingerprint, reject_constant, unique_pairs,
    matches,
)
from tools.kaep_reply_sender import ACTOR, _mailbox
from tools.kaep_route_notice import (
    DISCOVERY_REPOSITORY, DISCOVERY_ISSUE, POINTER_VERSION,
    verify_source_request,
)

SOURCE_URL = re.compile(
    r"https://github\.com/(kinoko34077/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)\Z")
POINTER_FIELDS = {"type", "owning_issue", "message_id", "comment_id"}
MAX_INDEX_BATCH = 20
REPLY_KINDS = {"ACK", "ANSWER", "BLOCKED"}


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def parse_pointer(text: str) -> dict[str, Any] | None:
    """Recognize only a structured object with the exact pointer type.

    Ordinary prose mentioning the pointer protocol is not a pointer, and may
    coexist with real discovery messages.
    """
    try:
        obj = json.loads(text, object_pairs_hook=unique_pairs,
                         parse_constant=reject_constant)
    except InvalidMessage:
        raise
    except (ValueError, RecursionError, TypeError) as exc:
        # Malformed JSON that attempts to be a typed pointer is rejected.
        # Ordinary prose, including an incidental version mention, is ignored.
        stripped = text.lstrip()
        if stripped.startswith("{") and '"type"' in stripped and POINTER_VERSION in stripped:
            raise InvalidMessage("INVALID_DISCOVERY_POINTER") from exc
        return None
    if type(obj) is not dict or obj.get("type") != POINTER_VERSION:
        return None
    if set(obj) != POINTER_FIELDS or type(obj["owning_issue"]) is not str:
        _fail("INVALID_DISCOVERY_POINTER")
    target = SOURCE_URL.fullmatch(obj["owning_issue"])
    if target is None or not matches(r"msg_[A-Za-z0-9_-]{1,72}", obj["message_id"]):
        _fail("INVALID_DISCOVERY_POINTER")
    if type(obj["comment_id"]) is not int or obj["comment_id"] < 1:
        _fail("INVALID_DISCOVERY_POINTER")
    if target.group(1) == DISCOVERY_REPOSITORY and int(target.group(2)) == DISCOVERY_ISSUE:
        _fail("DISCOVERY_LOOP")
    return obj


def _source_context(
    pages: str, *, repository: str, issue: int, message_id: str,
    expected_actor: str,
) -> dict[str, Any]:
    """Observe original immutable scope and correlated replies (not model ID)."""
    comments, items = _mailbox(pages, repository=repository, issue=issue)
    matches_found = [(cid, msg) for cid, msg in items if msg["message_id"] == message_id]
    if len(matches_found) != 1:
        _fail("SOURCE_MESSAGE_NOT_UNIQUE")
    _, root = matches_found[0]
    actors = {comment["id"]: comment["actor_login"] for comment in comments}
    replies = sorted({
        msg["kind"] for cid, msg in items
        if msg["in_reply_to"] == message_id
        and msg["exchange_id"] == root["exchange_id"]
        and msg["recipient"] == "chatgpt"
        and msg["kind"] in REPLY_KINDS
        and actors[cid].casefold() == expected_actor.casefold()
    })
    return {"expected_head": root["scope"]["expected_head"],
            "observed_reply_kinds": replies}


def discover_batch(
    index_pages: str, *, expected_notice_actor: str,
    expected_source_actor: str, fetch_source: Callable[[str, int], str],
    after_id: int = 0,
) -> dict[str, Any]:
    if type(after_id) is not int or after_id < 0:
        _fail("INVALID_CURSOR")
    if (type(expected_notice_actor) is not str or not ACTOR.fullmatch(expected_notice_actor)
            or type(expected_source_actor) is not str or not ACTOR.fullmatch(expected_source_actor)):
        _fail("INVALID_ACTOR")
    # Provider pagination/order/user metadata remains globally verified. Only
    # individual untrusted Issue comment content gets per-item isolation.
    comments = parse_pages(index_pages, repository=DISCOVERY_REPOSITORY,
                           issue=DISCOVERY_ISSUE)
    remaining = [item for item in comments if item["id"] > after_id]
    subset = remaining[:MAX_INDEX_BATCH]
    result: dict[str, Any] = {
        "status": "READ_ONLY",
        "hints": [],
        "rejected": [],
        "truncated": len(remaining) > len(subset),
        "next_after_id": subset[-1]["id"] if subset else after_id,
        "read_only": True,
        "peer_identity_verified": False,
    }
    source_cache: dict[tuple[str, int], str] = {}
    seen_msg: dict[str, str] = {}
    seen_keys: dict[str, str] = {}
    for comment in subset:
        cid = comment["id"]
        body = comment["body"]
        if not body.startswith(MARKER):
            continue
        if comment["actor_login"].casefold() != expected_notice_actor.casefold():
            result["rejected"].append({"index_comment_id": cid,
                                       "reason_code": "UNTRUSTED_DISCOVERY_ACTOR"})
            continue
        try:
            msg = decode_comment(body, task_ref=f"{DISCOVERY_REPOSITORY}#{DISCOVERY_ISSUE}")
            identity = fingerprint(msg)
            old_msg = seen_msg.get(msg["message_id"])
            old_key = seen_keys.get(msg["idempotency_key"])
            if (old_msg is not None and old_msg != identity
                    or old_key is not None and old_key != identity):
                _fail("CONFLICTING_INDEX_REPLAY")
            seen_msg[msg["message_id"]] = identity
            seen_keys[msg["idempotency_key"]] = identity
            if (msg["recipient"] != "claude-code" or msg["kind"] != "REQUEST"
                    or msg["intent"] != "REPORT" or msg["in_reply_to"] is not None
                    or msg["scope"]["effect"] != "READ_ONLY"):
                continue
            pointer = parse_pointer(msg["payload"]["text"])
            if pointer is None:
                continue
            match = SOURCE_URL.fullmatch(pointer["owning_issue"])
            assert match is not None
            repo, issue = match.group(1), int(match.group(2))
            key = (repo, issue)
            if key not in source_cache:
                # A failed provider/source fetch is not a malformed index item:
                # fail the entire scan so a cursor is NEVER advanced past it.
                source_cache[key] = fetch_source(repo, issue)
            verified = verify_source_request(
                source_cache[key], repository=repo, issue=issue,
                message_id=pointer["message_id"], expected_actor=expected_source_actor)
            if verified != pointer:
                _fail("DISCOVERY_SOURCE_MISMATCH")
            context = _source_context(
                source_cache[key], repository=repo, issue=issue,
                message_id=pointer["message_id"],
                expected_actor=expected_source_actor)
            result["hints"].append({
                "index_comment_id": cid,
                "owning_issue": pointer["owning_issue"],
                "source_comment_id": verified["comment_id"],
                "source_message_id": verified["message_id"],
                "expected_head": context["expected_head"],
                "observed_reply_kinds": context["observed_reply_kinds"],
                "status": "POINTER_SOURCE_VERIFIED_ONLY",
            })
        except InvalidMessage as exc:
            # Invalid index content/actor cannot starve later entries. Never
            # claim the invalid item is a verified task. Owning-Issue transport
            # corruption or unavailable reads are still globally fatal.
            if str(exc) in {
                "INCOMPLETE_PAGE", "MISSING_PAGES", "MAILBOX_TOO_LARGE",
                "INVALID_GITHUB_JSON", "INVALID_PAGES", "INVALID_PAGE",
                "GITHUB_READ_FAILED", "GITHUB_READ_UNAVAILABLE",
                "DUPLICATE_GITHUB_FIELD", "INVALID_COMMENT_ID",
                "COMMENT_ID_ORDER", "INVALID_ACTOR_LOGIN",
            }:
                raise
            result["rejected"].append({
                "index_comment_id": cid, "reason_code": str(exc)})
    return result


def discover(
    index_pages: str, *, expected_notice_actor: str,
    expected_source_actor: str, fetch_source: Callable[[str, int], str],
    after_id: int = 0,
) -> list[dict[str, Any]]:
    """Backward-compatible list projection; use discover_batch for cursor."""
    return discover_batch(
        index_pages, expected_notice_actor=expected_notice_actor,
        expected_source_actor=expected_source_actor,
        fetch_source=fetch_source, after_id=after_id)["hints"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--expect-notice-actor", required=True)
    parser.add_argument("--expect-source-actor", required=True)
    args = parser.parse_args(argv)
    try:
        result = discover_batch(
            fetch_gh_pages(DISCOVERY_REPOSITORY, DISCOVERY_ISSUE),
            expected_notice_actor=args.expect_notice_actor,
            expected_source_actor=args.expect_source_actor,
            fetch_source=fetch_gh_pages, after_id=args.after_id)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (InvalidMessage, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, InvalidMessage) else "DISCOVERY_IO_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason_code": reason}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
