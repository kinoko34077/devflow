"""F8 one-Issue central sender guard tests; no Github mutation or messages."""
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout
from unittest.mock import patch
import io
import json
import tempfile
from pathlib import Path
import unittest

from tools.kaep_mailbox_codec import InvalidMessage
from tools.gpt_liveness_f8_sender import (
    ALLOWED_MAILBOX, require_exact_target, preview, dispatch, main,
)
from tools.gpt_liveness_fleet_plan import SCHEMA
from tools.gpt_liveness_pilot import MARKER, END, SCHEMA as LS, iso

REPO = "kinoko34077/devflow"
NOW = datetime(2026, 10, 15, 1, tzinfo=timezone.utc)


def manifest(targets=None):
    return json.dumps({"schema": SCHEMA,
                       "targets": [ALLOWED_MAILBOX] if targets is None else targets})


def issue(*, state="open", body=""):
    return {"repository": REPO, "number": 554, "state": state, "body": body}


def enrolled(*, enabled=True, long_until=None, expired=False):
    data = {
        "schema": LS, "session_id": "session_f8_554_test",
        "turn_id": "turn_f8_554_test",
        "started_at": iso(NOW - timedelta(minutes=60 if expired else 1)),
        "expires_at": iso(NOW - timedelta(minutes=5) if expired else NOW + timedelta(minutes=25)),
        "expected_actor": "kinoko34077", "enabled": enabled,
    }
    if long_until:
        data["long_running_until"] = long_until
    return MARKER + json.dumps(data) + END


class F8OneMailboxTests(unittest.TestCase):
    def test_wrong_target_is_rejected_before_any_mutation(self):
        for targets in ([], [REPO + "#519"], [ALLOWED_MAILBOX, REPO + "#519"],
                        ["kinoko34077/execution-coordinator#138"]):
            with self.subTest(targets=targets):
                with self.assertRaisesRegex(InvalidMessage, "F8_TARGET_NOT_AUTHORIZED"):
                    require_exact_target(manifest(targets))

    def test_closed_or_inactive_has_no_ping_candidate(self):
        for data in (issue(state="closed", body=enrolled()),
                     issue(body=""), issue(body=enrolled(enabled=False)),
                     issue(body=enrolled(expired=True))):
            result = preview(raw_manifest=manifest(), snapshot=data,
                             pages=None, now=NOW)
            self.assertEqual(result["target_count"], 1)
            self.assertFalse(result["targets"][0]["would_ping_if_authorized"])
            self.assertFalse(result["deployment_authorized"])
            self.assertFalse(result["claim_authority"])

    def test_active_pages_are_required_and_no_payload_leaks(self):
        with self.assertRaisesRegex(InvalidMessage, "ACTIVE_MAILBOX_REQUIRED"):
            preview(raw_manifest=manifest(), snapshot=issue(body=enrolled()),
                    pages=None, now=NOW)
        report = preview(raw_manifest=manifest(), snapshot=issue(body=enrolled()),
                         pages="[[]]", now=NOW)
        self.assertEqual(report["targets"][0]["dispatch_state"], "READY")
        self.assertTrue(report["targets"][0]["would_ping_if_authorized"])
        self.assertNotIn("nonce", json.dumps(report))
        self.assertNotIn("request_text", json.dumps(report))

    def test_inactive_cannot_smuggle_unverified_comment_pages(self):
        with self.assertRaisesRegex(InvalidMessage, "INACTIVE_MAILBOX_PAGES_FORBIDDEN"):
            preview(raw_manifest=manifest(), snapshot=issue(), pages="[[{}]]", now=NOW)

    def test_wrong_identity_duplicate_enrollment_blocked(self):
        forged = issue(body=enrolled())
        forged["number"] = 519
        with self.assertRaisesRegex(InvalidMessage, "ISSUE_IDENTITY_MISMATCH"):
            preview(raw_manifest=manifest(), snapshot=forged, pages="[[]]", now=NOW)
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_ENROLLMENT"):
            preview(raw_manifest=manifest(), snapshot=issue(body=enrolled() + enrolled()),
                    pages="[[]]", now=NOW)

    def test_long_running_suppressed(self):
        report = preview(raw_manifest=manifest(),
                         snapshot=issue(body=enrolled(long_until=iso(NOW + timedelta(minutes=5)))),
                         pages=None, now=NOW)
        self.assertEqual(report["targets"][0]["dispatch_state"], "LONG_RUNNING")
        suppressed = dispatch(report=report, want_send=True,
                              confirmed_mailbox=ALLOWED_MAILBOX,
                              sender=lambda _: self.fail("writer must not be called"))
        self.assertFalse(suppressed["post_attempted"])

    def test_disabled_gate_does_not_execute_writer(self):
        report = preview(raw_manifest=manifest(), snapshot=issue(), pages=None, now=NOW)
        x = dispatch(report=report, want_send=True, confirmed_mailbox=ALLOWED_MAILBOX,
                     sender=lambda _: self.fail("writer must not be called"))
        self.assertEqual(x["status"], "SUPPRESSED_BY_POLICY")

    def test_default_is_preview_only_not_an_action(self):
        report = preview(raw_manifest=manifest(), snapshot=issue(body=enrolled()),
                         pages="[[]]", now=NOW)
        x = dispatch(report=report, want_send=False, confirmed_mailbox=None,
                     sender=lambda _: self.fail("writer must not be called"))
        self.assertEqual(x["status"], "PREVIEW_ONLY")
        self.assertFalse(x["post_attempted"])

    def test_missing_explicit_write_confirmation_blocked(self):
        report = preview(raw_manifest=manifest(), snapshot=issue(body=enrolled()),
                         pages="[[]]", now=NOW)
        with self.assertRaisesRegex(InvalidMessage, "F8_SEND_CONFIRMATION_MISSING"):
            dispatch(report=report, want_send=True, confirmed_mailbox="wrong",
                     sender=lambda _: self.fail("no writer"))

    def test_verified_ready_only_delegates_once_to_existing_f4_sender(self):
        report = preview(raw_manifest=manifest(), snapshot=issue(body=enrolled()),
                         pages="[[]]", now=NOW)
        calls = []
        result = dispatch(report=report, want_send=True, confirmed_mailbox=ALLOWED_MAILBOX,
                          sender=lambda args: calls.append(args) or 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ["--repository", REPO, "--issue", "554", "--send"])
        self.assertEqual(result["status"], "F4_SENDER_EXECUTED")
        self.assertFalse(result["claim_authority"])
        self.assertFalse(result["gpt_currently_alive_proven"])

    def test_existing_f4_sender_failure_is_not_a_success(self):
        report = preview(raw_manifest=manifest(), snapshot=issue(body=enrolled()),
                         pages="[[]]", now=NOW)
        with self.assertRaisesRegex(InvalidMessage, "F4_POST_OR_READBACK_FAILED"):
            dispatch(report=report, want_send=True, confirmed_mailbox=ALLOWED_MAILBOX,
                     sender=lambda _: 2)

    def test_forged_preview_authority_never_reaches_sender(self):
        report = preview(raw_manifest=manifest(), snapshot=issue(body=enrolled()),
                         pages="[[]]", now=NOW)
        report["deployment_authorized"] = True
        with self.assertRaisesRegex(InvalidMessage, "PREVIEW_AUTHORITY_MISMATCH"):
            dispatch(report=report, want_send=True, confirmed_mailbox=ALLOWED_MAILBOX,
                     sender=lambda _: self.fail("forged status"))

    def test_cli_closed_mailbox_calls_no_gh_comment_or_sender(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d, "allowlist.json")
            file.write_text(manifest(), encoding="utf-8")
            with patch("tools.gpt_liveness_f8_sender.fetch_owning_issue",
                       return_value=issue(state="open",body="")), \
                 patch("tools.gpt_liveness_f8_sender.fetch_gh_pages") as comments, \
                 patch("tools.gpt_liveness_f8_sender.single_target_pilot_main") as sender, \
                 redirect_stdout(io.StringIO()) as output:
                code = main(["--manifest", str(file)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "PREVIEW_ONLY")
            comments.assert_not_called()
            sender.assert_not_called()

    def test_cli_manual_confirmation_rejects_before_github_reads(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d, "allowlist.json")
            file.write_text(manifest(), encoding="utf-8")
            with patch("tools.gpt_liveness_f8_sender.fetch_owning_issue") as get, \
                 redirect_stdout(io.StringIO()) as output:
                code = main(["--manifest", str(file), "--send"])
            self.assertEqual(code, 2)
            self.assertIn("F8_SEND_CONFIRMATION_MISSING", output.getvalue())
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
