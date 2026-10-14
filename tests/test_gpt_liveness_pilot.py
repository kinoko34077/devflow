"""Offline liveness PING/ANSWER tests; never mutate GitHub or trigger ChatGPT."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from tools.kaep_mailbox_codec import encode_comment, InvalidMessage
from tools.kaep_request_sender import make_request
from tools.kaep_reply_sender import make_reply, ACTOR
from tools.gpt_liveness_pilot import (
    SCHEMA, MARKER, END, enrollment, plan, challenge, answer, utc, iso, main
)

REPO = "kinoko34077/devflow"
ISSUE = 519
NOW = datetime(2026, 10, 14, 4, 30, tzinfo=timezone.utc)
NONCE = "0" * 32
SESSION = "session_20261014x"
TURN = "turn_20261014x"
BOT = "github-actions[bot]"


def body(*, minutes=60, enabled=True, **overrides):
    d = {
        "schema": SCHEMA, "session_id": SESSION, "turn_id": TURN,
        "started_at": iso(NOW - timedelta(minutes=1)),
        "expires_at": iso(NOW + timedelta(minutes=minutes)),
        "expected_actor": "kinoko34077", "enabled": enabled,
    }
    d.update(overrides)
    return "Implementation issue\n" + MARKER + json.dumps(d) + END


def page_msg(d, cid, at=NOW, actor="kinoko34077"):
    return {"id": cid, "body": encode_comment(d),
            "actor_login": actor, "created_at": iso(at)}


def first_ping(at=NOW):
    out = plan(body=body(), comments=[], repo=REPO, issue=ISSUE, now=at, nonce=NONCE)
    req, _ = make_request(json.dumps([[]]), repository=REPO, issue=ISSUE, recipient="chatgpt",
                          intent="PING", request_key=out["request_key"],
                          request_text=out["request_text"], expect_existing_actor=BOT)
    return out, req


def reply(req, *, mode="ACTIVE", nonce=NONCE, checkpoint="checkpoint-1", expected_until=None):
    payload = {"schema": SCHEMA, "session_id": SESSION, "turn_id": TURN,
               "nonce": nonce, "mode": mode, "checkpoint": checkpoint,
               "expected_until": expected_until}
    rep, _ = make_reply(
        json.dumps([[{"id": 1, "body": encode_comment(req),
                      "user": {"login": BOT}}]]),
        repository=REPO, issue=ISSUE, parent_message_id=req["message_id"],
        kind="ANSWER", response_text=json.dumps(payload), expect_actor=BOT,
        parent_recipient="chatgpt", reply_recipient="coordinator",
        reply_actor="kinoko34077",
    )
    return rep


class LivenessContractTests(unittest.TestCase):
    def test_no_enrollment_zero_posts(self):
        self.assertEqual(plan(body="normal Issue", comments=[], repo=REPO, issue=ISSUE,
                              now=NOW, nonce=NONCE)["status"], "NO_ACTIVE_ENROLLMENT")

    def test_disabled_expired(self):
        self.assertIsNone(enrollment(body(enabled=False), now=NOW))
        self.assertIsNone(enrollment(body(started_at=iso(NOW - timedelta(minutes=20)),
                                          expires_at=iso(NOW - timedelta(minutes=10))), now=NOW))

    def test_registration_rejects_wrong_fields_and_overlong(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_ENROLLMENT_FIELDS"):
            enrollment(body(secret="never"), now=NOW)
        with self.assertRaisesRegex(InvalidMessage, "INVALID_ENROLLMENT_DURATION"):
            enrollment(body(minutes=200), now=NOW)
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_ENROLLMENT"):
            enrollment(body() + "\n" + body(), now=NOW)

    def test_declared_long_running_suppresses_ping_until_deadline(self):
        extended = body(long_running_until=iso(NOW + timedelta(minutes=35)))
        self.assertEqual(plan(body=extended, comments=[], repo=REPO, issue=ISSUE,
                              now=NOW, nonce=NONCE)["status"], "LONG_RUNNING")
        self.assertEqual(plan(body=extended, comments=[], repo=REPO, issue=ISSUE,
                              now=NOW + timedelta(minutes=40), nonce=NONCE)["status"], "READY")
        with self.assertRaisesRegex(InvalidMessage, "INVALID_LONG_RUNNING_DEADLINE"):
            enrollment(body(long_running_until=iso(NOW + timedelta(hours=3))), now=NOW)

    def test_first_ping_kaep_roundtrip(self):
        result, req = first_ping()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(req["kind"], "REQUEST")
        self.assertEqual(req["intent"], "PING")
        self.assertEqual(req["task_ref"], f"{REPO}#{ISSUE}")
        self.assertEqual(challenge(req["payload"]["text"])["nonce"], NONCE)
        self.assertTrue(ACTOR.fullmatch(BOT))
        self.assertFalse(ACTOR.fullmatch("github-actions[bot]evil"))

    def test_existing_bucket_is_idempotent(self):
        _, req = first_ping()
        out = plan(body=body(), comments=[page_msg(req, 10, actor=BOT)],
                   repo=REPO, issue=ISSUE, now=NOW, nonce="1" * 32)
        self.assertEqual(out["status"], "ALREADY_PINGED")

    def test_three_pending_stop_without_claim_effect(self):
        comments = []
        for i in range(3):
            at = NOW + timedelta(minutes=i * 5)
            _, request = first_ping(at)
            comments.append(page_msg(request, 10 + i, at=at, actor=BOT))
        result = plan(body=body(minutes=100), comments=comments,
                      repo=REPO, issue=ISSUE, now=NOW + timedelta(minutes=15),
                      nonce=NONCE)
        self.assertEqual(result["status"], "SUSPECT_NO_REPLY")
        self.assertEqual(result["unanswered"], 3)
        self.assertFalse(result["claim_authority"])

    def test_ack_does_not_count_as_gpt_answer(self):
        _, req = first_ping()
        ack = dict(req, message_id="msg_ack001", in_reply_to=req["message_id"],
                   idempotency_key="kaep.liveness.ack001", recipient="claude-code",
                   kind="ACK", payload={"text": "transport only"})
        out = plan(body=body(), comments=[page_msg(req, 1, actor=BOT), page_msg(ack, 2)],
                   repo=REPO, issue=ISSUE, now=NOW + timedelta(minutes=5), nonce="a" * 32)
        self.assertEqual(out["unanswered"], 1)

    def test_answer_must_match_nonce_session_and_expiry(self):
        _, req = first_ping()
        ping = challenge(req["payload"]["text"])
        good = {"schema": SCHEMA, "session_id": SESSION, "turn_id": TURN,
                "nonce": NONCE, "mode": "ACTIVE", "checkpoint": "x",
                "expected_until": None}
        self.assertEqual(answer(json.dumps(good), ping=ping, now=NOW)["mode"], "ACTIVE")
        for bad in (
            dict(good, nonce="f" * 32), dict(good, turn_id="wrong"),
            dict(good, expected_until=iso(NOW + timedelta(hours=1))),
        ):
            with self.assertRaises(InvalidMessage):
                answer(json.dumps(bad), ping=ping, now=NOW)
        with self.assertRaisesRegex(InvalidMessage, "EXPIRED_CHALLENGE"):
            answer(json.dumps(good), ping=ping, now=NOW + timedelta(minutes=20))

    def test_valid_answer_stays_answered_after_window(self):
        _, req = first_ping()
        rep = reply(req)
        comments = [page_msg(req, 1, at=NOW, actor=BOT),
                    page_msg(rep, 2, at=NOW + timedelta(seconds=30))]
        out = plan(body=body(), comments=comments, repo=REPO,
                   issue=ISSUE, now=NOW + timedelta(minutes=20), nonce="a"*32)
        self.assertEqual(out["status"], "READY")
        self.assertEqual(out["unanswered"], 0)

    def test_late_answer_not_proof(self):
        _, req = first_ping()
        rep = reply(req)
        comments = [page_msg(req, 1, at=NOW, actor=BOT),
                    page_msg(rep, 2, at=NOW + timedelta(minutes=19))]
        out = plan(body=body(), comments=comments, repo=REPO,
                   issue=ISSUE, now=NOW + timedelta(minutes=20), nonce="a"*32)
        self.assertEqual(out["unanswered"], 1)

    def test_long_running_requires_finite_future_deadline(self):
        _, req = first_ping()
        ping = challenge(req["payload"]["text"])
        payload = {"schema": SCHEMA, "session_id": SESSION, "turn_id": TURN,
                   "nonce": NONCE, "mode": "LONG_RUNNING", "checkpoint": "compile",
                   "expected_until": iso(NOW + timedelta(minutes=50))}
        self.assertEqual(answer(json.dumps(payload), ping=ping, now=NOW)["mode"], "LONG_RUNNING")
        payload["expected_until"] = None
        with self.assertRaisesRegex(InvalidMessage, "LONG_RUNNING_MISSING_DEADLINE"):
            answer(json.dumps(payload), ping=ping, now=NOW)

    def test_untrusted_ping_cannot_suppress_real_probe(self):
        _, req = first_ping()
        result = plan(body=body(), comments=[page_msg(req, 1, actor="untrusted")],
                      repo=REPO, issue=ISSUE, now=NOW, nonce="a"*32)
        self.assertEqual(result["status"], "READY")

    def test_wrong_actor_not_accepted(self):
        _, req = first_ping()
        rep = reply(req)
        result = plan(body=body(), comments=[page_msg(req, 1, actor=BOT),
                        page_msg(rep, 2, actor="untrusted")],
                      repo=REPO, issue=ISSUE, now=NOW + timedelta(minutes=5),
                      nonce="f"*32)
        self.assertEqual(result["unanswered"], 1)


    def test_mailbox_receives_only_fresh_valid_bot_ping(self):
        from tools.gpt_liveness_mailbox import pending_pings
        _, req = first_ping()
        result = pending_pings(body=body(),
            comments=[page_msg(req, 1, at=NOW, actor=BOT)],
            repo=REPO, issue=ISSUE, now=NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["parent_message_id"], req["message_id"])
        self.assertEqual(pending_pings(body=body(),
            comments=[page_msg(req, 1, at=NOW, actor="unknown")],
            repo=REPO, issue=ISSUE, now=NOW), [])

    def test_mailbox_accepts_only_timed_authenticated_matching_answer(self):
        from tools.gpt_liveness_mailbox import pending_pings
        _, req = first_ping()
        rep = reply(req)
        root = page_msg(req, 1, at=NOW, actor=BOT)
        valid = page_msg(rep, 2, at=NOW + timedelta(seconds=30))
        self.assertEqual(pending_pings(body=body(), comments=[root, valid],
                                       repo=REPO, issue=ISSUE, now=NOW + timedelta(minutes=5)), [])
        attacker = page_msg(rep, 2, at=NOW + timedelta(seconds=30), actor="attacker")
        self.assertEqual(len(pending_pings(body=body(), comments=[root, attacker],
                           repo=REPO, issue=ISSUE, now=NOW + timedelta(minutes=5))), 1)
        late = page_msg(rep, 2, at=NOW + timedelta(minutes=16))
        self.assertEqual(len(pending_pings(body=body(), comments=[root, late],
                           repo=REPO, issue=ISSUE, now=NOW + timedelta(minutes=18))), 0)
        # At 18 min the root challenge itself has expired and must not reappear.

    def test_explicit_respond_gate(self):
        from tools.gpt_liveness_mailbox import main as mailbox_main
        with patch("tools.gpt_liveness_mailbox.fetch_issue") as f:
            self.assertEqual(mailbox_main(["--send"]), 2)
            f.assert_not_called()

    def test_model_answer_composer_validates_deadline(self):
        from tools.gpt_liveness_mailbox import create_answer
        _, req = first_ping()
        ping = challenge(req["payload"]["text"])
        res = create_answer(ping=ping, mode="ACTIVE", checkpoint="F1", expected_until=None, now=NOW)
        self.assertEqual(json.loads(res)["nonce"], NONCE)
        with self.assertRaises(InvalidMessage):
            create_answer(ping=ping, mode="LONG_RUNNING", checkpoint="F1",
                          expected_until=None, now=NOW)

    def test_cli_without_enrollment_does_not_fetch_mailbox(self):
        with patch("tools.gpt_liveness_pilot.fetch_issue", return_value="no enrollment"), \
             patch("tools.gpt_liveness_pilot.fetch_gh_pages") as fetch:
            self.assertEqual(main(["--issue", str(ISSUE), "--send"]), 0)
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
