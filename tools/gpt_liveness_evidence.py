"""Produce read-only, non-authoritative GPT-liveness observation from KAEP GitHub mailbox.

Wire/nonce/reply-chain validation reuses devflow's existing KAEP v0.2 codec.
The resulting JSON is *producer-reported evidence*, not model identity, Claim,
lease or a reason to launch/interrupt interactive ChatGPT.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys
from typing import Any

from tools.kaep_inbox_reader import fetch_gh_pages, parse_pages, InvalidMessage, REPOSITORY
from tools.gpt_liveness_pilot import challenge, answer, extract, utc, iso

ID = re.compile(r"[A-Za-z0-9_-]{8,72}\Z")
ACTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
BOT = "github-actions[bot]"


def _fail(reason: str) -> None:
    raise InvalidMessage(reason)


def validated_comments(raw: str, *, repository: str, issue: int) -> list[dict[str, Any]]:
    """Require canonical complete KAEP pages and GitHub comment identity/times."""
    result = parse_pages(raw, repository=repository, issue=issue)
    try:
        pages = json.loads(raw)
        flattened = [comment for page in pages for comment in page]
    except (ValueError, TypeError) as exc:
        raise InvalidMessage("INVALID_GITHUB_JSON") from exc
    if len(result) != len(flattened):
        _fail("COMMENT_SEQUENCE_MISMATCH")
    for cleaned, original in zip(result, flattened):
        cid = cleaned["id"]
        if original.get("id") != cid or original.get("issue_url") != (
                f"https://api.github.com/repos/{repository}/issues/{issue}"):
            _fail("COMMENT_ISSUE_IDENTITY_MISMATCH")
        if original.get("html_url") != (
                f"https://github.com/{repository}/issues/{issue}#issuecomment-{cid}"):
            _fail("COMMENT_URL_MISMATCH")
        if original.get("user", {}).get("login") != cleaned["actor_login"]:
            _fail("COMMENT_ACTOR_MISMATCH")
        cleaned["created_at"] = iso(utc(original.get("created_at")))
    return result


def project_from_pages(*, raw: str, repository: str, issue: int,
                       session_id: str, turn_id: str,
                       expected_reply_actor: str) -> dict[str, Any]:
    if not REPOSITORY.fullmatch(repository) or type(issue) is not int or issue < 1:
        _fail("INVALID_TARGET")
    if any(type(v) is not str or not ID.fullmatch(v) for v in (session_id, turn_id)):
        _fail("INVALID_SESSION")
    if type(expected_reply_actor) is not str or not ACTOR.fullmatch(expected_reply_actor):
        _fail("INVALID_REPLY_ACTOR")
    comments = validated_comments(raw, repository=repository, issue=issue)
    items = extract(comments, repo=repository, issue=issue)
    stamps = {c["id"]: utc(c["created_at"]) for c in comments}
    sources = []
    for cid, msg, actor in items:
        if msg["kind"] != "REQUEST" or msg["intent"] != "PING" or msg["recipient"] != "chatgpt":
            continue
        if actor.casefold() != BOT.casefold():
            continue
        try:
            ping = challenge(msg["payload"]["text"])
        except InvalidMessage:
            continue  # Ordinary KAEP PING is not GPT liveness evidence.
        if ping["session_id"] != session_id or ping["turn_id"] != turn_id:
            continue
        issued, expires = utc(ping["issued_at"]), utc(ping["expires_at"])
        if stamps[cid] < issued - timedelta(seconds=30) or stamps[cid] > expires:
            continue
        sources.append((cid, msg, ping))
    if not sources:
        _fail("NO_VALID_LIVENESS_PING")
    # Newest challenge for exactly this scoped session/turn, not a prior turn.
    source_cid, source, ping = max(sources, key=lambda x: x[0])
    event = "NO_RESPONSE"
    observed_id = source_cid
    observed_at = stamps[source_cid]
    actor = BOT
    valid_until = utc(ping["expires_at"])
    candidate = []
    for cid, msg, reply_actor in items:
        if (msg["kind"] != "ANSWER" or msg["intent"] != "PING"
                or msg["in_reply_to"] != source["message_id"]
                or msg["exchange_id"] != source["exchange_id"]
                or reply_actor.casefold() != expected_reply_actor.casefold()):
            continue
        try:
            reply_time = stamps[cid]
            if reply_time < stamps[source_cid]:
                continue
            parsed = answer(msg["payload"]["text"], ping=ping, now=reply_time)
        except InvalidMessage:
            continue
        candidate.append((cid, reply_actor, parsed))
    if candidate:
        observed_id, actor, parsed = max(candidate, key=lambda x: x[0])
        observed_at = stamps[observed_id]
        if parsed["mode"] == "LONG_RUNNING":
            event = "LONG_RUNNING_DECLARED"
            valid_until = utc(parsed["expected_until"])
        else:
            event = "MODEL_TOOL_RESPONSE_OBSERVED"
    # An accepted challenge is finite <= 20m; long-run declaration is <= 2h.
    if valid_until <= observed_at or valid_until - observed_at > timedelta(hours=2):
        _fail("INVALID_OBSERVATION_TTL")
    return {
        "schema": "gpt-liveness-observation.v1",
        "source": "devflow/kaep-v0.2",
        "mailbox_ref": f"{repository}#{issue}",
        "task_ref": f"{repository}#{issue}",
        "session_id": session_id,
        "turn_id": turn_id,
        "event": event,
        "observed_at": iso(observed_at),
        "valid_until": iso(valid_until),
        "evidence_url": f"https://github.com/{repository}/issues/{issue}#issuecomment-{observed_id}",
        "reported_actor": actor,
        "producer_validation": "UPSTREAM_REPORTED",
        "claim_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="kinoko34077/devflow")
    parser.add_argument("--issue", type=int, default=519)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--expected-reply-actor", required=True)
    parser.add_argument("--offline-pages", type=Path, help="read-only fixture, no POST")
    args = parser.parse_args(argv)
    try:
        raw = (args.offline_pages.read_text(encoding="utf-8")
               if args.offline_pages is not None
               else fetch_gh_pages(args.repository, args.issue))
        report = project_from_pages(
            raw=raw, repository=args.repository, issue=args.issue,
            session_id=args.session_id, turn_id=args.turn_id,
            expected_reply_actor=args.expected_reply_actor,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (InvalidMessage, OSError, UnicodeError) as exc:
        code = str(exc) if isinstance(exc, InvalidMessage) else "READ_ONLY_IO_FAILURE"
        print(json.dumps({"status": "BLOCKED", "reason_code": code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
