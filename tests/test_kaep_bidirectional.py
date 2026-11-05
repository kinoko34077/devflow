"""KAEP M1 offline cross-module round trips; genuine Claude E2E remains untested."""
from __future__ import annotations

import json
import unittest

from tools.kaep_mailbox_codec import encode_comment
from tools.kaep_inbox_reader import inspect_pages
from tools.kaep_reply_sender import make_reply, FIXED_ACK
from tools.kaep_request_sender import make_request

REPO = "kinoko34077/devflow"
ISSUE = 503


def pages(messages):
    return json.dumps([[
        {"id": i + 10, "body": encode_comment(m),
         "user": {"login": "kinoko34077", "id": 79015263}}
        for i, m in enumerate(messages)
    ]], ensure_ascii=False)


class KAEPTwoWayOfflineTests(unittest.TestCase):
    def _exchange(self, *, recipient, reply_recipient, key):
        root, already = make_request(
            pages([]), repository=REPO, issue=ISSUE,
            recipient=recipient, intent="ANALYZE", request_key=key,
            request_text="Offline read-only analysis task",
            expect_existing_actor="kinoko34077",
        )
        self.assertIsNone(already)
        inbox = inspect_pages(
            pages([root]), repository=REPO, issue=ISSUE,
            recipient=recipient,
        )
        self.assertEqual(len(inbox["messages"]), 1)
        self.assertFalse(inbox["messages"][0]["provider_identity_verified"])
        ack, _ = make_reply(
            pages([root]), repository=REPO, issue=ISSUE,
            parent_message_id=root["message_id"],
            kind="ACK", response_text=FIXED_ACK, expect_actor="kinoko34077",
            parent_recipient=recipient, reply_recipient=reply_recipient,
        )
        answer, _ = make_reply(
            pages([root, ack]), repository=REPO, issue=ISSUE,
            parent_message_id=root["message_id"],
            kind="ANSWER", response_text="Verified offline response",
            expect_actor="kinoko34077",
            parent_recipient=recipient, reply_recipient=reply_recipient,
        )
        inbox_reply = inspect_pages(
            pages([root, ack, answer]), repository=REPO, issue=ISSUE,
            recipient=reply_recipient,
        )
        self.assertEqual(
            [m["kind"] for m in inbox_reply["messages"]],
            ["ACK", "ANSWER"],
        )
        self.assertEqual(
            {m["in_reply_to"] for m in inbox_reply["messages"]},
            {root["message_id"]},
        )
        self.assertFalse(inbox_reply["claim_or_agent_execution_proven"])

    def test_claude_request_gpt_reply(self):
        self._exchange(
            recipient="chatgpt", reply_recipient="claude-code",
            key="kaep.m1.test.reverse.0001",
        )

    def test_gpt_request_claude_reply(self):
        self._exchange(
            recipient="claude-code", reply_recipient="chatgpt",
            key="kaep.m1.test.forward.0001",
        )

    def test_codex_request_chatgpt_reply(self):
        self._exchange(
            recipient="codex", reply_recipient="chatgpt",
            key="kaep.m1.test.codex.0001",
        )


if __name__ == "__main__":
    unittest.main()
