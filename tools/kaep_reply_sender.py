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

from tools.kaep_inbox_reader import (
    InvalidMessage, fetch_gh_pages, parse_pages, REPOSITORY, MAX_RESPONSE_BYTES,
)
from tools.kaep_mailbox_codec import (
    encode_comment, fingerprint, read_mailbox, verify_reply_chain,
)

KINDS = {"ACK", "ANSWER", "BLOCKED"}
ACTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
FIXED_ACK = "Received the referenced KAEP message. This acknowledges receipt only; no task execution, provider run, or authorization is asserted."


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def _mailbox(text: str, *, repository: str, issue: int) -> tuple[list[dict[str, Any]], list[tuple[int, dict[str, Any]]]]:
    comments = parse_pages(text, repository=repository, issue=issue)
    task_ref = f"{repository}#{issue}"
    items = read_mailbox(comments, task_ref=task_ref)
    verify_reply_chain([item for _, item in items])
    return comments, items


def make_reply(
    text: str, *, repository: str, issue: int, parent_message_id: str,
    kind: str, response_text: str, expect_actor: str,
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
    comments, items = _mailbox(text, repository=repository, issue=issue)
    actor_map = {item["id"]: item["actor_login"] for item in comments}
    matching = [(cid, msg) for cid, msg in items if msg["message_id"] == parent_message_id]
    if len(matching) != 1:
        _fail("PARENT_NOT_FOUND")
    cid, parent = matching[0]
    if actor_map[cid].casefold() != expect_actor.casefold():
        _fail("PARENT_ACTOR_MISMATCH")
    if parent["recipient"] != "claude-code" or parent["kind"] not in ("REQUEST", "QUESTION"):
        _fail("INVALID_PARENT_INTENT")
    if parent["scope"]["effect"] != "READ_ONLY" or parent["intent"] not in ("PING", "ANALYZE", "TEST", "REPORT"):
        _fail("UNSUPPORTED_EFFECT")
    if kind == "ACK" and parent["kind"] != "REQUEST":
        _fail("INVALID_REPLY_KIND")
    digest = hashlib.sha256(
        (parent["task_ref"] + "\n" + parent_message_id + "\n" + kind).encode("utf-8")
    ).hexdigest()[:32]
    reply = {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": parent["exchange_id"],
        "message_id": "msg_" + digest,
        "in_reply_to": parent_message_id,
        "task_ref": parent["task_ref"],
        "recipient": "chatgpt",
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
    existing = [(c, m) for c, m in items if m["message_id"] == reply["message_id"]]
    if existing:
        existing_id, existing_msg = existing[0]
        if fingerprint(existing_msg) != fingerprint(reply):
            _fail("REPLY_COLLISION")
        # Identical reply is already durable. Do not POST again.
        return reply, existing_id
    return reply, None


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


def send_reply(
    *, repository: str, issue: int, parent_message_id: str, kind: str,
    response_text: str, expect_actor: str, do_send: bool = False,
    offline_pages: str | None = None,
) -> dict[str, Any]:
    if do_send and offline_pages is not None:
        _fail("OFFLINE_POST_FORBIDDEN")
    source = offline_pages if offline_pages is not None else fetch_gh_pages(repository, issue)
    reply, existing_id = make_reply(
        source, repository=repository, issue=issue,
        parent_message_id=parent_message_id, kind=kind,
        response_text=response_text, expect_actor=expect_actor,
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
    posted_id = post_comment(repository=repository, issue=issue, body=encode_comment(reply))
    after = fetch_gh_pages(repository, issue)
    _, observed = _mailbox(after, repository=repository, issue=issue)
    exact = [(cid, msg) for cid, msg in observed if cid == posted_id and
             msg["message_id"] == reply["message_id"] and
             fingerprint(msg) == fingerprint(reply)]
    if len(exact) != 1:
        _fail("READBACK_UNCONFIRMED_READ_BEFORE_RETRY")
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
