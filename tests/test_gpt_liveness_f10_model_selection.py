"""F10 H1/H2: explicit active-model-turn PING selection, not sidecar auto-answer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
import unittest
from unittest import mock

from tools import gpt_liveness_mailbox as mailbox
from tools.kaep_mailbox_codec import encode_comment
from tools.gpt_liveness_pilot import iso, challenge
from tests.test_gpt_liveness_pilot import (
    REPO, ISSUE, NOW, NONCE, BOT, SESSION, TURN, body, first_ping, reply,
)


def gh_comment(message, comment_id, at, actor):
    return {
        "id": comment_id,
        "body": encode_comment(message),
        "user": {"login": actor},
        "created_at": iso(at),
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{ISSUE}",
        "html_url": f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-{comment_id}",
    }


class ExplicitModelSelectionTests(unittest.TestCase):
    def run_cli(self, argv, *, messages=None, registration=None, now=None, reply_result=None):
        if messages is None:
            _report, req = first_ping()
            messages = [gh_comment(req, 111, NOW, BOT)]
        raw = json.dumps([messages])
        with (mock.patch.object(mailbox, "fetch_issue", return_value=registration or body()),
              mock.patch.object(mailbox, "fetch_gh_pages", return_value=raw),
              mock.patch.object(mailbox, "datetime", wraps=datetime) as clock,
              mock.patch.object(mailbox, "send_reply",
                                return_value=reply_result or
                                {"status": "PREPARED", "posted_comment_id": None}) as send,
              mock.patch("sys.stdout", new_callable=io.StringIO) as output):
            clock.now.return_value = now or NOW + timedelta(minutes=1)
            code = mailbox.main(["--repository", REPO, "--issue", str(ISSUE)] + argv)
            return code, json.loads(output.getvalue()), send

    def test_read_only_lists_explicit_nonce_and_parent_without_reply(self):
        code, data, send = self.run_cli([])
        self.assertEqual(code, 0)
        self.assertEqual(data["status"], "MAILBOX_CHECKED")
        self.assertTrue(data["requires_explicit_model_challenge_selection"])
        self.assertFalse(data["automatic_answer_supported"])
        self.assertFalse(data["gpt_liveness_proven"])
        self.assertEqual(len(data["unanswered_pings"]), 1)
        item = data["unanswered_pings"][0]
        self.assertEqual(item["comment_id"], 111)
        self.assertEqual(item["session_id"], SESSION)
        self.assertEqual(item["turn_id"], TURN)
        self.assertEqual(item["nonce"], NONCE)
        send.assert_not_called()

    def test_model_must_explicitly_choose_inspected_comment_and_nonce(self):
        code, data, send = self.run_cli([
            "--respond", "--checkpoint", "F10 H2 active-turn inspected",
            "--reply-to-comment-id", "111", "--reply-to-nonce", NONCE,
        ])
        self.assertEqual(code, 0)
        self.assertEqual(data["status"], "PREPARED")
        self.assertTrue(data["model_selection_observed_in_tool_arguments"])
        self.assertFalse(data["model_identity_cryptographically_verified"])
        self.assertFalse(data["autonomous_gpt_wake_proven"])
        self.assertFalse(data["claim_authority"])
        self.assertFalse(send.call_args.kwargs["do_send"])
        self.assertEqual(send.call_args.kwargs["parent_recipient"], "chatgpt")
        self.assertEqual(send.call_args.kwargs["reply_recipient"], "coordinator")

    def test_send_requires_model_decision_and_both_explicit_selection_fields(self):
        for args, reason in [
            (["--send"], "EXPLICIT_RESPOND_REQUIRED"),
            (["--respond", "--checkpoint", "x"], "EXPLICIT_PING_SELECTION_REQUIRED"),
            (["--respond", "--checkpoint", "x",
              "--reply-to-comment-id", "111"], "EXPLICIT_PING_SELECTION_REQUIRED"),
            (["--respond", "--checkpoint", "x",
              "--reply-to-nonce", NONCE], "EXPLICIT_PING_SELECTION_REQUIRED"),
            (["--reply-to-comment-id", "111", "--reply-to-nonce", NONCE],
             "RESPONSE_SELECTION_WITHOUT_MODEL_DECISION"),
        ]:
            with self.subTest(args=args):
                code, data, send = self.run_cli(args)
                self.assertEqual(code, 2)
                self.assertEqual(data["status"], "BLOCKED")
                self.assertEqual(data["reason"], reason)
                send.assert_not_called()

    def test_wrong_nonce_or_comment_never_switches_to_current_root(self):
        for ident, nonce in [(112, NONCE), (111, "f" * 32)]:
            with self.subTest(ident=ident, nonce=nonce):
                code, data, send = self.run_cli([
                    "--respond", "--checkpoint", "x",
                    "--reply-to-comment-id", str(ident),
                    "--reply-to-nonce", nonce, "--send"])
                self.assertEqual(code, 2)
                self.assertEqual(data["reason"], "PING_SELECTION_STALE_OR_MISMATCHED")
                send.assert_not_called()

    def test_newer_ping_invalidates_old_selection_instead_of_auto_selecting(self):
        _r, old = first_ping()
        _r2, newer = first_ping(at=NOW + timedelta(minutes=5))
        msgs = [gh_comment(old, 111, NOW, BOT),
                gh_comment(newer, 222, NOW + timedelta(minutes=5), BOT)]
        code, data, send = self.run_cli([
            "--respond", "--checkpoint", "old selected",
            "--reply-to-comment-id", "111", "--reply-to-nonce", NONCE, "--send",
        ], messages=msgs, now=NOW + timedelta(minutes=6))
        self.assertEqual(code, 2)
        self.assertEqual(data["reason"], "PING_SELECTION_STALE_OR_MISMATCHED")
        send.assert_not_called()

    def test_wrong_turn_or_already_answered_or_expired_cannot_reply(self):
        _r, req = first_ping()
        rep = reply(req)
        for variant, kw in [
            ("turn", {"registration": body(turn_id="turn_different_20261017")}),
            ("answered", {"messages": [
                gh_comment(req, 111, NOW, BOT),
                gh_comment(rep, 112, NOW + timedelta(seconds=30), "kinoko34077"),
            ]}),
            ("expired", {"now": NOW + timedelta(minutes=16)}),
        ]:
            with self.subTest(variant=variant):
                code, data, send = self.run_cli([
                    "--respond", "--checkpoint", "x",
                    "--reply-to-comment-id", "111",
                    "--reply-to-nonce", NONCE, "--send",
                ], **kw)
                self.assertEqual(code, 2)
                self.assertEqual(data["reason"], "NO_VALID_PENDING_PING")
                send.assert_not_called()

    def test_explicit_send_is_only_optional_write_after_selected_model_turn(self):
        code, data, send = self.run_cli([
            "--respond", "--checkpoint", "selected model turn",
            "--reply-to-comment-id", "111", "--reply-to-nonce", NONCE, "--send",
        ], reply_result={"status": "SENT_AND_READ_BACK", "posted_comment_id": 789})
        self.assertEqual(code, 0)
        self.assertEqual(data["status"], "SENT_AND_READ_BACK")
        self.assertEqual(data["posted_comment_id"], 789)
        self.assertTrue(send.call_args.kwargs["do_send"])
        self.assertFalse(data["autonomous_gpt_wake_proven"])


if __name__ == "__main__":
    unittest.main()
