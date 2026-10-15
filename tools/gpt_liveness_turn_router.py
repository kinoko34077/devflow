"""Turn-scoped read-only GPT heartbeat routing across explicitly allowed mailboxes.

An active F4 turn_id is the participant ID: NO per-chat registry or persistent
conversation UUID is required. Each concurrent turn occupies exactly one Issue.
This module never mutates GitHub, dispatches workflows or asserts model identity.
Actual GitHub REST metadata (actor + server timestamps) must be supplied by
an authorized, validating caller; never trust content-provided actor claims.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import secrets
from typing import Any

from tools.gpt_liveness_fleet_plan import parse_manifest, validate_snapshot
from tools.gpt_liveness_pilot import enrollment, challenge, answer, utc
from tools.kaep_mailbox_codec import InvalidMessage, validate, verify_reply_chain

SCHEMA = "gpt.liveness.turn-routing.v0.1"


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def new_turn_id() -> str:
    """Opaque, collision-resistant ID for ONE active GPT turn only."""
    return "turn_" + secrets.token_hex(16)


def new_session_id() -> str:
    """Opaque, independent bounded enrollment ID; no ChatGPT native ID claim."""
    return "session_" + secrets.token_hex(16)


def _admit(*, manifest: str, snapshots: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timedelta(0):
        _fail("INVALID_ROUTING_TIME")
    targets = parse_manifest(manifest)  # F6 existing exact allowlist and duplicate rejection
    if not isinstance(snapshots, dict) or set(targets) != set(snapshots):
        _fail("TURN_SNAPSHOT_SET_MISMATCH")
    rows: list[dict[str, Any]] = []
    used_turns: set[str] = set()
    for target in targets:
        state, body = validate_snapshot(snapshots[target], target=target)
        row: dict[str, Any] = {
            "mailbox_ref": target, "status": "UNOBSERVED",
            "participant_id": None, "session_id": None,
            "gpt_currently_alive_proven": False, "claim_authority": False,
        }
        if state == "closed":
            row["status"] = "ISSUE_CLOSED"
        else:
            current = enrollment(body, now=now)  # strict F4: single marker, finite expiry
            if current is not None:
                participant_id = current["turn_id"]
                if participant_id in used_turns:
                    _fail("DUPLICATE_ACTIVE_TURN")
                used_turns.add(participant_id)
                row.update({
                    "participant_id": participant_id, "session_id": current["session_id"],
                    "started_at": current["started_at"], "expires_at": current["expires_at"],
                    "expected_actor": current["expected_actor"],
                    "status": "LONG_RUNNING_DECLARED"
                        if current.get("long_running_until")
                        and utc(current["long_running_until"]) > now
                        else "ACTIVE_TURN_ENROLLMENT",
                })
        rows.append(row)
    return rows


def plan(*, manifest: str, snapshots: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Advisory only. Never reports ALIVE merely because enrollment exists."""
    return {
        "schema": SCHEMA,
        "targets": _admit(manifest=manifest, snapshots=snapshots, now=now),
        "write_authorized": False, "gpt_currently_alive_proven": False,
        "claim_authority": False,
    }


def route(*, report: dict[str, Any], participant_id: str) -> dict[str, Any]:
    """Find exactly one bound active turn, never by the common GitHub login."""
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        _fail("INVALID_TURN_ROUTING_REPORT")
    rows = report.get("targets")
    if not isinstance(rows, list):
        _fail("INVALID_TURN_ROUTING_REPORT")
    matches = [r for r in rows if isinstance(r, dict)
               and r.get("participant_id") == participant_id
               and r.get("status") in ("ACTIVE_TURN_ENROLLMENT", "LONG_RUNNING_DECLARED")]
    if len(matches) != 1:
        _fail("TURN_ROUTE_NOT_FOUND_OR_AMBIGUOUS")
    return {
        "participant_id": participant_id, "mailbox_ref": matches[0]["mailbox_ref"],
        "inbox_ref": matches[0]["mailbox_ref"], "outbox_ref": matches[0]["mailbox_ref"],
        "session_id": matches[0]["session_id"],
        "status": matches[0]["status"],
        "write_authorized": False, "claim_authority": False,
    }


def verify_pair(
    *, report: dict[str, Any], participant_id: str, mailbox_ref: str,
    ping_message: dict[str, Any], answer_message: dict[str, Any],
    ping_actor: str, answer_actor: str,
    ping_created_at: str, answer_created_at: str,
) -> dict[str, Any]:
    """Validate an independently observed pair *for this active turn*.

    A valid pair proves only a tool-mediated response at one observed instant.
    The transport actors and timestamps must be obtained from GitHub REST
    records by the caller, not from untrusted KAEP payload text.
    """
    r = route(report=report, participant_id=participant_id)
    if r["mailbox_ref"] != mailbox_ref:
        _fail("TURN_MAILBOX_MISMATCH")
    row = next(x for x in report["targets"] if x.get("mailbox_ref") == mailbox_ref)
    if (not isinstance(ping_actor, str)
            or ping_actor.casefold() != "github-actions[bot]"
            or not isinstance(answer_actor, str)
            or answer_actor.casefold() != row["expected_actor"].casefold()):
        _fail("TURN_ACTOR_MISMATCH")
    validate(ping_message, task_ref=mailbox_ref)
    validate(answer_message, task_ref=mailbox_ref)
    verify_reply_chain([ping_message, answer_message])
    if (ping_message["kind"] != "REQUEST" or ping_message["intent"] != "PING"
            or ping_message["recipient"] != "chatgpt"
            or ping_message["in_reply_to"] is not None
            or ping_message["scope"]["effect"] != "READ_ONLY"
            or answer_message["kind"] != "ANSWER"
            or answer_message["intent"] != "PING"
            or answer_message["in_reply_to"] != ping_message["message_id"]
            or answer_message["exchange_id"] != ping_message["exchange_id"]):
        _fail("TURN_REPLY_CHAIN_MISMATCH")
    c = challenge(ping_message["payload"]["text"])
    if c["turn_id"] != participant_id or c["session_id"] != r["session_id"]:
        _fail("TURN_CHALLENGE_IDENTITY_MISMATCH")
    issued, posted = utc(c["issued_at"]), utc(ping_created_at)
    answered = utc(answer_created_at)
    if (issued < utc(row["started_at"]) - timedelta(seconds=30)
            or posted < issued - timedelta(seconds=30)
            or answered < posted
            or answered > utc(c["expires_at"])
            or answered >= utc(row["expires_at"])):
        _fail("TURN_EVIDENCE_TIME_MISMATCH")
    proof = answer(answer_message["payload"]["text"], ping=c, now=answered)
    return {
        "participant_id": participant_id, "mailbox_ref": mailbox_ref,
        "session_id": r["session_id"],
        "status": "MODEL_TOOL_RESPONSE_OBSERVED",
        "mode": proof["mode"], "observed_at": answer_created_at,
        "claim_authority": False, "model_identity_attested": False,
        "gpt_currently_alive_proven": False,
    }


def format_manifest(targets: list[str]) -> str:
    """Read-only helper; caller still MUST supply allowed, live Issue snapshots."""
    raw = json.dumps({"schema": "gpt-liveness-fleet-plan.v0.1", "targets": targets})
    parse_manifest(raw)
    return raw
