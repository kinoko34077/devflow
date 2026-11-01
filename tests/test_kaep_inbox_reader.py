"""KAEP inbox read-only preflight tests: no agent, posting, network or Claim."""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.kaep_inbox_reader import (
    MAX_RESPONSE_BYTES, InvalidMessage, fetch_gh_pages,
    inspect_pages, parse_pages, main,
)
from tools.kaep_mailbox_codec import encode_comment

REPO = "kinoko34077/devflow"
TASK = REPO + "#503"


def envelope(*, kind="REQUEST", recipient="claude-code", message_id="msg_msg001",
             in_reply_to=None, exchange_id="ex_exchange001", text="M1 PING"):
    return {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": exchange_id,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "task_ref": TASK,
        "recipient": recipient,
        "kind": kind,
        "intent": "PING",
        "idempotency_key": "kaep.test." + message_id,
        "scope": {"repository": REPO, "expected_head": None, "effect": "READ_ONLY"},
        "payload": {"text": text},
        "evidence_refs": [],
    }


def comment(cid, body, actor="kinoko34077"):
    return {"id": cid, "body": body, "user": {"login": actor}}


def pages(*groups):
    return json.dumps(list(groups), ensure_ascii=False)


class ReadOnlyInboxTests(unittest.TestCase):
    def assert_blocked(self, text, code):
        with self.assertRaisesRegex(InvalidMessage, code):
            inspect_pages(text, repository=REPO, issue=503,
                          recipient="claude-code")

    def test_empty_inbox(self):
        d = inspect_pages(pages([]), repository=REPO, issue=503,
                          recipient="claude-code")
        self.assertEqual(d["messages"], [])
        self.assertEqual(d["observed_latest_comment_id"], 0)
        self.assertTrue(d["read_only"])

    def test_real_m1_shape_no_forged_ack(self):
        ping = encode_comment(envelope())
        d = inspect_pages(pages([comment(11, ping)]), repository=REPO,
                          issue=503, recipient="claude-code")
        self.assertEqual([m["message_id"] for m in d["messages"]],
                         ["msg_msg001"])
        self.assertFalse(d["messages"][0]["provider_identity_verified"])
        self.assertFalse(d["claim_or_agent_execution_proven"])
        self.assertNotIn("untrusted_payload_text", d["messages"][0])

    def test_explicit_untrusted_text(self):
        d = inspect_pages(pages([comment(11, encode_comment(envelope()))]),
                          repository=REPO, issue=503, recipient="claude-code",
                          include_text=True)
        self.assertEqual(d["messages"][0]["untrusted_payload_text"], "M1 PING")

    def test_response_correlated_to_parent(self):
        ping = encode_comment(envelope())
        ack = encode_comment(envelope(kind="ACK", recipient="chatgpt",
                                     message_id="msg_ack002",
                                     in_reply_to="msg_msg001"))
        d = inspect_pages(pages([comment(11, ping),
                                 comment(12, ack, actor="shared-user")]),
                          repository=REPO, issue=503, recipient="chatgpt")
        self.assertEqual(len(d["messages"]), 1)
        self.assertEqual(d["messages"][0]["github_actor_login"], "shared-user")
        self.assertFalse(d["messages"][0]["provider_identity_verified"])

    def test_missing_reply_parent_fails_closed(self):
        ack = encode_comment(envelope(kind="ACK", recipient="chatgpt",
                                     message_id="msg_ack002",
                                     in_reply_to="msg_missing"))
        self.assert_blocked(pages([comment(11, ack)]), "UNKNOWN_PARENT")

    def test_cross_exchange_quarantined_and_reported(self):
        ping = encode_comment(envelope())
        ack = encode_comment(envelope(kind="ACK", recipient="chatgpt",
                                     message_id="msg_ack002",
                                     in_reply_to="msg_msg001",
                                     exchange_id="ex_another"))
        independent = encode_comment(envelope(
            message_id="msg_independent003", exchange_id="ex_independent",
            recipient="chatgpt"))
        result = inspect_pages(
            pages([comment(11, ping), comment(12, ack),
                   comment(13, independent)]),
            repository=REPO, issue=503, recipient="chatgpt", after_id=11,
        )
        self.assertEqual(
            [m["message_id"] for m in result["messages"]],
            ["msg_independent003"],
        )
        self.assertEqual(result["quarantined_exchanges"], [
            {"exchange_id": "ex_another", "reason": "CROSS_EXCHANGE_REPLY"}
        ])
        # The formerly valid root remains available to its intended recipient.
        roots = inspect_pages(
            pages([comment(11, ping), comment(12, ack),
                   comment(13, independent)]),
            repository=REPO, issue=503, recipient="claude-code")
        self.assertEqual([m["message_id"] for m in roots["messages"]],
                         ["msg_msg001"])

    def test_cursor_does_not_hide_conflicting_history(self):
        first = encode_comment(envelope())
        collision = envelope(text="mutated", message_id="msg_alt002")
        collision["idempotency_key"] = "kaep.test.msg_msg001"
        conflicting = encode_comment(collision)
        self.assert_blocked(pages([comment(11, first), comment(12, conflicting)]),
                            "IDEMPOTENCY_CONFLICT")

    def test_cursor_filters_only_new_messages(self):
        first = encode_comment(envelope())
        next_msg = encode_comment(envelope(message_id="msg_next002"))
        d = inspect_pages(pages([comment(11, first), comment(12, next_msg)]),
                          repository=REPO, issue=503, recipient="claude-code",
                          after_id=11)
        self.assertEqual([x["comment_id"] for x in d["messages"]], [12])

    def test_ordinary_comments_not_commands(self):
        d = inspect_pages(pages([comment(7, "please start the worker now!")]),
                          repository=REPO, issue=503, recipient="claude-code")
        self.assertEqual(d["messages"], [])
        self.assertEqual(d["observed_latest_comment_id"], 7)

    def test_wrong_issue_rejected(self):
        with self.assertRaisesRegex(InvalidMessage, "TASK_MISMATCH"):
            inspect_pages(pages([comment(11, encode_comment(envelope()))]),
                          repository=REPO, issue=504, recipient="claude-code")

    def test_malicious_kaep_wrapper_rejected(self):
        self.assert_blocked(pages([comment(11, "<!-- kaep:message:v0.2 -->\nnot json")]),
                            "INVALID_WRAPPER")

    def test_duplicate_comment_id(self):
        a = encode_comment(envelope())
        self.assert_blocked(pages([comment(11, a), comment(11, a)]),
                            "INVALID_COMMENT_SEQUENCE")

    def test_backwards_comment_ids(self):
        a = encode_comment(envelope())
        self.assert_blocked(pages([comment(12, a), comment(11, a)]),
                            "INVALID_COMMENT_SEQUENCE")

    def test_missing_github_actor(self):
        c = comment(11, encode_comment(envelope()))
        c["user"] = None
        self.assert_blocked(pages([c]), "MISSING_GITHUB_ACTOR")

    def test_incomplete_nonterminal_page(self):
        text = pages([comment(10, "one")], [comment(11, "two")])
        self.assert_blocked(text, "INCOMPLETE_PAGE")

    def test_invalid_page_shape(self):
        self.assert_blocked(json.dumps({"comments": []}), "INVALID_PAGES")

    def test_empty_page_chain(self):
        self.assert_blocked(pages([], []), "INCOMPLETE_PAGE")

    def test_duplicate_github_field(self):
        text = '[[{"id":11,"id":12,"body":"normal","user":{"login":"x"}}]]'
        self.assert_blocked(text, "DUPLICATE_GITHUB_FIELD")

    def test_oversized_pages(self):
        with self.assertRaisesRegex(InvalidMessage, "MAILBOX_TOO_LARGE"):
            parse_pages("x" * (MAX_RESPONSE_BYTES + 1), repository=REPO,
                        issue=503)

    def test_invalid_repository_target(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_TARGET"):
            parse_pages(pages([]), repository="bad/repo", issue=503)

    def test_invalid_recipient_and_cursor(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_FILTER"):
            inspect_pages(pages([]), repository=REPO, issue=503,
                          recipient="unknown")
        with self.assertRaisesRegex(InvalidMessage, "INVALID_FILTER"):
            inspect_pages(pages([]), repository=REPO, issue=503,
                          recipient="claude-code", after_id=True)

    @patch("tools.kaep_inbox_reader.subprocess.run")
    def test_gh_read_uses_only_get_and_pagination(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout=pages([]), stderr="")
        self.assertEqual(fetch_gh_pages(REPO, 503), pages([]))
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["gh", "api", "--paginate", "--slurp"])
        self.assertNotIn("POST", argv)
        self.assertIn("/repos/kinoko34077/devflow/issues/503/comments?per_page=100", argv)

    @patch("tools.kaep_inbox_reader.subprocess.run")
    def test_gh_denial_fails_closed_without_stderr(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="private-secret")
        with self.assertRaisesRegex(InvalidMessage, "^GITHUB_READ_FAILED$"):
            fetch_gh_pages(REPO, 503)

    @patch("tools.kaep_inbox_reader.subprocess.run")
    def test_gh_timeout_fails_closed(self, run):
        run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=30)
        with self.assertRaisesRegex(InvalidMessage, "^GITHUB_READ_UNAVAILABLE$"):
            fetch_gh_pages(REPO, 503)

    def test_offline_main_readonly_no_network(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "comments.json"
            f.write_text(pages([comment(11, encode_comment(envelope()))]),
                         encoding="utf-8")
            with patch("tools.kaep_inbox_reader.subprocess.run") as run:
                with patch("builtins.print") as output:
                    exitcode = main([
                        "--repository", REPO, "--issue", "503",
                        "--recipient", "claude-code", "--offline-pages", str(f)
                    ])
            self.assertEqual(exitcode, 0)
            run.assert_not_called()
            response = json.loads(output.call_args.args[0])
            self.assertEqual(response["messages"][0]["message_id"], "msg_msg001")
            self.assertNotIn("untrusted_payload_text", response["messages"][0])


if __name__ == "__main__":
    unittest.main()
