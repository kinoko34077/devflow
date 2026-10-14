"""GPT-invoked KAEP inbox check and optional explicit model-mediated liveness reply.

This CLI NEVER automatically answers. The GPT worker must call --respond with
a fresh checkpoint/mode while running in an authorized active tool turn.
A GitHub actor login remains transport evidence, not cryptographic model ID.
"""
from __future__ import annotations

import argparse
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
    parser.add_argument("--mode", default="ACTIVE", choices=["ACTIVE", "LONG_RUNNING", "IDLE", "FINISHED", "NEED_USER"])
    parser.add_argument("--expected-until", default=None)
    parser.add_argument("--send", action="store_true", help="post only after explicit --respond; no auto answer")
    args = parser.parse_args(argv)
    try:
        if args.send and not args.respond:
            raise InvalidMessage("EXPLICIT_RESPOND_REQUIRED")
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
                 "expires_at": p["ping"]["expires_at"]} for p in pings],
                 "gpt_liveness_proven": False}, sort_keys=True))
            return 0
        if not args.checkpoint:
            raise InvalidMessage("CHECKPOINT_REQUIRED")
        if not pings:
            raise InvalidMessage("NO_VALID_PENDING_PING")
        # Most recent challenge, not a stale prior turn.
        chosen = pings[-1]
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
                          "claim_authority": False}, sort_keys=True))
        return 0
    except (InvalidMessage, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc) if isinstance(exc, InvalidMessage) else "IO_FAILURE"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
