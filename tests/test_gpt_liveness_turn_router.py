"""Turn-scoped GPT heartbeat routing, fake inputs only; no Github writes."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from tools import gpt_liveness_turn_router as router
from tools.kaep_mailbox_codec import InvalidMessage

NOW = datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc)
A, B = "kinoko34077/devflow#700", "kinoko34077/devflow#701"
TA, TB = "turn_" + "1" * 32, "turn_" + "2" * 32
SA, SB = "session_" + "a" * 32, "session_" + "b" * 32


def record(mailbox, session, turn, *, enabled=True, state="open",
           expiry="2026-10-16T02:00:00Z", start="2026-10-16T00:00:00Z",
           long_until=None):
    m = {"schema": "gpt.liveness.v0.1", "session_id": session, "turn_id": turn,
         "started_at": start, "expires_at": expiry,
         "expected_actor": "kinoko34077", "enabled": enabled}
    if long_until:
        m["long_running_until"] = long_until
    return {
        "repository": "kinoko34077/devflow",
        "number": int(mailbox.split("#")[1]), "state": state,
        "body": "<!-- gpt-liveness:enrollment:v0.1 " + json.dumps(m) + " -->",
    }


def inputs(a=None, b=None, targets=None):
    manifest = router.format_manifest([A, B] if targets is None else targets)
    snapshots = {
        A: record(A, SA, TA) if a is None else a,
        B: record(B, SB, TB) if b is None else b,
    }
    return manifest, snapshots


def plan(a=None, b=None):
    manifest, snaps = inputs(a, b)
    return router.plan(manifest=manifest, snapshots=snaps, now=NOW)


def pair(mailbox=A, *, session=SA, turn=TA, nonce="f" * 32):
    challenge = {"schema": "gpt.liveness.v0.1", "session_id": session, "turn_id": turn,
                 "nonce": nonce, "issued_at": "2026-10-16T00:57:00Z",
                 "expires_at": "2026-10-16T01:10:00Z", "purpose": "GPT_LIVENESS_PING"}
    response = {"schema": "gpt.liveness.v0.1", "session_id": session, "turn_id": turn,
                "nonce": nonce, "mode": "FINISHED", "checkpoint": "done",
                "expected_until": None}
    request = {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": "ex_" + "a" * 16, "message_id": "msg_" + "b" * 16,
        "in_reply_to": None, "task_ref": mailbox, "recipient": "chatgpt",
        "kind": "REQUEST", "intent": "PING", "idempotency_key": "ping." + "a" * 12,
        "scope": {"repository": "kinoko34077/devflow", "expected_head": None,
                  "effect": "READ_ONLY"}, "payload": {"text": json.dumps(challenge)},
        "evidence_refs": [],
    }
    reply = {
        "schema_version": "kaep.message.v0.2", "exchange_id": request["exchange_id"],
        "message_id": "msg_" + "c" * 16, "in_reply_to": request["message_id"],
        "task_ref": mailbox, "recipient": "coordinator", "kind": "ANSWER", "intent": "PING",
        "idempotency_key": "reply." + "b" * 12,
        "scope": {"repository": "kinoko34077/devflow", "expected_head": None,
                  "effect": "READ_ONLY"}, "payload": {"text": json.dumps(response)},
        "evidence_refs": [],
    }
    return request, reply


def check(p, participant=TA, mailbox=A, request=None, reply=None,
          ping_actor="github-actions[bot]", answer_actor="kinoko34077",
          posted="2026-10-16T00:57:02Z", answered="2026-10-16T01:00:00Z"):
    if request is None or reply is None:
        request, reply = pair()
    return router.verify_pair(
        report=p, participant_id=participant, mailbox_ref=mailbox,
        ping_message=request, answer_message=reply,
        ping_actor=ping_actor, answer_actor=answer_actor,
        ping_created_at=posted, answer_created_at=answered)


class TurnRoutingTests(unittest.TestCase):
    def test_random_turn_id_not_chat_title_or_timestamp(self):
        a, b = router.new_turn_id(), router.new_turn_id()
        self.assertRegex(a, r"^turn_[0-9a-f]{32}$")
        self.assertNotEqual(a, b)
        self.assertRegex(router.new_session_id(), r"^session_[0-9a-f]{32}$")

    def test_two_concurrent_turns_with_same_github_actor_have_distinct_routes(self):
        p = plan()
        self.assertFalse(p["write_authorized"])
        self.assertFalse(p["gpt_currently_alive_proven"])
        self.assertEqual(router.route(report=p, participant_id=TA)["inbox_ref"], A)
        self.assertEqual(router.route(report=p, participant_id=TB)["outbox_ref"], B)
        proof_a = check(p)
        request, reply = pair(B, session=SB, turn=TB)
        proof_b = check(p, TB, B, request, reply)
        self.assertEqual(proof_a["status"], "MODEL_TOOL_RESPONSE_OBSERVED")
        self.assertEqual(proof_b["status"], "MODEL_TOOL_RESPONSE_OBSERVED")
        self.assertNotEqual(proof_a["participant_id"], proof_b["participant_id"])
        self.assertFalse(proof_b["model_identity_attested"])
        self.assertFalse(proof_a["gpt_currently_alive_proven"])

    def test_cross_turn_answer_rejected_even_with_same_github_actor(self):
        with self.assertRaises(InvalidMessage):
            check(plan(), participant=TB, mailbox=B)
        request, reply = pair(B, session=SB, turn=TB)
        with self.assertRaises(InvalidMessage):
            check(plan(), participant=TA, mailbox=A, request=request, reply=reply)

    def test_duplicate_active_turn_in_two_mailboxes_rejected(self):
        m, snaps = inputs(b=record(B, SB, TA))
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_ACTIVE_TURN"):
            router.plan(manifest=m, snapshots=snaps, now=NOW)

    def test_disabled_expired_closed_not_routed(self):
        b = record(B, SB, TB, enabled=False)
        p = plan(b=b)
        self.assertEqual(p["targets"][1]["status"], "UNOBSERVED")
        with self.assertRaises(InvalidMessage):
            router.route(report=p, participant_id=TB)
        for b in (record(B, SB, TB, expiry="2026-10-16T00:30:00Z"),
                  record(B, SB, TB, state="closed")):
            p = plan(b=b)
            with self.assertRaises(InvalidMessage):
                router.route(report=p, participant_id=TB)

    def test_invalid_or_multiple_registration_rejected(self):
        dup = record(A, SA, TA)
        dup["body"] += dup["body"]
        m, snaps = inputs(a=dup)
        with self.assertRaises(InvalidMessage):
            router.plan(manifest=m, snapshots=snaps, now=NOW)

    def test_manifest_missing_extra_and_duplicate_target_rejected(self):
        m, snaps = inputs()
        del snaps[B]
        with self.assertRaises(InvalidMessage):
            router.plan(manifest=m, snapshots=snaps, now=NOW)
        with self.assertRaises(InvalidMessage):
            router.format_manifest([A, A])
        with self.assertRaises(InvalidMessage):
            router.format_manifest(["kinoko34077/unknown#0"])

    def test_nonce_cross_exchange_parent_wrong_reply_rejected(self):
        r, a = pair()
        a["payload"]["text"] = json.dumps({**json.loads(a["payload"]["text"]), "nonce": "e" * 32})
        with self.assertRaises(InvalidMessage):
            check(plan(), request=r, reply=a)
        r, a = pair()
        a["exchange_id"] = "ex_" + "e" * 16
        with self.assertRaises(InvalidMessage):
            check(plan(), request=r, reply=a)
        r, a = pair()
        a["in_reply_to"] = "msg_" + "z" * 16
        with self.assertRaises(InvalidMessage):
            check(plan(), request=r, reply=a)

    def test_untrusted_actor_or_timing_rejected(self):
        with self.assertRaises(InvalidMessage):
            check(plan(), answer_actor="another-gpt")
        with self.assertRaises(InvalidMessage):
            check(plan(), ping_actor="kinoko34077")
        with self.assertRaises(InvalidMessage):
            check(plan(), posted="2026-10-16T00:50:00Z")
        with self.assertRaises(InvalidMessage):
            check(plan(), answered="2026-10-16T01:11:00Z")

    def test_no_stable_chat_id_binding_needed(self):
        p = plan()
        for row in p["targets"]:
            self.assertNotIn("chat_id", row)
            self.assertNotIn("chat_binding", row)
            self.assertIsNotNone(row["participant_id"])
        source = Path(router.__file__).read_text(encoding="utf-8")
        for forbidden in ("post_comment(", "workflow_dispatch(", "subprocess.run(",
                          "requests.post(", "add_comment_to_issue("):
            self.assertNotIn(forbidden, source)

    def test_long_running_remains_read_only(self):
        p = plan(b=record(B, SB, TB, long_until="2026-10-16T01:30:00Z"))
        self.assertEqual(p["targets"][1]["status"], "LONG_RUNNING_DECLARED")
        self.assertFalse(router.route(report=p, participant_id=TB)["write_authorized"])

    def test_current_single_issue_legacy_sender_untouched(self):
        root = Path(__file__).resolve().parents[1]
        f8 = (root / "tools/gpt_liveness_f8_sender.py").read_text(encoding="utf-8")
        self.assertIn('ALLOWED_MAILBOX = "kinoko34077/devflow#554"', f8)


if __name__ == "__main__":
    unittest.main()
