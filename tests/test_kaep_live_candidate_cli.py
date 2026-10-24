"""B6-D actual published candidate locator -> canonical live original GET checks."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import unittest
from unittest import mock

from tools.kaep_live_candidate_cli import (
    read_live_candidate_cohort, validate_index, fetch_public_json, _unique_pairs,
)
from tools.kaep_mailbox_codec import encode_comment
from tools.kaep_request_sender import make_request

REPO = "kinoko34077/devflow"
NOW = datetime(2026, 10, 17, 5, 0, tzinfo=timezone.utc)


def root(*, number=1, issue=576, recipient="claude-code"):
    obj, _ = make_request(
        json.dumps([[]]), repository=REPO, issue=issue, recipient=recipient,
        intent="ANALYZE", expected_head="a" * 40,
        request_key=f"live.candidate.test.{number}.{issue}",
        request_text="private test-only prompt must never appear in public results",
        expect_existing_actor="kinoko34077",
    )
    return obj


def issue_object(n=576, state="open"):
    return {
        "number": n, "state": state,
        "html_url": f"https://github.com/{REPO}/issues/{n}",
        "title": "[SPEC] Non-TASK historical root", "body": "No metadata",
        "created_at": "2026-10-16T00:00:00Z", "updated_at": "2026-10-16T00:00:00Z",
        "author_association": "OWNER",
        "user": {"id": 79015263, "login": "kinoko34077"},
    }


def source_page(*elements):
    return json.dumps([[{"id": n, "body": encode_comment(msg),
                         "user": {"id": 79015263 if actor == "kinoko34077" else 123456789,
                                  "login": actor}}
                        for n, msg, actor in elements]])


def index_with(*elements, age_seconds=120, status="BOUNDED_SEARCH_READ"):
    return {
        "schema_version": "kaep.public-source-index.v1",
        "kind": "NON_AUTHORITATIVE_CANDIDATE_SNAPSHOT",
        "status": status, "observed_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "repositories": [REPO],
        "rows": [
            {
                "repository": REPO, "issue_number": issue,
                "issue_url": f"https://github.com/{REPO}/issues/{issue}",
                "source_comment_id": cid,
                "source_url": f"https://github.com/{REPO}/issues/{issue}#issuecomment-{cid}",
                "recipient": msg["recipient"], "message_id": msg["message_id"],
            } for issue, cid, msg in elements
        ],
        "has_unknown_work": True, "complete_source_universe": False,
        "can_authorize_execution": False, "fallback_retirement_authorized": False,
        "requires_live_original_issue_revalidation": True,
    }


class LiveCandidateTests(unittest.TestCase):
    def audit(self, snapshot, sources, *, recipient="claude-code"):
        calls = []
        def get_issue(repo, number):
            calls.append(("issue", repo, number))
            return issue_object(number)
        def get_comments(repo, number):
            calls.append(("comments", repo, number))
            return sources[(repo, number)]
        return read_live_candidate_cohort(
            snapshot, recipient=recipient,
            fetch_live_issue=get_issue, fetch_live_comments=get_comments,
            now=NOW,
        ), calls

    def test_real_576_style_public_candidate_get_then_live_original(self):
        old = root()
        old["message_id"] = "msg_cursor576_readonly_audit_20261015a"
        old["exchange_id"] = "ex_cursor576_readonly_audit_20261015a"
        snap = index_with((576, 6193914061, old))
        out, calls = self.audit(snap, {(REPO, 576): source_page(
            (6193914061, old, "kinoko34077"))})
        self.assertEqual(out["status"], "BOUNDED_LIVE_CANDIDATE_READ")
        self.assertEqual(calls, [("issue", REPO, 576), ("comments", REPO, 576)])
        self.assertEqual(out["candidate_issues"], 1)
        self.assertEqual(out["live_original_roots"], 1)
        self.assertEqual(out["index_rows_not_verified_live"], 0)
        self.assertEqual(out["new_in_live_originals"], 0)
        self.assertEqual(out["live_rows"][0]["index_presence"], "INDEXED_AND_LIVE")
        self.assertEqual(out["live_rows"][0]["source_comment_id"], 6193914061)
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["complete_source_universe"])
        self.assertFalse(out["can_authorize_execution"])
        self.assertFalse(out["recipient_pickup_proven"])
        self.assertFalse(out["fallback_retirement_authorized"])
        self.assertNotIn("private test-only prompt", json.dumps(out))

    def test_new_request_in_known_original_is_visible_without_issue_search(self):
        old, new = root(number=2), root(number=3)
        snap = index_with((576, 100, old), age_seconds=7200)
        out, calls = self.audit(snap, {(REPO, 576): source_page(
            (100, old, "kinoko34077"), (105, new, "kinoko34077"))})
        self.assertEqual(len(calls), 2)
        self.assertTrue(out["snapshot_stale"])
        self.assertEqual(out["new_in_live_originals"], 1)
        self.assertEqual(out["live_original_roots"], 2)
        self.assertEqual(out["live_rows"][1]["index_presence"], "LIVE_ORIGINAL_ONLY")
        self.assertFalse(out["current_head_verified"])

    def test_missing_cached_original_and_quarantine_never_become_silent_empty(self):
        snap = index_with((576, 200, root(number=4)))
        out, _ = self.audit(snap, {(REPO, 576): source_page()})
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["index_rows_not_verified_live"], 1)
        self.assertEqual(out["live_rows"], [])
        self.assertFalse(out["can_authorize_execution"])

    def test_untrusted_origin_fails_as_unknown(self):
        msg = root(number=5)
        snap = index_with((576, 201, msg))
        out, _ = self.audit(snap, {(REPO, 576): source_page(
            (201, msg, "not-the-owner"))})
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["index_rows_not_verified_live"], 1)
        self.assertEqual(out["live_rows"], [])

    def test_recipient_isolation_does_not_fetch_unrelated_issues(self):
        claude, codex = root(number=6), root(number=7, issue=577, recipient="codex")
        snap = index_with((576, 301, claude), (577, 302, codex))
        out, calls = self.audit(snap, {(REPO, 577): source_page(
            (302, codex, "kinoko34077"))}, recipient="codex")
        self.assertEqual(out["candidate_issues"], 1)
        self.assertEqual(out["live_original_roots"], 1)
        self.assertEqual(calls, [("issue", REPO, 577), ("comments", REPO, 577)])

    def test_public_index_authority_and_locator_are_not_trusted(self):
        msg = root(number=8)
        for name, value in (("can_authorize_execution", True),
                            ("requires_live_original_issue_revalidation", False),
                            ("kind", "WORK_ORDER"),
                            ("complete_source_universe", True)):
            idx = index_with((576, 401, msg))
            idx[name] = value
            with self.assertRaisesRegex(ValueError, "PUBLIC_INDEX_FALSE_AUTHORITY"):
                validate_index(idx, now=NOW)
        idx = index_with((576, 401, msg))
        idx["rows"][0]["source_url"] = "javascript:alert(1)"
        with self.assertRaisesRegex(ValueError, "INVALID_PUBLIC_INDEX_LOCATOR"):
            validate_index(idx, now=NOW)

    def test_future_timestamp_and_malformed_schema_fail_closed(self):
        snap = index_with(age_seconds=-900)
        with self.assertRaisesRegex(ValueError, "PUBLIC_INDEX_FROM_FUTURE"):
            validate_index(snap, now=NOW)
        snap = index_with()
        snap["schema_version"] = "invalid"
        with self.assertRaisesRegex(ValueError, "INVALID_PUBLIC_INDEX_SCHEMA"):
            validate_index(snap, now=NOW)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_INDEX_FIELD"):
            json.loads('{"rows":[],"rows":[]}', object_pairs_hook=_unique_pairs)

    def test_zero_recipient_candidates_not_zero_work_authority(self):
        snap = index_with()
        out, calls = self.audit(snap, {})
        self.assertEqual(out["status"], "BOUNDED_LIVE_CANDIDATE_READ")
        self.assertEqual(calls, [])
        self.assertEqual(out["candidate_issues"], 0)
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["complete_source_universe"])

    def test_unreachable_public_index_is_blocked_without_credentials(self):
        with mock.patch("urllib.request.build_opener",
                        side_effect=OSError("unavailable")):
            with self.assertRaisesRegex(ValueError, "PUBLIC_INDEX_READ_UNAVAILABLE"):
                fetch_public_json()


if __name__ == "__main__":
    unittest.main()
