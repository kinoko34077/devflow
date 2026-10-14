"""Opt-in GPT liveness observation over KAEP v0.2; no Claim/agent authority.

Scheduled invocations inspect one explicitly enrolled owning Issue, then send at
most one KAEP PING per five-minute UTC bucket. They cannot awaken ChatGPT.
Existing KAEP ACK means delivery, not GPT/model liveness.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
import subprocess
import sys
from typing import Any

from tools.kaep_inbox_reader import fetch_gh_pages, parse_pages
from tools.kaep_mailbox_codec import InvalidMessage, read_mailbox, verify_reply_chain
from tools.kaep_request_sender import send_request

MARKER = "<!-- gpt-liveness:enrollment:v0.1 "
END = " -->"
SCHEMA = "gpt.liveness.v0.1"
ID = re.compile(r"[A-Za-z0-9_-]{8,72}\Z")
ACTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
MAX_ENROLLMENT = timedelta(hours=2)
PING_INTERVAL = 300
MAX_UNANSWERED = 3


def _fail(reason: str) -> None:
    raise InvalidMessage(reason)


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail("INVALID_UTC")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("INVALID_UTC")
    if result.utcoffset() != timedelta(0):
        _fail("INVALID_UTC")
    return result


def iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        _fail("INVALID_UTC")
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def strict_json(raw: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in items:
            if k in out:
                _fail("DUPLICATE_FIELD")
            out[k] = v
        return out
    try:
        obj = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, TypeError):
        _fail("INVALID_JSON")
    if type(obj) is not dict:
        _fail("INVALID_JSON")
    return obj


def enrollment(body: str, *, now: datetime) -> dict[str, Any] | None:
    if type(body) is not str:
        _fail("INVALID_ISSUE_BODY")
    if MARKER not in body:
        return None
    if body.count(MARKER) != 1:
        _fail("DUPLICATE_ENROLLMENT")
    raw = body.split(MARKER, 1)[1]
    if END not in raw or len(raw.split(END, 1)[0]) > 1500:
        _fail("INVALID_ENROLLMENT")
    data = strict_json(raw.split(END, 1)[0])
    fields = {"schema", "session_id", "turn_id", "started_at", "expires_at", "expected_actor", "enabled"}
    if set(data) not in (fields, fields | {"long_running_until"}):
        _fail("INVALID_ENROLLMENT_FIELDS")
    if data["schema"] != SCHEMA or type(data["enabled"]) is not bool:
        _fail("INVALID_ENROLLMENT")
    if not ID.fullmatch(str(data["session_id"])) or not ID.fullmatch(str(data["turn_id"])):
        _fail("INVALID_SESSION")
    if not isinstance(data["expected_actor"], str) or not ACTOR.fullmatch(data["expected_actor"]):
        _fail("INVALID_ACTOR")
    start, end = utc(data["started_at"]), utc(data["expires_at"])
    if end <= start or end - start > MAX_ENROLLMENT:
        _fail("INVALID_ENROLLMENT_DURATION")
    if start > now + timedelta(minutes=5):
        _fail("ENROLLMENT_IN_FUTURE")
    long_until = data.get("long_running_until")
    if long_until is not None:
        deadline = utc(long_until)
        if deadline <= start or deadline > end:
            _fail("INVALID_LONG_RUNNING_DEADLINE")
    if not data["enabled"] or now < start or now >= end:
        return None
    return data


def challenge(text: str) -> dict[str, Any]:
    data = strict_json(text)
    expected = {"schema", "session_id", "turn_id", "nonce", "issued_at", "expires_at", "purpose"}
    if set(data) != expected or data["schema"] != SCHEMA or data["purpose"] != "GPT_LIVENESS_PING":
        _fail("INVALID_CHALLENGE")
    if not ID.fullmatch(str(data["session_id"])) or not ID.fullmatch(str(data["turn_id"])):
        _fail("INVALID_SESSION")
    if not re.fullmatch(r"[0-9a-f]{32}", str(data["nonce"])):
        _fail("INVALID_NONCE")
    if utc(data["expires_at"]) <= utc(data["issued_at"]) or utc(data["expires_at"]) - utc(data["issued_at"]) > timedelta(minutes=20):
        _fail("INVALID_CHALLENGE_DURATION")
    return data


def answer(text: str, *, ping: dict[str, Any], now: datetime) -> dict[str, Any]:
    data = strict_json(text)
    fields = {"schema", "session_id", "turn_id", "nonce", "mode", "checkpoint", "expected_until"}
    if set(data) != fields or data["schema"] != SCHEMA:
        _fail("INVALID_ANSWER")
    for key in ("session_id", "turn_id", "nonce"):
        if data[key] != ping[key]:
            _fail("ANSWER_CHALLENGE_MISMATCH")
    if data["mode"] not in ("ACTIVE", "LONG_RUNNING", "IDLE", "FINISHED", "NEED_USER"):
        _fail("INVALID_MODE")
    if type(data["checkpoint"]) is not str or not 1 <= len(data["checkpoint"]) <= 256:
        _fail("INVALID_CHECKPOINT")
    if utc(ping["expires_at"]) < now or now < utc(ping["issued_at"]) - timedelta(seconds=30):
        _fail("EXPIRED_CHALLENGE")
    if data["mode"] == "LONG_RUNNING":
        if data["expected_until"] is None:
            _fail("LONG_RUNNING_MISSING_DEADLINE")
        deadline = utc(data["expected_until"])
        if deadline <= now or deadline > now + MAX_ENROLLMENT:
            _fail("INVALID_LONG_RUNNING_DEADLINE")
    elif data["expected_until"] is not None:
        _fail("UNEXPECTED_LONG_RUNNING_DEADLINE")
    return data


def extract(comments: list[dict[str, Any]], *, repo: str, issue: int) -> list[tuple[int, dict[str, Any], str]]:
    items = read_mailbox(comments, task_ref=f"{repo}#{issue}")
    verify_reply_chain([item for _, item in items])
    actor = {c["id"]: c["actor_login"] for c in comments}
    return [(cid, msg, actor[cid]) for cid, msg in items]


def plan(*, body: str, comments: list[dict[str, Any]], repo: str, issue: int,
         now: datetime, nonce: str) -> dict[str, Any]:
    en = enrollment(body, now=now)
    if en is None:
        return {"status": "NO_ACTIVE_ENROLLMENT"}
    if en.get("long_running_until") is not None and utc(en["long_running_until"]) > now:
        return {"status": "LONG_RUNNING", "expected_until": en["long_running_until"],
                "claim_authority": False}
    items = extract(comments, repo=repo, issue=issue)
    existing: list[dict[str, Any]] = []
    for _, msg, actor in items:
        if (msg["kind"] == "REQUEST" and msg["intent"] == "PING" and
                msg["recipient"] == "chatgpt" and actor.casefold() == "github-actions[bot]"):
            try:
                c = challenge(msg["payload"]["text"])
            except InvalidMessage:
                continue  # Another KAEP PING is not a liveness probe.
            if c["session_id"] == en["session_id"] and c["turn_id"] == en["turn_id"]:
                existing.append(msg)
    # An Answer is NOT automatically proof; evaluate only a challenge-bound
    # answer with exact session/turn/nonce/expiry, never an ACK or sidecar PONG.
    valid_answered: set[str] = set()
    latest_answer: tuple[int, dict[str, Any] | None] = (-1, None)
    times = {c["id"]: c.get("created_at") for c in comments}
    for root in existing:
        c = challenge(root["payload"]["text"])
        for cid, msg, actor in items:
            if (msg["kind"] != "ANSWER" or msg["in_reply_to"] != root["message_id"]
                    or msg["exchange_id"] != root["exchange_id"]
                    or actor.casefold() != en["expected_actor"].casefold()):
                continue
            try:
                observed_at = utc(times[cid])
                if observed_at > now + timedelta(seconds=30):
                    continue
                proven = answer(msg["payload"]["text"], ping=c, now=observed_at)
            except InvalidMessage:
                continue
            valid_answered.add(root["message_id"])
            if cid > latest_answer[0]:
                latest_answer = (cid, proven)
    if latest_answer[1] is not None:
        mode = latest_answer[1]["mode"]
        if mode in ("FINISHED", "IDLE", "NEED_USER"):
            return {"status": mode, "claim_authority": False}
        if mode == "LONG_RUNNING":
            until = latest_answer[1]["expected_until"]
            if until is not None and now < utc(until):
                return {"status": "LONG_RUNNING", "expected_until": until,
                        "claim_authority": False}
    pending = [r for r in existing if r["message_id"] not in valid_answered]
    slot = int(now.timestamp()) // PING_INTERVAL
    keyhash = hashlib.sha256(f"{repo}#{issue}:{en['session_id']}:{en['turn_id']}".encode()).hexdigest()[:20]
    key = f"kaep.liveness.{keyhash}.{slot}"
    if any(r["idempotency_key"] == key for r in existing):
        return {"status": "ALREADY_PINGED", "unanswered": len(pending)}
    if len(pending) >= MAX_UNANSWERED:
        return {"status": "SUSPECT_NO_REPLY", "unanswered": len(pending), "claim_authority": False}
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        _fail("INVALID_NONCE")
    payload = {
        "schema": SCHEMA, "session_id": en["session_id"],
        "turn_id": en["turn_id"], "nonce": nonce,
        "issued_at": iso(now),
        "expires_at": iso(min(now + timedelta(minutes=15), utc(en["expires_at"]))),
        "purpose": "GPT_LIVENESS_PING",
    }
    if utc(payload["expires_at"]) <= now:
        return {"status": "NO_ACTIVE_ENROLLMENT"}
    return {"status": "READY", "request_key": key,
            "request_text": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            "unanswered": len(pending)}


def fetch_issue(repo: str, issue: int) -> str:
    # Exact owning-Issue read only; no authentication/session inspection.
    proc = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github+json",
                           f"/repos/{repo}/issues/{issue}"], capture_output=True,
                          text=True, timeout=30, check=False)
    if proc.returncode != 0 or len(proc.stdout) > 2_000_000:
        _fail("ISSUE_READ_FAILED")
    data = strict_json(proc.stdout)
    if data.get("number") != issue or data.get("repository_url") != f"https://api.github.com/repos/{repo}" or data.get("state") != "open":
        _fail("ISSUE_IDENTITY_MISMATCH")
    if not isinstance(data.get("body"), str):
        _fail("MISSING_ISSUE_BODY")
    return data["body"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="kinoko34077/devflow")
    parser.add_argument("--issue", type=int, default=519)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args(argv)
    try:
        from tools.kaep_inbox_reader import REPOSITORY
        if not REPOSITORY.fullmatch(args.repository) or args.issue < 1:
            _fail("INVALID_TARGET")
        now = datetime.now(timezone.utc)
        body = fetch_issue(args.repository, args.issue)
        # Explicit opt-in must be present BEFORE full mailbox fetch or any POST.
        if enrollment(body, now=now) is None:
            print(json.dumps({"status": "NO_ACTIVE_ENROLLMENT"}))
            return 0
        pages_text = fetch_gh_pages(args.repository, args.issue)
        comments = parse_pages(pages_text, repository=args.repository, issue=args.issue)
        raw_pages = json.loads(pages_text)
        for parsed, original in zip(comments, (x for page in raw_pages for x in page)):
            if parsed["id"] != original["id"]:
                _fail("COMMENT_SEQUENCE_MISMATCH")
            parsed["created_at"] = original.get("created_at")
        result = plan(body=body, comments=comments, repo=args.repository, issue=args.issue,
                      now=now.replace(microsecond=0), nonce=secrets.token_hex(16))
        if args.send and result["status"] == "READY":
            # Re-read the owning Issue before effect, to catch a disabled or
            # replaced enrollment while paginated mailbox inspection was running.
            latest_body = fetch_issue(args.repository, args.issue)
            if latest_body != body or enrollment(latest_body, now=datetime.now(timezone.utc)) is None:
                _fail("ENROLLMENT_CHANGED_BEFORE_POST")
            # Existing KAEP sender owns idempotency + complete mailbox preflight
            # + GitHub actor readback; never introduce another transport.
            sent = send_request(repository=args.repository, issue=args.issue,
                                recipient="chatgpt", intent="PING",
                                request_key=result["request_key"], request_text=result["request_text"],
                                expect_existing_actor="github-actions[bot]", do_send=True)
            result = {"status": sent["status"], "posted_comment_id": sent["posted_comment_id"]}
        else:
            result.pop("request_text", None)  # redact nonce unless deliberately sending
        print(json.dumps(result, sort_keys=True))
        return 0
    except (InvalidMessage, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc) if isinstance(exc, InvalidMessage) else "IO_FAILURE"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
