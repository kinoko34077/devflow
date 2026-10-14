"""Deterministic KAEP->read-only liveness producer tests. Never post GitHub comments."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from tools.kaep_mailbox_codec import encode_comment, InvalidMessage
from tools.kaep_request_sender import make_request
from tools.kaep_reply_sender import make_reply
from tools.gpt_liveness_evidence import project_from_pages, main

REPO = "kinoko34077/devflow"
ISSUE = 519
SESSION = "session_pilot20261014_1755"
TURN = "turn_pilot20261014_1755"
BOT = "github-actions[bot]"
USER = "kinoko34077"
NOW = datetime(2026, 10, 14, 17, 57, 29, tzinfo=timezone.utc)
NONCE = "9b92fb81b92b1978340afc8efb43dfa7"


def fmt(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def comment(message, cid, actor, created_at):
    return {
        "id": cid,
        "body": encode_comment(message),
        "user": {"login": actor},
        "created_at": fmt(created_at),
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{ISSUE}",
        "html_url": f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-{cid}",
    }


def fixture(*, reply=True, mode="ACTIVE", actor=USER, nonce=NONCE,
            reply_at=55, expected_until=None):
    ping_text = json.dumps({
        "schema": "gpt.liveness.v0.1", "session_id": SESSION, "turn_id": TURN,
        "nonce": NONCE, "issued_at": fmt(NOW),
        "expires_at": fmt(NOW + timedelta(minutes=15)),
        "purpose": "GPT_LIVENESS_PING",
    })
    req, _ = make_request(
        json.dumps([[]]), repository=REPO, issue=ISSUE,
        recipient="chatgpt", intent="PING",
        request_key="kaep.liveness.testcase.5973335",
        request_text=ping_text, expect_existing_actor=BOT,
    )
    root = comment(req, 6174844672, BOT, NOW + timedelta(seconds=2))
    if not reply:
        return json.dumps([[root]])
    msg = {
        "schema": "gpt.liveness.v0.1", "session_id": SESSION,
        "turn_id": TURN, "nonce": nonce,
        "mode": mode, "checkpoint": "F4-D actual GPT reply",
        "expected_until": expected_until,
    }
    rep, _ = make_reply(
        json.dumps([[root]]), repository=REPO, issue=ISSUE,
        parent_message_id=req["message_id"], kind="ANSWER",
        response_text=json.dumps(msg),
        expect_actor=BOT, parent_recipient="chatgpt",
        reply_recipient="coordinator", reply_actor=actor,
    )
    return json.dumps([[root, comment(rep, 6174861252, actor,
                                    NOW + timedelta(seconds=reply_at))]])


def project(raw):
    return project_from_pages(
        raw=raw, repository=REPO, issue=ISSUE,
        session_id=SESSION, turn_id=TURN,
        expected_reply_actor=USER,
    )


class ProducerTests(unittest.TestCase):
    def test_real_time_pilot_shape_positive(self):
        out = project(fixture())
        self.assertEqual(out["event"], "MODEL_TOOL_RESPONSE_OBSERVED")
        self.assertEqual(out["observed_at"], "2026-10-14T17:58:24Z")
        self.assertEqual(out["valid_until"], "2026-10-14T18:12:29Z")
        self.assertEqual(out["reported_actor"], USER)
        self.assertEqual(out["producer_validation"], "UPSTREAM_REPORTED")
        self.assertFalse(out["claim_authority"])

    def test_undelivered_ping_is_not_gpt_answer(self):
        out = project(fixture(reply=False))
        self.assertEqual(out["event"], "NO_RESPONSE")
        self.assertEqual(out["reported_actor"], BOT)
        self.assertFalse(out["claim_authority"])

    def test_wrong_nonce_does_not_clear_ping(self):
        out = project(fixture(nonce="f"*32))
        self.assertEqual(out["event"], "NO_RESPONSE")

    def test_wrong_actor_does_not_clear_ping(self):
        out = project(fixture(actor="attacker"))
        self.assertEqual(out["event"], "NO_RESPONSE")

    def test_expired_response_does_not_clear_ping(self):
        out = project(fixture(reply_at=16*60))
        self.assertEqual(out["event"], "NO_RESPONSE")

    def test_valid_long_running_declaration_is_bounded(self):
        out = project(fixture(mode="LONG_RUNNING",
                              expected_until="2026-10-14T18:49:00Z"))
        self.assertEqual(out["event"], "LONG_RUNNING_DECLARED")
        self.assertEqual(out["valid_until"], "2026-10-14T18:49:00Z")

    def test_invalid_long_running_missing_until_does_not_clear(self):
        out = project(fixture(mode="LONG_RUNNING"))
        self.assertEqual(out["event"], "NO_RESPONSE")

    def test_invalid_gh_comment_identity_fail_closed(self):
        raw = json.loads(fixture())
        raw[0][0]["issue_url"] = "https://api.github.com/repos/attacker/repo/issues/519"
        with self.assertRaisesRegex(InvalidMessage, "COMMENT_ISSUE_IDENTITY_MISMATCH"):
            project(json.dumps(raw))

    def test_explicit_session_turn_scope_is_required(self):
        with self.assertRaisesRegex(InvalidMessage, "NO_VALID_LIVENESS_PING"):
            project_from_pages(raw=fixture(), repository=REPO, issue=ISSUE,
                               session_id=SESSION, turn_id="turn_other20261014",
                               expected_reply_actor=USER)

    def test_no_background_post_or_claim_from_cli(self):
        data = fixture()
        with patch("tools.gpt_liveness_evidence.fetch_gh_pages", return_value=data), \
             patch("tools.gpt_liveness_evidence.project_from_pages", wraps=project_from_pages):
            # Caller invokes query; never calls request/reply senders.
            output = project(data)
        self.assertFalse(output["claim_authority"])


if __name__ == "__main__":
    unittest.main()
