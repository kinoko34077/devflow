"""Read-only per-chat GPT heartbeat identity, binding and evidence routing.

One GitHub Issue mailbox is exclusively bound to each chat. No Issue creation,
token, POST, workflow dispatch, scheduler, Claim or model identity attestation.
The caller must verify GitHub actors using trusted REST metadata.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
import secrets
from typing import Any

from tools.gpt_liveness_fleet_plan import parse_manifest, validate_snapshot
from tools.gpt_liveness_pilot import answer, challenge, enrollment, utc
from tools.kaep_mailbox_codec import InvalidMessage, validate as validate_message, verify_reply_chain

BINDING_SCHEMA = "gpt.liveness.chat-binding.v0.1"
MARKER = "<!-- gpt-liveness:chat-binding:v0.1 "
END = " -->"
CHAT_ID = re.compile(r"chat_[0-9a-f]{32}\Z")
MAILBOX = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+#[1-9][0-9]*\Z")
MAX_BODY_BYTES = 200_000


def fail(code: str) -> None:
    raise InvalidMessage(code)


def new_chat_id() -> str:
    """128-bit cryptographic random routing ID; NOT an auth token."""
    return "chat_" + secrets.token_hex(16)


def new_session_id() -> str:
    return "session_" + secrets.token_hex(16)


def new_turn_id() -> str:
    return "turn_" + secrets.token_hex(16)


def binding_marker(*, chat_id: str, mailbox_ref: str) -> str:
    if not isinstance(chat_id, str) or CHAT_ID.fullmatch(chat_id) is None:
        fail("INVALID_CHAT_ID")
    if not isinstance(mailbox_ref, str) or MAILBOX.fullmatch(mailbox_ref) is None:
        fail("INVALID_CHAT_MAILBOX")
    data = {"schema": BINDING_SCHEMA, "chat_id": chat_id, "mailbox_ref": mailbox_ref}
    return MARKER + json.dumps(data, separators=(",", ":"), sort_keys=True) + END


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in pairs:
        if key in out:
            fail("DUPLICATE_CHAT_BINDING_FIELD")
        out[key] = val
    return out


def parse_binding(body: str, *, mailbox_ref: str) -> dict[str, str]:
    if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_BODY_BYTES:
        fail("INVALID_CHAT_BINDING_BODY")
    if not isinstance(mailbox_ref, str) or MAILBOX.fullmatch(mailbox_ref) is None:
        fail("INVALID_CHAT_MAILBOX")
    if body.count(MARKER) != 1:
        fail("MISSING_OR_DUPLICATE_CHAT_BINDING")
    piece = body.split(MARKER, 1)[1]
    if END not in piece or len(piece.split(END, 1)[0]) > 300:
        fail("INVALID_CHAT_BINDING")
    try:
        raw = json.loads(piece.split(END, 1)[0], object_pairs_hook=_strict_pairs)
    except (ValueError, TypeError) as exc:
        if isinstance(exc, InvalidMessage):
            raise
        fail("INVALID_CHAT_BINDING_JSON")
    if (not isinstance(raw, dict)
            or set(raw) != {"schema", "chat_id", "mailbox_ref"}
            or raw.get("schema") != BINDING_SCHEMA
            or not isinstance(raw.get("chat_id"), str)
            or CHAT_ID.fullmatch(raw["chat_id"]) is None
            or raw.get("mailbox_ref") != mailbox_ref):
        fail("CHAT_BINDING_MISMATCH")
    return raw


def read_only_plan(*, manifest: str, snapshots: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Per-chat read-only F6 allowlist plus unique Issue-body binding.

    Registry membership alone is NOT an enrollment, permission to send, or
    evidence of currently running ChatGPT. No fallback to shared GitHub actor.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timedelta(0):
        fail("INVALID_CHAT_PLAN_TIME")
    targets = parse_manifest(manifest)
    if not isinstance(snapshots, dict) or set(snapshots) != set(targets):
        fail("CHAT_SNAPSHOT_SET_MISMATCH")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in targets:
        state, body = validate_snapshot(snapshots[target], target=target)
        binding = parse_binding(body, mailbox_ref=target)
        chat_id = binding["chat_id"]
        if chat_id in seen:
            fail("DUPLICATE_CHAT_ID")
        seen.add(chat_id)
        record: dict[str, Any] = {
            "chat_id": chat_id, "mailbox_ref": target, "status": "NO_ACTIVE_ENROLLMENT",
            "model_response_proven": False, "claim_authority": False,
        }
        if state == "closed":
            record["status"] = "ISSUE_CLOSED"
        else:
            registration = enrollment(body, now=now)
            if registration is not None:
                record.update({
                    "status": "ACTIVE_ENROLLMENT_REPORTED",
                    "session_id": registration["session_id"],
                    "turn_id": registration["turn_id"],
                    "expected_actor": registration["expected_actor"],
                    "expires_at": registration["expires_at"],
                })
        entries.append(record)
    return {
        "schema": "gpt.liveness.chat-routing.v0.1", "entries": entries,
        "writable": False, "gpt_currently_alive_proven": False,
        "claim_authority": False,
    }


def validate_heartbeat_pair(
    *, plan: dict[str, Any], chat_id: str, mailbox_ref: str,
    ping_message: dict[str, Any], answer_message: dict[str, Any],
    ping_actor: str, answer_actor: str,
    ping_created_at: str, answer_created_at: str,
) -> dict[str, Any]:
    """Match one chat/issue/session/turn and a timely, exact KAEP reply pair.

    Both actors and timestamps MUST come from trusted GitHub REST responses.
    A passing result is evidence of tool-mediated ANSWER, not ChatGPT platform
    conversation identity, cryptographic model identity or current liveness.
    """
    if not isinstance(plan, dict) or plan.get("schema") != "gpt.liveness.chat-routing.v0.1":
        fail("INVALID_CHAT_ROUTING_PLAN")
    entries = plan.get("entries")
    if not isinstance(entries, list):
        fail("INVALID_CHAT_ROUTING_PLAN")
    matches = [
        e for e in entries if isinstance(e, dict)
        and e.get("chat_id") == chat_id and e.get("mailbox_ref") == mailbox_ref
    ]
    if len(matches) != 1:
        fail("CHAT_ROUTE_NOT_FOUND")
    record = matches[0]
    if record.get("status") != "ACTIVE_ENROLLMENT_REPORTED":
        fail("CHAT_ENROLLMENT_INACTIVE")
    if (not isinstance(ping_actor, str) or ping_actor.casefold() != "github-actions[bot]"
            or not isinstance(answer_actor, str)
            or answer_actor.casefold() != record["expected_actor"].casefold()):
        fail("CHAT_HEARTBEAT_ACTOR_MISMATCH")
    validate_message(ping_message, task_ref=mailbox_ref)
    validate_message(answer_message, task_ref=mailbox_ref)
    verify_reply_chain([ping_message, answer_message])
    if (ping_message["kind"] != "REQUEST" or ping_message["intent"] != "PING"
            or ping_message["recipient"] != "chatgpt"
            or ping_message["in_reply_to"] is not None
            or ping_message["scope"]["effect"] != "READ_ONLY"
            or answer_message["kind"] != "ANSWER" or answer_message["intent"] != "PING"
            or answer_message["in_reply_to"] != ping_message["message_id"]
            or answer_message["exchange_id"] != ping_message["exchange_id"]):
        fail("CHAT_HEARTBEAT_CHAIN_MISMATCH")
    ping = challenge(ping_message["payload"]["text"])
    if (ping["session_id"] != record["session_id"]
            or ping["turn_id"] != record["turn_id"]):
        fail("CHAT_SESSION_TURN_MISMATCH")
    issued, posted, replied = utc(ping["issued_at"]), utc(ping_created_at), utc(answer_created_at)
    if (posted < issued - timedelta(seconds=30) or
            replied < posted or replied > utc(ping["expires_at"])):
        fail("CHAT_HEARTBEAT_TIME_MISMATCH")
    response = answer(answer_message["payload"]["text"], ping=ping, now=replied)
    return {
        "chat_id": chat_id, "mailbox_ref": mailbox_ref,
        "session_id": ping["session_id"], "turn_id": ping["turn_id"],
        "exchange_id": ping_message["exchange_id"], "nonce": ping["nonce"],
        "mode": response["mode"], "status": "MODEL_TOOL_RESPONSE_OBSERVED",
        "observed_at": answer_created_at, "model_identity_attested": False,
        "current_liveness_proven": False, "claim_authority": False,
    }
