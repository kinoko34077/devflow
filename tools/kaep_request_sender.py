"""KAEP v0.2 read-only REQUEST composition and opt-in GitHub Issue transport.

This is an inter-agent message transport only. A REQUEST cannot grant runtime
Claim, work authorization, PR Review or Human approval. No auto agent wake.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from tools.kaep_inbox_reader import fetch_gh_pages, InvalidMessage, REPOSITORY
from tools.kaep_reply_sender import _mailbox, post_comment, ACTOR
from tools.kaep_mailbox_codec import encode_comment, fingerprint

INTENTS = {"PING", "ANALYZE", "TEST", "REPORT"}
RECIPIENTS = {"claude-code", "chatgpt", "codex"}


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def make_request(
    text: str, *, repository: str, issue: int, recipient: str,
    intent: str, request_key: str, request_text: str,
    expect_existing_actor: str,
) -> tuple[dict[str, Any], int | None]:
    if not REPOSITORY.fullmatch(repository) or type(issue) is not int or issue < 1:
        _fail("INVALID_TARGET")
    if recipient not in RECIPIENTS or intent not in INTENTS:
        _fail("UNSUPPORTED_REQUEST")
    if type(request_text) is not str or not request_text.strip():
        _fail("INVALID_REQUEST_TEXT")
    if type(expect_existing_actor) is not str or not ACTOR.fullmatch(expect_existing_actor):
        _fail("INVALID_ACTOR")
    # Codec owns exact syntax validation for request_key and bounded content.
    digest = hashlib.sha256((f"{repository}#{issue}\n" + request_key).encode("utf-8")).hexdigest()[:32] \
             if type(request_key) is str else ""
    task_ref = f"{repository}#{issue}"
    req = {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": "ex_" + digest,
        "message_id": "msg_" + digest,
        "in_reply_to": None,
        "task_ref": task_ref,
        "recipient": recipient,
        "kind": "REQUEST",
        "intent": intent,
        "idempotency_key": request_key,
        "scope": {"repository": repository, "expected_head": None,
                  "effect": "READ_ONLY"},
        "payload": {"text": request_text},
        "evidence_refs": [],
    }
    encode_comment(req)
    comments, items = _mailbox(text, repository=repository, issue=issue)
    actors = {c["id"]: c["actor_login"] for c in comments}
    matching = [
        (cid, msg) for cid, msg in items
        if msg["idempotency_key"] == request_key or msg["message_id"] == req["message_id"]
    ]
    if matching:
        cid, existing = matching[0]
        if fingerprint(existing) != fingerprint(req):
            _fail("REQUEST_KEY_COLLISION")
        if actors[cid].casefold() != expect_existing_actor.casefold():
            _fail("EXISTING_ACTOR_MISMATCH")
        return req, cid
    return req, None


def send_request(
    *, repository: str, issue: int, recipient: str, intent: str,
    request_key: str, request_text: str, expect_existing_actor: str,
    do_send: bool = False, offline_pages: str | None = None,
) -> dict[str, Any]:
    if do_send and offline_pages is not None:
        _fail("OFFLINE_POST_FORBIDDEN")
    source = offline_pages if offline_pages is not None else fetch_gh_pages(repository, issue)
    req, existing_id = make_request(
        source, repository=repository, issue=issue, recipient=recipient,
        intent=intent, request_key=request_key, request_text=request_text,
        expect_existing_actor=expect_existing_actor,
    )
    output = {
        "status": "ALREADY_SENT" if existing_id is not None else
                  ("PREPARED" if not do_send else "POST_PENDING"),
        "task_ref": req["task_ref"],
        "message_id": req["message_id"],
        "exchange_id": req["exchange_id"],
        "recipient": recipient,
        "intent": intent,
        "posted_comment_id": existing_id,
        "read_only_request": True,
        "agent_woken": False,
        "worker_identity_verified": False,
    }
    if existing_id is not None or not do_send:
        return output
    cid = post_comment(repository=repository, issue=issue, body=encode_comment(req))
    after = fetch_gh_pages(repository, issue)
    _, msgs = _mailbox(after, repository=repository, issue=issue)
    actual = [
        c for c, msg in msgs
        if c == cid and msg["message_id"] == req["message_id"]
        and fingerprint(msg) == fingerprint(req)
    ]
    if len(actual) != 1:
        _fail("READBACK_UNCONFIRMED_READ_BEFORE_RETRY")
    output["status"] = "SENT_AND_READ_BACK"
    output["posted_comment_id"] = cid
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--recipient", required=True, choices=sorted(RECIPIENTS))
    parser.add_argument("--intent", required=True, choices=sorted(INTENTS))
    parser.add_argument("--request-key", required=True,
                        help="Stable unique key; reused keys must keep exactly the same message")
    parser.add_argument("--text-file", type=Path, required=True,
                        help="Non-secret UTF-8 text to send; never put secrets in Issue comments")
    parser.add_argument("--expect-existing-actor", required=True,
                        help="Expected GitHub login for any already-posted request; not model identity")
    parser.add_argument("--offline-pages", type=Path,
                        help="Fixture for dry-run only")
    parser.add_argument("--send", action="store_true",
                        help="Explicitly post one ordinary GitHub Issue comment")
    args = parser.parse_args(argv)
    try:
        if args.offline_pages is not None and args.send:
            _fail("OFFLINE_POST_FORBIDDEN")
        result = send_request(
            repository=args.repository, issue=args.issue, recipient=args.recipient,
            intent=args.intent, request_key=args.request_key,
            request_text=args.text_file.read_text(encoding="utf-8"),
            expect_existing_actor=args.expect_existing_actor,
            do_send=args.send,
            offline_pages=args.offline_pages.read_text(encoding="utf-8")
            if args.offline_pages is not None else None,
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (InvalidMessage, OSError, UnicodeError) as exc:
        code = str(exc) if isinstance(exc, InvalidMessage) else "REQUEST_IO_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason_code": code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
