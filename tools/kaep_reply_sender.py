"""KAEP M1 explicit reply transport for existing READ_ONLY Issue requests.

Requires caller-chosen existing GitHub comment actor and an explicitly invoked
--send flag for any write. No Claude launch, Actions, Claim or credentials changes.

Post is at-least-once; read-before-retry suppresses known duplicate replies.
GitHub Issues does not offer compare-and-swap create-comment, so simultaneous
senders are not exactly-once; receivers must deduplicate by message identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.github_issue_trust import is_trusted_principal
from tools.kaep_inbox_reader import (
    InvalidMessage, fetch_gh_pages, parse_pages, REPOSITORY, MAX_RESPONSE_BYTES,
)
from tools.kaep_mailbox_codec import (
    encode_comment, fingerprint, read_mailbox, isolate_cross_exchange_replies,
)

KINDS = {"ACK", "ANSWER", "BLOCKED"}
ROLES = {"claude-code", "chatgpt", "codex", "coordinator"}
ACTOR = re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9-]{0,38}|github-actions\[bot\])\Z")
FIXED_ACK = "Received the referenced KAEP message. This acknowledges receipt only; no task execution, provider run, or authorization is asserted."


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def _matching_actor(comment: dict[str, Any], expected_login: str) -> bool:
    """Require stable numeric identity for the trusted human actor.

    Other expected logins are read-only transport observations, never authority.
    """
    if comment["actor_login"].casefold() != expected_login.casefold():
        return False
    if expected_login.casefold() == "kinoko34077":
        return is_trusted_principal({"user": {
            "id": comment.get("actor_id"), "login": comment["actor_login"]
        }})
    return True


def _mailbox_snapshot(
    text: str, *, repository: str, issue: int,
) -> tuple[
    list[dict[str, Any]],
    list[tuple[int, dict[str, Any]]],
    list[tuple[int, dict[str, Any]]],
]:
    """Decode once; retain both eligible messages and all reserved identities.

    The complete mailbox is required for collision and replay checks.
    Quarantined exchanges are excluded only from actionable parent selection.
    """
    comments = parse_pages(text, repository=repository, issue=issue)
    all_items = read_mailbox(comments, task_ref=f"{repository}#{issue}")
    accepted, _quarantined = isolate_cross_exchange_replies(
        [item for _, item in all_items]
    )
    accepted_ids = {item["message_id"] for item in accepted}
    eligible = [
        (cid, item) for cid, item in all_items
        if item["message_id"] in accepted_ids
    ]
    return comments, eligible, all_items


def _mailbox(
    text: str, *, repository: str, issue: int,
) -> tuple[list[dict[str, Any]], list[tuple[int, dict[str, Any]]]]:
    """Existing two-result contract for source and discovery callers."""
    comments, eligible, _all_items = _mailbox_snapshot(
        text, repository=repository, issue=issue,
    )
    return comments, eligible


def _eligible_reply_parent(
    items: list[tuple[int, dict[str, Any]]],
    actors: dict[int, dict[str, Any]], *, parent_message_id: str,
    expect_actor: str, parent_recipient: str, kind: str,
) -> dict[str, Any]:
    """Select one trusted READ_ONLY parent before composing a reply.

    Only canonical, non-quarantined mailbox items may be a reply parent;
    this boundary never reserves reply identities or posts a comment.
    """
    matching = [(cid, msg) for cid, msg in items
                if msg["message_id"] == parent_message_id]
    if len(matching) != 1:
        _fail("PARENT_NOT_FOUND")
    cid, parent = matching[0]
    if not _matching_actor(actors[cid], expect_actor):
        _fail("PARENT_ACTOR_MISMATCH")
    if parent["recipient"] != parent_recipient or parent["kind"] not in ("REQUEST", "QUESTION"):
        _fail("INVALID_PARENT_INTENT")
    if parent["scope"]["effect"] != "READ_ONLY" or parent["intent"] not in ("PING", "ANALYZE", "TEST", "REPORT"):
        _fail("UNSUPPORTED_EFFECT")
    if kind == "ACK" and parent["kind"] != "REQUEST":
        _fail("INVALID_REPLY_KIND")
    return parent


def _reserved_reply_comment(
    reply: dict[str, Any], *,
    eligible_items: list[tuple[int, dict[str, Any]]],
    all_items: list[tuple[int, dict[str, Any]]],
    actors: dict[int, dict[str, Any]], expected_reply_actor: str,
) -> int | None:
    """Reserve identities from the complete mailbox, even quarantined replies.

    An eligible parent is not proof that a matching reply ID is available.
    Compare the first pre-existing matching ID/key and require its original
    actor; a matching transport login is not a verified model identity.
    """
    accepted_ids = {m["message_id"] for _, m in eligible_items}
    existing = [
        (c, m) for c, m in all_items
        if (m["message_id"] == reply["message_id"] or
            m["idempotency_key"] == reply["idempotency_key"])
    ]
    if existing:
        existing_id, existing_msg = existing[0]
        if existing_msg["message_id"] not in accepted_ids:
            _fail("REPLY_COLLISION")
        if fingerprint(existing_msg) != fingerprint(reply):
            _fail("REPLY_COLLISION")
        if not _matching_actor(actors[existing_id], expected_reply_actor):
            _fail("EXISTING_REPLY_ACTOR_MISMATCH")
        return existing_id
    return None


def make_reply(
    text: str, *, repository: str, issue: int, parent_message_id: str,
    kind: str, response_text: str, expect_actor: str,
    parent_recipient: str = "claude-code", reply_recipient: str = "chatgpt",
    reply_actor: str | None = None,
) -> tuple[dict[str, Any], int | None]:
    """Return expected reply and existing comment ID, if already sent.

    Does not authenticate the sender system; GitHub login is only transport
    metadata. Caller must separately confirm task authority and provenance.
    """
    if not REPOSITORY.fullmatch(repository) or type(issue) is not int or issue < 1:
        _fail("INVALID_TARGET")
    if kind not in KINDS or type(expect_actor) is not str or not ACTOR.fullmatch(expect_actor):
        _fail("INVALID_REPLY_OPTIONS")
    if type(response_text) is not str or not response_text.strip():
        _fail("INVALID_REPLY_TEXT")
    if (parent_recipient not in ROLES or reply_recipient not in ROLES
            or parent_recipient == reply_recipient):
        _fail("INVALID_REPLY_ROUTE")
    effective_reply_actor = expect_actor if reply_actor is None else reply_actor
    if type(effective_reply_actor) is not str or not ACTOR.fullmatch(effective_reply_actor):
        _fail("INVALID_REPLY_ACTOR")
    comments, items, all_items = _mailbox_snapshot(
        text, repository=repository, issue=issue,
    )
    actor_map = {item["id"]: item for item in comments}
    parent = _eligible_reply_parent(
        items, actor_map, parent_message_id=parent_message_id,
        expect_actor=expect_actor, parent_recipient=parent_recipient,
        kind=kind,
    )
    digest = hashlib.sha256(
        (parent["task_ref"] + "\n" + parent_message_id + "\n" + kind).encode("utf-8")
    ).hexdigest()[:32]
    reply = {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": parent["exchange_id"],
        "message_id": "msg_" + digest,
        "in_reply_to": parent_message_id,
        "task_ref": parent["task_ref"],
        "recipient": reply_recipient,
        "kind": kind,
        "intent": parent["intent"],
        "idempotency_key": "kaep.m1.reply." + digest,
        "scope": {
            "repository": repository,
            "expected_head": parent["scope"]["expected_head"],
            "effect": "READ_ONLY",
        },
        "payload": {"text": response_text},
        "evidence_refs": parent["evidence_refs"],
    }
    # Use the canonical codec for strict size, allowed-fields and wire validation.
    encode_comment(reply)
    existing_id = _reserved_reply_comment(
        reply, eligible_items=items, all_items=all_items,
        actors=actor_map, expected_reply_actor=effective_reply_actor,
    )
    return reply, existing_id


def post_comment(*, repository: str, issue: int, body: str) -> int:
    """Single ordinary Issue-comment POST, never an Action/Claim operation."""
    if not REPOSITORY.fullmatch(repository) or type(issue) is not int or issue < 1:
        _fail("INVALID_TARGET")
    data = json.dumps({"body": body}, ensure_ascii=False)
    try:
        resp = subprocess.run(
            ["gh", "api", "-X", "POST", "-H",
             "Accept: application/vnd.github+json",
             f"/repos/{repository}/issues/{issue}/comments", "--input", "-"],
            input=data, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidMessage("POST_AMBIGUOUS_READ_BEFORE_RETRY") from exc
    # Do not leak stderr or transport response body into failure messages.
    if resp.returncode != 0:
        _fail("POST_UNKNOWN_READ_BEFORE_RETRY")
    if len(resp.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
        _fail("POST_UNKNOWN_READ_BEFORE_RETRY")
    try:
        info = json.loads(resp.stdout)
    except (ValueError, TypeError) as exc:
        raise InvalidMessage("POST_UNKNOWN_READ_BEFORE_RETRY") from exc
    if type(info) is not dict or type(info.get("id")) is not int or info["id"] < 1:
        _fail("POST_UNKNOWN_READ_BEFORE_RETRY")
    return info["id"]


def post_and_verify(
    *, repository: str, issue: int, message: dict[str, Any],
    post_func, fetch_func, expected_post_actor: str,
) -> int:
    """Single shared post/readback boundary; callable injection is for offline tests.

    An Issue comment is only transport evidence, never provider identity,
    task authorization, runtime Claim or formal GitHub Review.
    """
    if type(expected_post_actor) is not str or not ACTOR.fullmatch(expected_post_actor):
        _fail("INVALID_POST_ACTOR")
    posted_id = post_func(repository=repository, issue=issue,
                          body=encode_comment(message))
    after = fetch_func(repository, issue)
    comments, observed = _mailbox(after, repository=repository, issue=issue)
    exact = [(cid, msg) for cid, msg in observed if cid == posted_id and
             msg["message_id"] == message["message_id"] and
             fingerprint(msg) == fingerprint(message)]
    if len(exact) != 1:
        _fail("READBACK_UNCONFIRMED_READ_BEFORE_RETRY")
    actors = {c["id"]: c for c in comments}
    if not _matching_actor(actors[posted_id], expected_post_actor):
        _fail("READBACK_ACTOR_MISMATCH")
    return posted_id


def send_reply(
    *, repository: str, issue: int, parent_message_id: str, kind: str,
    response_text: str, expect_actor: str, do_send: bool = False,
    offline_pages: str | None = None,
    parent_recipient: str = "claude-code", reply_recipient: str = "chatgpt",
    reply_actor: str | None = None,
) -> dict[str, Any]:
    if do_send and offline_pages is not None:
        _fail("OFFLINE_POST_FORBIDDEN")
    source = offline_pages if offline_pages is not None else fetch_gh_pages(repository, issue)
    reply, existing_id = make_reply(
        source, repository=repository, issue=issue,
        parent_message_id=parent_message_id, kind=kind,
        response_text=response_text, expect_actor=expect_actor,
        parent_recipient=parent_recipient, reply_recipient=reply_recipient,
        reply_actor=reply_actor,
    )
    result = {
        "status": "ALREADY_SENT" if existing_id is not None else
                  ("PREPARED" if not do_send else "POST_PENDING"),
        "message_id": reply["message_id"],
        "in_reply_to": reply["in_reply_to"],
        "kind": reply["kind"],
        "task_ref": reply["task_ref"],
        "posted_comment_id": existing_id,
        "genuine_claude_identity_verified": False,
        "effect": "ISSUE_COMMENT_ONLY" if do_send else "NONE",
    }
    if not do_send or existing_id is not None:
        return result
    # POST only after a fresh validated preflight. A concurrent writer may still
    # race, because GitHub has no conditional Issue-comment insertion.
    posted_id = post_and_verify(
        repository=repository, issue=issue, message=reply,
        post_func=post_comment, fetch_func=fetch_gh_pages,
        expected_post_actor=expect_actor if reply_actor is None else reply_actor,
    )
    result["status"] = "SENT_AND_READ_BACK"
    result["posted_comment_id"] = posted_id
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--parent-message-id", required=True)
    parser.add_argument("--kind", choices=sorted(KINDS), required=True)
    parser.add_argument("--expect-actor", required=True,
                        help="Existing parent GitHub login, not a model identity")
    parser.add_argument("--parent-recipient", choices=sorted(ROLES), default="claude-code",
                        help="The intended recipient of the original request")
    parser.add_argument("--reply-recipient", choices=sorted(ROLES), default="chatgpt",
                        help="Explicit recipient of the reply, not an authenticated sender")
    parser.add_argument("--expect-reply-actor",
                        help="Expected GitHub login for the reply post; defaults to --expect-actor. Not model identity.")
    parser.add_argument("--text-file", type=Path,
                        help="UTF-8 non-secret reply text; required for ANSWER/BLOCKED")
    parser.add_argument("--send", action="store_true",
                        help="Explicitly post one normal GitHub Issue comment")
    parser.add_argument("--offline-pages", type=Path,
                        help="Fixture for dry run only; never with --send")
    args = parser.parse_args(argv)
    try:
        if args.kind == "ACK" and args.text_file is None:
            answer = FIXED_ACK
        elif args.text_file is not None:
            answer = args.text_file.read_text(encoding="utf-8")
        else:
            _fail("REPLY_TEXT_REQUIRED")
        if args.send and args.offline_pages is not None:
            _fail("OFFLINE_POST_FORBIDDEN")
        offline = (args.offline_pages.read_text(encoding="utf-8")
                   if args.offline_pages else None)
        result = send_reply(
            repository=args.repository, issue=args.issue,
            parent_message_id=args.parent_message_id, kind=args.kind,
            response_text=answer, expect_actor=args.expect_actor,
            parent_recipient=args.parent_recipient, reply_recipient=args.reply_recipient,
            reply_actor=args.expect_reply_actor,
            do_send=args.send, offline_pages=offline,
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (InvalidMessage, OSError, UnicodeError) as exc:
        code = str(exc) if isinstance(exc, InvalidMessage) else "REPLY_IO_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason_code": code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
