"""Two-phase KAEP producer receipt: no false discovery, delivery or retry."""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from tools.kaep_inbox_reader import InvalidMessage
from tools.kaep_send_with_discovery import publish_source_and_route, main

REPO = "kinoko34077/devflow"
ACTOR = "kinoko34077"
KEY = "kaep.source.route.test.stable-key"
MESSAGE_ID = "msg_0123456789abcdef0123456789abcdef"


def args(**updates):
    options = dict(
        repository=REPO, issue=726, intent="ANALYZE",
        request_key=KEY, request_text="private request text",
        expected_source_actor=ACTOR,
        expected_notice_actor=ACTOR,
    )
    options.update(updates)
    return options


def source(status="SENT_AND_READ_BACK", cid=101):
    return {
        "status": status, "posted_comment_id": cid,
        "message_id": MESSAGE_ID,
    }


def pointer(status="SENT_AND_READ_BACK", cid=301):
    return {
        "status": status, "discovery_comment_id": cid,
        "source_message_id": MESSAGE_ID,
        "source_comment_id": 101,
    }


class TwoPhaseSourceRouteTests(unittest.TestCase):
    def test_fresh_dry_run_only_prepares_source_and_never_routes(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   return_value=source("PREPARED", None)) as send, patch(
                "tools.kaep_send_with_discovery.route_request") as route, patch(
                "tools.kaep_send_with_discovery.verify_public_source") as visibility:
            out = publish_source_and_route(**args())
        self.assertEqual(out["status"], "SOURCE_PREPARED_ONLY")
        self.assertIsNone(out["discovery_comment_id"])
        self.assertFalse(out["delivery_confirmed"])
        self.assertFalse(out["can_authorize_execution"])
        route.assert_not_called()
        visibility.assert_not_called()
        self.assertFalse(send.call_args.kwargs["do_send"])

    def test_source_and_pointer_readbacks_not_model_pickup(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   return_value=source()), patch(
                "tools.kaep_send_with_discovery.route_request",
                return_value=pointer()) as route, patch(
                "tools.kaep_send_with_discovery.verify_public_source") as visibility:
            out = publish_source_and_route(**args(do_send=True))
        visibility.assert_called_once_with(REPO)
        self.assertTrue(route.call_args.kwargs["do_send"])
        self.assertEqual(out["status"], "SOURCE_AND_POINTER_READBACK")
        self.assertEqual(out["source_comment_id"], 101)
        self.assertEqual(out["discovery_comment_id"], 301)
        self.assertFalse(out["delivery_confirmed"])
        self.assertFalse(out["recipient_pickup_proven"])
        self.assertFalse(out["agent_woken"])
        self.assertFalse(out["source_universe_complete"])
        self.assertFalse(out["fallback_retirement_authorized"])
        self.assertTrue(out["has_unknown_work"])
        self.assertNotIn("private request text", json.dumps(out))

    def test_retry_with_existing_source_uses_stable_message_and_no_repost(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   return_value=source("ALREADY_SENT")), patch(
                "tools.kaep_send_with_discovery.route_request",
                return_value=pointer("ALREADY_SENT")) as route, patch(
                "tools.kaep_send_with_discovery.verify_public_source"):
            out = publish_source_and_route(**args(do_send=True))
        self.assertEqual(out["status"], "SOURCE_AND_POINTER_READBACK")
        self.assertEqual(route.call_args.kwargs["message_id"], MESSAGE_ID)

    def test_source_readback_but_route_failed_is_recoverable_partial(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   return_value=source()), patch(
                "tools.kaep_send_with_discovery.route_request",
                side_effect=InvalidMessage("SOURCE_MAILBOX_UNAVAILABLE")) as route, patch(
                "tools.kaep_send_with_discovery.verify_public_source"):
            out = publish_source_and_route(**args(do_send=True))
        self.assertEqual(route.call_count, 1)
        self.assertEqual(out["status"], "SOURCE_STORED_ROUTE_UNVERIFIED")
        self.assertEqual(out["source_comment_id"], 101)
        self.assertIsNone(out["discovery_comment_id"])
        self.assertEqual(out["reason_code"], "ROUTE_POST_OR_READBACK_UNVERIFIED")
        self.assertFalse(out["delivery_confirmed"])

    def test_unknown_source_write_must_not_attempt_route(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   side_effect=OSError("sensitive network failure")), patch(
                "tools.kaep_send_with_discovery.route_request") as route, patch(
                "tools.kaep_send_with_discovery.verify_public_source"):
            out = publish_source_and_route(**args(do_send=True))
        self.assertEqual(out["status"], "SOURCE_NOT_VERIFIED")
        self.assertEqual(out["reason_code"], "SOURCE_POST_OR_READBACK_UNVERIFIED")
        self.assertNotIn("sensitive", json.dumps(out))
        route.assert_not_called()

    def test_private_source_is_rejected_before_any_write(self):
        with patch("tools.kaep_send_with_discovery.verify_public_source",
                   side_effect=InvalidMessage("SOURCE_NOT_PUBLIC")), patch(
                "tools.kaep_send_with_discovery.send_request") as send, patch(
                "tools.kaep_send_with_discovery.route_request") as route:
            with self.assertRaisesRegex(InvalidMessage, "SOURCE_NOT_PUBLIC"):
                publish_source_and_route(**args(do_send=True))
        send.assert_not_called()
        route.assert_not_called()

    def test_missing_or_invalid_source_receipt_prevents_pointer(self):
        for result in (source("SENT_AND_READ_BACK", None),
                       source("UNKNOWN", 101)):
            with self.subTest(result=result), patch(
                    "tools.kaep_send_with_discovery.send_request",
                    return_value=result), patch(
                    "tools.kaep_send_with_discovery.route_request") as route, patch(
                    "tools.kaep_send_with_discovery.verify_public_source"):
                out = publish_source_and_route(**args(do_send=True))
                self.assertEqual(out["status"], "SOURCE_NOT_VERIFIED")
                route.assert_not_called()

    def test_invalid_pointer_receipt_cannot_be_success(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   return_value=source()), patch(
                "tools.kaep_send_with_discovery.route_request",
                return_value=pointer("SENT_AND_READ_BACK", cid=None)), patch(
                "tools.kaep_send_with_discovery.verify_public_source"):
            out = publish_source_and_route(**args(do_send=True))
        self.assertEqual(out["status"], "SOURCE_STORED_ROUTE_UNVERIFIED")
        self.assertEqual(out["reason_code"], "INVALID_ROUTE_RECEIPT")

    def test_explicit_route_intent_and_offline_write_gates(self):
        with self.assertRaisesRegex(InvalidMessage, "ROUTE_UNSUPPORTED_INTENT"):
            publish_source_and_route(**args(intent="TEST"))
        with self.assertRaisesRegex(InvalidMessage, "OFFLINE_POST_FORBIDDEN"):
            publish_source_and_route(**args(
                do_send=True, offline_source_pages="[]",
                offline_discovery_pages="[]",
            ))
        with self.assertRaisesRegex(InvalidMessage, "INCOMPLETE_OFFLINE_FIXTURE"):
            publish_source_and_route(**args(offline_source_pages="[]"))

    def test_cli_dry_run_does_not_activate_source_or_route_write(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "request.txt"
            path.write_text("test-only safe text", encoding="utf-8")
            with patch("tools.kaep_send_with_discovery.send_request",
                       return_value=source("PREPARED", None)) as send, patch(
                    "tools.kaep_send_with_discovery.route_request") as route, redirect_stdout(io.StringIO()) as out:
                result = main([
                    "--repository", REPO, "--issue", "726",
                    "--intent", "ANALYZE",
                    "--request-key", KEY,
                    "--text-file", str(path),
                    "--expect-source-actor", ACTOR,
                    "--expect-notice-actor", ACTOR,
                ])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(out.getvalue())["status"], "SOURCE_PREPARED_ONLY")
        self.assertFalse(send.call_args.kwargs["do_send"])
        route.assert_not_called()


if __name__ == "__main__":
    unittest.main()
