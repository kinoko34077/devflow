"""Cross-chat heartbeat isolation: no external writes, credentials, or schedule."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from tools import gpt_liveness_chat_registry as route
from tools.kaep_mailbox_codec import InvalidMessage

NOW = datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc)
A = "kinoko34077/devflow#700"
B = "kinoko34077/devflow#701"
CHAT_A = "chat_" + "a" * 32
CHAT_B = "chat_" + "b" * 32
SESSION_A = "session_" + "1" * 32
SESSION_B = "session_" + "2" * 32
TURN_A = "turn_" + "3" * 32
TURN_B = "turn_" + "4" * 32


def snapshot(target, chat, session, turn, *, enabled=True):
    bind = route.binding_marker(chat_id=chat, mailbox_ref=target)
    enroll = {
        "schema": "gpt.liveness.v0.1", "session_id": session, "turn_id": turn,
        "started_at": "2026-10-16T00:00:00Z", "expires_at": "2026-10-16T02:00:00Z",
        "expected_actor": "kinoko34077", "enabled": enabled,
    }
    body = bind + "\n<!-- gpt-liveness:enrollment:v0.1 " + json.dumps(enroll) + " -->"
    return {
        "repository": "kinoko34077/devflow",
        "number": int(target.partition("#")[2]), "state": "open", "body": body,
    }


def get_plan(*, b_enabled=True):
    m = json.dumps({"schema": "gpt-liveness-fleet-plan.v0.1", "targets": [A, B]})
    return route.read_only_plan(manifest=m, now=NOW, snapshots={
        A: snapshot(A, CHAT_A, SESSION_A, TURN_A),
        B: snapshot(B, CHAT_B, SESSION_B, TURN_B, enabled=b_enabled),
    })


def pair(target=A, *, session=SESSION_A, turn=TURN_A, nonce="f" * 32):
    challenge = {
        "schema": "gpt.liveness.v0.1", "session_id": session, "turn_id": turn,
        "nonce": nonce, "issued_at": "2026-10-16T00:57:00Z",
        "expires_at": "2026-10-16T01:10:00Z", "purpose": "GPT_LIVENESS_PING",
    }
    answer = {
        "schema": "gpt.liveness.v0.1", "session_id": session,
        "turn_id": turn, "nonce": nonce, "mode": "FINISHED",
        "checkpoint": "done", "expected_until": None,
    }
    req = {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": "ex_" + "c" * 16, "message_id": "msg_" + "a" * 16,
        "in_reply_to": None, "task_ref": target, "recipient": "chatgpt",
        "kind": "REQUEST", "intent": "PING",
        "idempotency_key": "test.ping." + "a" * 12,
        "scope": {"repository": "kinoko34077/devflow", "expected_head": None, "effect": "READ_ONLY"},
        "payload": {"text": json.dumps(challenge)}, "evidence_refs": [],
    }
    reply = {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": req["exchange_id"], "message_id": "msg_" + "b" * 16,
        "in_reply_to": req["message_id"], "task_ref": target,
        "recipient": "coordinator", "kind": "ANSWER", "intent": "PING",
        "idempotency_key": "test.answer." + "b" * 12,
        "scope": {"repository": "kinoko34077/devflow", "expected_head": None, "effect": "READ_ONLY"},
        "payload": {"text": json.dumps(answer)}, "evidence_refs": [],
    }
    return req, reply


def check(table, chat=CHAT_A, target=A, req=None, reply=None,
          response_actor="kinoko34077",
          posted_at="2026-10-16T00:57:02Z",
          replied_at="2026-10-16T01:00:00Z"):
    if req is None or reply is None:
        req, reply = pair()
    return route.validate_heartbeat_pair(
        plan=table, chat_id=chat, mailbox_ref=target,
        ping_message=req, answer_message=reply,
        ping_actor="github-actions[bot]", answer_actor=response_actor,
        ping_created_at=posted_at, answer_created_at=replied_at,
    )


class PerChatHeartbeatTests(unittest.TestCase):
    def test_cryptographic_ids_are_distinct(self):
        x, y = route.new_chat_id(), route.new_chat_id()
        self.assertRegex(x, "^chat_[0-9a-f]{32}$")
        self.assertNotEqual(x, y)
        self.assertRegex(route.new_session_id(), "^session_[0-9a-f]{32}$")
        self.assertRegex(route.new_turn_id(), "^turn_[0-9a-f]{32}$")

    def test_two_chats_have_distinct_mailboxes_same_github_actor(self):
        p = get_plan()
        self.assertEqual({e["chat_id"] for e in p["entries"]}, {CHAT_A, CHAT_B})
        self.assertEqual({e["mailbox_ref"] for e in p["entries"]}, {A, B})
        self.assertFalse(p["writable"])
        self.assertFalse(p["gpt_currently_alive_proven"])
        self.assertEqual(check(p)["status"], "MODEL_TOOL_RESPONSE_OBSERVED")
        req, reply = pair(B, session=SESSION_B, turn=TURN_B)
        self.assertEqual(check(p, CHAT_B, B, req, reply)["chat_id"], CHAT_B)

    def test_chat_a_proof_never_proves_chat_b(self):
        with self.assertRaises(InvalidMessage):
            check(get_plan(), CHAT_B, B)

    def test_disabled_b_ignores_a_heartbeat(self):
        p = get_plan(b_enabled=False)
        self.assertEqual(p["entries"][1]["status"], "NO_ACTIVE_ENROLLMENT")
        req, reply = pair(B, session=SESSION_B, turn=TURN_B)
        with self.assertRaises(InvalidMessage):
            check(p, CHAT_B, B, req, reply)

    def test_duplicate_chat_id_rejected(self):
        manifest = json.dumps({"schema": "gpt-liveness-fleet-plan.v0.1", "targets": [A, B]})
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_CHAT_ID"):
            route.read_only_plan(manifest=manifest, now=NOW, snapshots={
                A: snapshot(A, CHAT_A, SESSION_A, TURN_A),
                B: snapshot(B, CHAT_A, SESSION_B, TURN_B),
            })

    def test_duplicate_issue_rejected_by_f6_manifest(self):
        manifest = json.dumps({"schema": "gpt-liveness-fleet-plan.v0.1", "targets": [A, A]})
        with self.assertRaises(InvalidMessage):
            route.read_only_plan(manifest=manifest, now=NOW, snapshots={})

    def test_one_exact_binding_in_canonical_issue_body_required(self):
        mark = route.binding_marker(chat_id=CHAT_A, mailbox_ref=A)
        with self.assertRaises(InvalidMessage):
            route.parse_binding(mark + "\n" + mark, mailbox_ref=A)
        with self.assertRaises(InvalidMessage):
            route.parse_binding(mark, mailbox_ref=B)
        with self.assertRaises(InvalidMessage):
            route.parse_binding("", mailbox_ref=A)
        with self.assertRaises(InvalidMessage):
            route.binding_marker(chat_id="chat_weak", mailbox_ref=A)

    def test_session_turn_nonce_and_parent_mismatch_fail_closed(self):
        req, reply = pair(session=SESSION_B)
        with self.assertRaises(InvalidMessage):
            check(get_plan(), req=req, reply=reply)
        req, reply = pair()
        reply["payload"]["text"] = json.dumps({**json.loads(reply["payload"]["text"]), "nonce": "e" * 32})
        with self.assertRaises(InvalidMessage):
            check(get_plan(), req=req, reply=reply)
        req, reply = pair()
        reply["in_reply_to"] = "msg_" + "c" * 16
        with self.assertRaises(InvalidMessage):
            check(get_plan(), req=req, reply=reply)

    def test_wrong_mailbox_even_if_nonce_is_identical(self):
        req, reply = pair()
        with self.assertRaises(InvalidMessage):
            check(get_plan(), CHAT_B, B, req, reply)

    def test_actor_and_time_boundary(self):
        with self.assertRaises(InvalidMessage):
            check(get_plan(), response_actor="some-other-account")
        with self.assertRaises(InvalidMessage):
            check(get_plan(), replied_at="2026-10-16T01:11:00Z")
        with self.assertRaises(InvalidMessage):
            check(get_plan(), posted_at="2026-10-16T00:56:00Z")

    def test_narrow_evidence_never_claims_platform_identity(self):
        result = check(get_plan())
        self.assertFalse(result["model_identity_attested"])
        self.assertFalse(result["current_liveness_proven"])
        self.assertFalse(result["claim_authority"])
        source = Path(route.__file__).read_text(encoding="utf-8")
        for prohibited in ("post_comment(", "workflow_dispatch(", "subprocess.run(", "requests.post("):
            self.assertNotIn(prohibited, source)


if __name__ == "__main__":
    unittest.main()
