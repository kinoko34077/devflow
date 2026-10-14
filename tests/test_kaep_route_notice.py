"""A2 pointer-only KAEP discovery tests; no GitHub write or agent wake."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools.kaep_mailbox_codec import encode_comment, InvalidMessage
from tools.kaep_request_sender import make_request
from tools.kaep_route_notice import (
    DISCOVERY_REPOSITORY, DISCOVERY_ISSUE, POINTER_VERSION,
    verify_source_request, route_request,
)

REPO = "kinoko34077/UniverseGenome"
ISSUE = 336
HEAD = "a" * 40
ACTOR = "kinoko34077"
KEY = "kaep.discovery.test.parent0001"


def pages(*groups):
    return json.dumps(list(groups))


def comment(cid, msg, actor=ACTOR):
    return {"id": cid, "body": encode_comment(msg), "user": {"login": actor}}


def root_request():
    root, existing = make_request(
        pages([]), repository=REPO, issue=ISSUE, recipient="claude-code",
        intent="ANALYZE", request_key=KEY, request_text="Confidential payload must not be copied",
        expected_head=HEAD, expect_existing_actor=ACTOR,
    )
    assert existing is None
    return root


def route_kwargs(root):
    return dict(
        repository=REPO, issue=ISSUE, message_id=root["message_id"],
        expected_source_actor=ACTOR, expected_notice_actor=ACTOR,
        offline_source_pages=pages([comment(67, root)]),
        offline_discovery_pages=pages([]),
    )


class DiscoveryNoticeTests(unittest.TestCase):
    def test_source_pointer_contains_no_request_payload(self):
        root = root_request()
        ptr = verify_source_request(
            pages([comment(67, root)]), repository=REPO, issue=ISSUE,
            message_id=root["message_id"], expected_actor=ACTOR)
        self.assertEqual(ptr["type"], POINTER_VERSION)
        self.assertEqual(ptr["owning_issue"], "https://github.com/" + REPO + "/issues/336")
        self.assertEqual(ptr["comment_id"], 67)
        self.assertNotIn("Confidential payload", json.dumps(ptr))
        self.assertNotIn("expected_head", ptr)

    def test_qualified_pointer_sends_existing_readonly_route(self):
        root = root_request()
        with patch("tools.kaep_route_notice.send_request",
                   return_value={"status": "PREPARED", "posted_comment_id": None}) as send:
            result = route_request(**route_kwargs(root))
        self.assertEqual(result["status"], "PREPARED")
        self.assertFalse(result["agent_woken"])
        self.assertFalse(result["delivery_confirmed"])
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["repository"], DISCOVERY_REPOSITORY)
        self.assertEqual(kwargs["issue"], DISCOVERY_ISSUE)
        self.assertEqual(kwargs["recipient"], "claude-code")
        self.assertEqual(kwargs["intent"], "REPORT")
        self.assertFalse(kwargs["do_send"])
        self.assertIsNone(kwargs["expected_head"])
        self.assertEqual(kwargs["request_key"], "kaep.discovery." + root["message_id"])
        self.assertEqual(json.loads(kwargs["request_text"])["comment_id"], 67)

    def test_route_dedup_key_is_stable(self):
        root = root_request()
        with patch("tools.kaep_route_notice.send_request",
                   return_value={"status": "ALREADY_SENT", "posted_comment_id": 90}) as send:
            a = route_request(**route_kwargs(root))
            b = route_request(**route_kwargs(root))
        self.assertEqual(a["discovery_comment_id"], 90)
        self.assertEqual(a, b)
        self.assertEqual(send.call_count, 2)

    def test_offline_fixture_cannot_send(self):
        root = root_request()
        with self.assertRaisesRegex(InvalidMessage, "OFFLINE_POST_FORBIDDEN"):
            route_request(**route_kwargs(root), do_send=True)

    def test_unmatched_partial_fixture_fails_closed(self):
        root = root_request()
        kw = route_kwargs(root)
        kw["offline_discovery_pages"] = None
        with self.assertRaisesRegex(InvalidMessage, "INCOMPLETE_OFFLINE_FIXTURE"):
            route_request(**kw)

    def test_missing_source_root_rejected(self):
        root = root_request()
        with self.assertRaisesRegex(InvalidMessage, "SOURCE_MESSAGE_NOT_UNIQUE"):
            verify_source_request(
                pages([]), repository=REPO, issue=ISSUE,
                message_id=root["message_id"], expected_actor=ACTOR)

    def test_source_actor_mismatch_rejected(self):
        root = root_request()
        with self.assertRaisesRegex(InvalidMessage, "SOURCE_ACTOR_MISMATCH"):
            verify_source_request(
                pages([comment(67, root, actor="someone-else")]),
                repository=REPO, issue=ISSUE,
                message_id=root["message_id"], expected_actor=ACTOR)

    def test_conflicting_duplicate_message_ids_fail_closed(self):
        root = root_request()
        modified = dict(root)
        modified["payload"] = {"text": "different original request content"}
        with self.assertRaises(InvalidMessage):
            verify_source_request(
                pages([comment(67, root), comment(68, modified)]),
                repository=REPO, issue=ISSUE,
                message_id=root["message_id"], expected_actor=ACTOR)

    def test_identical_replay_is_deduplicated_by_existing_codec(self):
        root = root_request()
        verified = verify_source_request(
            pages([comment(67, root), comment(68, root)]),
            repository=REPO, issue=ISSUE,
            message_id=root["message_id"], expected_actor=ACTOR)
        self.assertEqual(verified["message_id"], root["message_id"])

    def test_reject_wrong_recipient_or_write_intent(self):
        root = root_request()
        for field, value in (("recipient", "chatgpt"), ("intent", "PING")):
            mutated = dict(root)
            mutated[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(InvalidMessage, "SOURCE_NOT_SUPPORTED_REQUEST"):
                    verify_source_request(
                        pages([comment(67, mutated)]), repository=REPO, issue=ISSUE,
                        message_id=root["message_id"], expected_actor=ACTOR)
        mutated = dict(root)
        mutated["scope"] = dict(root["scope"], effect="WRITE_INTENT")
        with self.assertRaisesRegex(InvalidMessage, "SOURCE_NOT_SUPPORTED_REQUEST"):
            verify_source_request(
                pages([comment(67, mutated)]), repository=REPO, issue=ISSUE,
                message_id=root["message_id"], expected_actor=ACTOR)

    def test_invalid_message_id_and_self_routing(self):
        root = root_request()
        with self.assertRaisesRegex(InvalidMessage, "INVALID_MESSAGE_ID"):
            verify_source_request(
                pages([]), repository=REPO, issue=ISSUE,
                message_id="bad", expected_actor=ACTOR)
        with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_LOOP"):
            verify_source_request(
                pages([]), repository=DISCOVERY_REPOSITORY, issue=DISCOVERY_ISSUE,
                message_id=root["message_id"], expected_actor=ACTOR)

    def test_private_source_blocks_send_before_any_post(self):
        root = root_request()
        with patch("tools.kaep_route_notice.verify_public_source",
                   side_effect=InvalidMessage("SOURCE_NOT_PUBLIC")):
            with patch("tools.kaep_route_notice.send_request") as post:
                with self.assertRaisesRegex(InvalidMessage, "SOURCE_NOT_PUBLIC"):
                    route_request(
                        repository=REPO, issue=ISSUE,
                        message_id=root["message_id"],
                        expected_source_actor=ACTOR,
                        expected_notice_actor=ACTOR, do_send=True)
                post.assert_not_called()

    def test_live_public_visibility_requires_verified_github_metadata(self):
        import subprocess
        from tools.kaep_route_notice import verify_public_source
        def proc(meta, rc=0):
            return subprocess.CompletedProcess(args=[], returncode=rc,
                                               stdout=json.dumps(meta), stderr="")
        with patch("tools.kaep_route_notice.subprocess.run",
                   return_value=proc({"full_name": REPO, "private": False})):
            self.assertIsNone(verify_public_source(REPO))
        for meta in ({"full_name": REPO, "private": True},
                     {"full_name": REPO},
                     {"full_name": "kinoko34077/other", "private": False}):
            with self.subTest(meta=meta):
                with patch("tools.kaep_route_notice.subprocess.run",
                           return_value=proc(meta)):
                    with self.assertRaises(InvalidMessage):
                        verify_public_source(REPO)

    def test_live_send_needs_genuine_source_read(self):
        root = root_request()
        source = pages([comment(67, root)])
        with patch("tools.kaep_route_notice.verify_public_source") as visibility:
            with patch("tools.kaep_route_notice.fetch_gh_pages", return_value=source) as read:
                with patch("tools.kaep_route_notice.send_request",
                           return_value={"status": "SENT_AND_READ_BACK",
                                         "posted_comment_id": 90}) as send:
                    result = route_request(
                        repository=REPO, issue=ISSUE, message_id=root["message_id"],
                        expected_source_actor=ACTOR, expected_notice_actor=ACTOR,
                        do_send=True)
        visibility.assert_called_once_with(REPO)
        read.assert_called_once_with(REPO, ISSUE)
        self.assertTrue(send.call_args.kwargs["do_send"])
        self.assertEqual(result["status"], "SENT_AND_READ_BACK")
        self.assertFalse(result["agent_woken"])


if __name__ == "__main__":
    unittest.main()
