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
from tools.kaep_mailbox_codec import encode_comment
from tools.kaep_request_sender import make_request
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


def staged_call(**options):
    """Mock only the external index preflight for legacy writer-state cases."""
    with patch("tools.kaep_send_with_discovery._discovery_read_preflight"):
        return publish_source_and_route(**options)


def indexed_page(*, trailing_newline=False):
    index, existing = make_request(
        json.dumps([[]]), repository="kinoko34077/devflow", issue=503,
        recipient="claude-code", intent="REPORT",
        request_key="kaep.discovery.preflight.fixture",
        request_text="stable benign marker",
        expect_existing_actor=ACTOR,
    )
    assert existing is None
    wire = encode_comment(index) + ("\n" if trailing_newline else "")
    return json.dumps([[{"id": 41, "body": wire, "user": {"login": ACTOR}}]])


class TwoPhaseSourceRouteTests(unittest.TestCase):
    def test_live_style_malformed_index_blocks_before_any_source_post(self):
        with patch("tools.kaep_send_with_discovery.fetch_gh_pages",
                   return_value=indexed_page(trailing_newline=True)) as reader, patch(
                "tools.kaep_send_with_discovery.verify_public_source") as public, patch(
                "tools.kaep_send_with_discovery.send_request") as source_writer, patch(
                "tools.kaep_send_with_discovery.route_request") as route_writer:
            out = publish_source_and_route(**args(do_send=True))
        public.assert_called_once_with(REPO)
        reader.assert_called_once_with("kinoko34077/devflow", 503)
        self.assertEqual(out["status"], "DISCOVERY_PREFLIGHT_BLOCKED")
        self.assertEqual(out["reason_code"], "INVALID_WRAPPER")
        self.assertFalse(out["delivery_confirmed"])
        source_writer.assert_not_called()
        route_writer.assert_not_called()

    def test_live_style_valid_index_allows_reusing_existing_writers(self):
        with patch("tools.kaep_send_with_discovery.fetch_gh_pages",
                   return_value=indexed_page()), patch(
                "tools.kaep_send_with_discovery.verify_public_source"), patch(
                "tools.kaep_send_with_discovery.send_request",
                return_value=source()) as writer, patch(
                "tools.kaep_send_with_discovery.route_request",
                return_value=pointer()) as notice:
            out = publish_source_and_route(**args(do_send=True))
        self.assertEqual(out["status"], "SOURCE_AND_POINTER_READBACK")
        writer.assert_called_once()
        notice.assert_called_once()

    def test_index_transport_failure_stops_original_before_post(self):
        with patch("tools.kaep_send_with_discovery.fetch_gh_pages",
                   side_effect=OSError("do not expose connection details")), patch(
                "tools.kaep_send_with_discovery.verify_public_source"), patch(
                "tools.kaep_send_with_discovery.send_request") as writer, patch(
                "tools.kaep_send_with_discovery.route_request") as notice:
            out = publish_source_and_route(**args(do_send=True))
        self.assertEqual(out["status"], "DISCOVERY_PREFLIGHT_BLOCKED")
        self.assertEqual(out["reason_code"], "DISCOVERY_READ_UNAVAILABLE")
        self.assertNotIn("connection details", json.dumps(out))
        writer.assert_not_called()
        notice.assert_not_called()

    def test_approved_789_uses_clean_index_not_malformed_503(self):
        with patch("tools.kaep_send_with_discovery.verify_public_source") as visibility, patch(
                "tools.kaep_send_with_discovery.fetch_gh_pages",
                return_value=json.dumps([[]])) as fetch, patch(
                "tools.kaep_send_with_discovery.send_request",
                return_value=source()) as sender, patch(
                "tools.kaep_send_with_discovery.route_request",
                return_value=pointer()) as route:
            out = publish_source_and_route(**args(do_send=True, discovery_issue=789))
        visibility.assert_called_once_with(REPO)
        fetch.assert_called_once_with("kinoko34077/devflow", 789)
        self.assertEqual(out["status"], "SOURCE_AND_POINTER_READBACK")
        self.assertEqual(out["discovery_issue"], "kinoko34077/devflow#789")
        self.assertEqual(route.call_args.kwargs["discovery_issue"], 789)
        self.assertTrue(sender.call_args.kwargs["do_send"])
        self.assertFalse(out["delivery_confirmed"])
        self.assertFalse(out["recipient_pickup_proven"])

    def test_malformed_789_preflight_stops_before_source_post(self):
        malformed = "<!-- kaep:message:v0.2 -->" + "\n" + chr(96) * 3 + "json" + "\n{}\n" + chr(96) * 3 + "\n"
        blob = json.dumps([[{"id": 55, "body": malformed, "user": {"login": ACTOR}}]])
        with patch("tools.kaep_send_with_discovery.verify_public_source"), patch(
                "tools.kaep_send_with_discovery.fetch_gh_pages",
                return_value=blob) as fetch, patch(
                "tools.kaep_send_with_discovery.send_request") as sender, patch(
                "tools.kaep_send_with_discovery.route_request") as route:
            out = publish_source_and_route(**args(do_send=True, discovery_issue=789))
        self.assertEqual(out["status"], "DISCOVERY_PREFLIGHT_BLOCKED")
        self.assertEqual(out["reason_code"], "INVALID_WRAPPER")
        fetch.assert_called_once_with("kinoko34077/devflow", 789)
        sender.assert_not_called()
        route.assert_not_called()

    def test_unapproved_target_and_successor_source_loop_prevent_writes(self):
        for value in (True, 0, 9001, "789"):
            with self.subTest(value=value), patch(
                    "tools.kaep_send_with_discovery.verify_public_source") as visibility, patch(
                    "tools.kaep_send_with_discovery.send_request") as sender:
                with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_INDEX_NOT_APPROVED"):
                    publish_source_and_route(**args(do_send=True, discovery_issue=value))
                visibility.assert_not_called()
                sender.assert_not_called()
        with patch("tools.kaep_send_with_discovery.verify_public_source") as visibility, patch(
                "tools.kaep_send_with_discovery.send_request") as sender:
            with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_LOOP"):
                publish_source_and_route(**args(repository="kinoko34077/devflow", issue=789,
                                                 do_send=True, discovery_issue=789))
            visibility.assert_not_called()
            sender.assert_not_called()

    def test_fresh_dry_run_only_prepares_source_and_never_routes(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   return_value=source("PREPARED", None)) as send, patch(
                "tools.kaep_send_with_discovery.route_request") as route, patch(
                "tools.kaep_send_with_discovery.verify_public_source") as visibility:
            out = staged_call(**args())
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
            out = staged_call(**args(do_send=True))
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
            out = staged_call(**args(do_send=True))
        self.assertEqual(out["status"], "SOURCE_AND_POINTER_READBACK")
        self.assertEqual(route.call_args.kwargs["message_id"], MESSAGE_ID)

    def test_source_readback_but_route_failed_is_recoverable_partial(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   return_value=source()), patch(
                "tools.kaep_send_with_discovery.route_request",
                side_effect=InvalidMessage("SOURCE_MAILBOX_UNAVAILABLE")) as route, patch(
                "tools.kaep_send_with_discovery.verify_public_source"):
            out = staged_call(**args(do_send=True))
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
            out = staged_call(**args(do_send=True))
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
                staged_call(**args(do_send=True))
        send.assert_not_called()
        route.assert_not_called()

    def test_discovery_mailbox_source_rejected_before_original_post(self):
        # Codex review P2: source #503 can never be routed to itself.
        for do_send in (False, True):
            with self.subTest(do_send=do_send), patch(
                    "tools.kaep_send_with_discovery.verify_public_source") as visibility, patch(
                    "tools.kaep_send_with_discovery.send_request") as send, patch(
                    "tools.kaep_send_with_discovery.route_request") as route:
                with self.assertRaisesRegex(InvalidMessage, "DISCOVERY_LOOP"):
                    staged_call(**args(
                        repository="kinoko34077/devflow", issue=503,
                        do_send=do_send,
                    ))
                visibility.assert_not_called()
                send.assert_not_called()
                route.assert_not_called()

    def test_invalid_notice_actor_rejected_before_original_post(self):
        with patch("tools.kaep_send_with_discovery.verify_public_source") as visibility, patch(
                "tools.kaep_send_with_discovery.send_request") as send, patch(
                "tools.kaep_send_with_discovery.route_request") as route:
            with self.assertRaisesRegex(InvalidMessage, "INVALID_ACTOR"):
                staged_call(**args(
                    expected_notice_actor="untrusted ⚠️", do_send=True,
                ))
            visibility.assert_not_called()
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
                out = staged_call(**args(do_send=True))
                self.assertEqual(out["status"], "SOURCE_NOT_VERIFIED")
                route.assert_not_called()

    def test_invalid_pointer_receipt_cannot_be_success(self):
        with patch("tools.kaep_send_with_discovery.send_request",
                   return_value=source()), patch(
                "tools.kaep_send_with_discovery.route_request",
                return_value=pointer("SENT_AND_READ_BACK", cid=None)), patch(
                "tools.kaep_send_with_discovery.verify_public_source"):
            out = staged_call(**args(do_send=True))
        self.assertEqual(out["status"], "SOURCE_STORED_ROUTE_UNVERIFIED")
        self.assertEqual(out["reason_code"], "INVALID_ROUTE_RECEIPT")

    def test_explicit_route_intent_and_offline_write_gates(self):
        with self.assertRaisesRegex(InvalidMessage, "ROUTE_UNSUPPORTED_INTENT"):
            staged_call(**args(intent="TEST"))
        with self.assertRaisesRegex(InvalidMessage, "OFFLINE_POST_FORBIDDEN"):
            staged_call(**args(
                do_send=True, offline_source_pages="[]",
                offline_discovery_pages="[]",
            ))
        with self.assertRaisesRegex(InvalidMessage, "INCOMPLETE_OFFLINE_FIXTURE"):
            staged_call(**args(offline_source_pages="[]"))

    def test_cli_dry_run_does_not_activate_source_or_route_write(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "request.txt"
            path.write_text("test-only safe text", encoding="utf-8")
            with patch("tools.kaep_send_with_discovery._discovery_read_preflight"), patch("tools.kaep_send_with_discovery.send_request",
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
