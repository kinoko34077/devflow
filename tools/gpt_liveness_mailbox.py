"""GPT-invoked KAEP inbox check and optional explicit model-mediated liveness reply.

This CLI NEVER automatically answers. The GPT worker must call --respond with
a fresh checkpoint/mode while running in an authorized active tool turn.
A GitHub actor login remains transport evidence, not cryptographic model ID.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
import json
import sys

from tools.kaep_inbox_reader import fetch_gh_pages, parse_pages
from tools.kaep_reply_sender import send_reply
from tools.kaep_mailbox_codec import InvalidMessage
from tools.gpt_liveness_pilot import (
    SCHEMA, answer, challenge, enrollment, extract, fetch_issue, iso, strict_json, utc,
)


def pending_pings(*, body: str, comments: list[dict], repo: str, issue: int,
                  now: datetime) -> list[dict]:
    active = enrollment(body, now=now)
    if active is None:
        return []
    entries = extract(comments, repo=repo, issue=issue)
    roots = []
    for cid, msg, actor in entries:
        if msg["kind"] != "REQUEST" or msg["intent"] != "PING" or msg["recipient"] != "chatgpt":
            continue
        if actor.casefold() != "github-actions[bot]":
            continue
        try:
            data = challenge(msg["payload"]["text"])
        except InvalidMessage:
            continue
        if data["session_id"] != active["session_id"] or data["turn_id"] != active["turn_id"]:
            continue
        if now >= utc(data["expires_at"]):
            continue
        roots.append({"comment_id": cid, "parent_message_id": msg["message_id"],
                      "exchange_id": msg["exchange_id"], "ping": data})
    result = []
    timestamps = {c["id"]: c.get("created_at") for c in comments}
    for root in roots:
        valid_reply = False
        for cid, msg, actor in entries:
            if (msg["kind"] != "ANSWER" or msg["in_reply_to"] != root["parent_message_id"]
                    or msg["exchange_id"] != root["exchange_id"]
                    or actor.casefold() != active["expected_actor"].casefold()):
                continue
            try:
                observed_at = utc(timestamps[cid])
                answer(msg["payload"]["text"], ping=root["ping"], now=observed_at)
                valid_reply = True
                break
            except InvalidMessage:
                continue
        if not valid_reply:
            result.append(root)
    return result


def create_answer(*, ping: dict, mode: str, checkpoint: str,
                  expected_until: str | None, now: datetime) -> str:
    message = {
        "schema": SCHEMA,
        "session_id": ping["session_id"], "turn_id": ping["turn_id"],
        "nonce": ping["nonce"], "mode": mode, "checkpoint": checkpoint,
        "expected_until": expected_until,
    }
    text = json.dumps(message, separators=(",", ":"), sort_keys=True)
    answer(text, ping=ping, now=now)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="kinoko34077/devflow")
    parser.add_argument("--issue", type=int, default=519)
    parser.add_argument("--respond", action="store_true", help="explicit GPT decision to compose an ANSWER")
    parser.add_argument("--checkpoint", default=None, help="model-supplied non-secret current checkpoint")
    parser.add_argument("--reply-to-comment-id", type=int, default=None,
                        help="exact GitHub comment_id the model inspected in read-only phase")
    parser.add_argument("--reply-to-nonce", default=None,
                        help="exact 32-hex nonce from selected inspected PING")
    parser.add_argument("--mode", default="ACTIVE", choices=["ACTIVE", "LONG_RUNNING", "IDLE", "FINISHED", "NEED_USER"])
    parser.add_argument("--expected-until", default=None)
    parser.add_argument("--send", action="store_true", help="post only after explicit --respond; no auto answer")
    args = parser.parse_args(argv)
    try:
        if args.send and not args.respond:
            raise InvalidMessage("EXPLICIT_RESPOND_REQUIRED")
        if not args.respond and (
            args.reply_to_comment_id is not None or args.reply_to_nonce is not None):
            raise InvalidMessage("RESPONSE_SELECTION_WITHOUT_MODEL_DECISION")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        body = fetch_issue(args.repository, args.issue)
        source = fetch_gh_pages(args.repository, args.issue)
        comments = parse_pages(source, repository=args.repository, issue=args.issue)
        raw = json.loads(source)
        for item, original in zip(comments, (c for page in raw for c in page)):
            if item["id"] != original["id"]:
                raise InvalidMessage("COMMENT_SEQUENCE_MISMATCH")
            item["created_at"] = original.get("created_at")
        pings = pending_pings(body=body, comments=comments, repo=args.repository,
                              issue=args.issue, now=now)
        if not args.respond:
            print(json.dumps({"status": "MAILBOX_CHECKED", "unanswered_pings": [
                {"comment_id": p["comment_id"], "parent_message_id": p["parent_message_id"],
                 "nonce": p["ping"]["nonce"],
                 "session_id": p["ping"]["session_id"],
                 "turn_id": p["ping"]["turn_id"],
                 "expires_at": p["ping"]["expires_at"]} for p in pings],
                 "gpt_liveness_proven": False,
                 "requires_explicit_model_challenge_selection": True,
                 "automatic_answer_supported": False}, sort_keys=True))
            return 0
        if not args.checkpoint:
            raise InvalidMessage("CHECKPOINT_REQUIRED")
        if (type(args.reply_to_comment_id) is not int
                or args.reply_to_comment_id <= 0
                or type(args.reply_to_nonce) is not str
                or re.fullmatch(r"[0-9a-f]{32}", args.reply_to_nonce) is None):
            raise InvalidMessage("EXPLICIT_PING_SELECTION_REQUIRED")
        if not pings:
            raise InvalidMessage("NO_VALID_PENDING_PING")
        # Require the model to select the newest inspected challenge explicitly.
        # Re-reading the canonical GitHub Issue above catches stale selection.
        chosen = max(pings, key=lambda p: p["comment_id"])
        if (chosen["comment_id"] != args.reply_to_comment_id
                or chosen["ping"]["nonce"] != args.reply_to_nonce):
            raise InvalidMessage("PING_SELECTION_STALE_OR_MISMATCHED")
        response = create_answer(ping=chosen["ping"], mode=args.mode,
                                 checkpoint=args.checkpoint,
                                 expected_until=args.expected_until, now=now)
        outcome = send_reply(
            repository=args.repository, issue=args.issue,
            parent_message_id=chosen["parent_message_id"],
            kind="ANSWER", response_text=response,
            expect_actor="github-actions[bot]",
            parent_recipient="chatgpt", reply_recipient="coordinator",
            reply_actor="kinoko34077", do_send=args.send,
        )
        print(json.dumps({"status": outcome["status"],
                          "parent_message_id": chosen["parent_message_id"],
                          "posted_comment_id": outcome["posted_comment_id"],
                          "model_identity_cryptographically_verified": False,
                          "model_selection_observed_in_tool_arguments": True,
                          "autonomous_gpt_wake_proven": False,
                          "claim_authority": False}, sort_keys=True))
        return 0
    except (InvalidMessage, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc) if isinstance(exc, InvalidMessage) else "IO_FAILURE"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
