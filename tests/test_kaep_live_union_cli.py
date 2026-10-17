"""B6 RT4 union: old indexed work + live new sources and state changes."""
from __future__ import annotations

import io
import json
from unittest import TestCase, mock

from tools import kaep_live_union_cli as union
from tools.kaep_inbox_reader import InvalidMessage, MARKER
from tools.kaep_mailbox_codec import encode_comment
from tests.test_kaep_live_candidate_cli import (
    REPO, root, index_with, issue_object, source_page,
)


def recent(issue, cid=900, body=MARKER+" marker"):
    return {
        "id": cid, "body": body, "user": {"login": "untrusted-discovery"},
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{issue}",
    }


class LiveUnionTests(TestCase):
    def run_union(self, snapshot, new_comments, sources, *, recipient="claude-code", states=None):
        seen = []
        states = states or {}
        def fetch_issue(repo, number):
            seen.append(("issue", repo, number))
            return issue_object(number, state=states.get(number, "open"))
        def fetch_comments(repo, number):
            seen.append(("comments", repo, number))
            return sources[(repo, number)]
        with mock.patch.object(union.strict, "build_search_list", wraps=union.strict.build_search_list) as verify:
            report = union.read_union(
                snapshot, recipient=recipient,
                recent_read=lambda repo, since=None: list(new_comments),
                issue_read=fetch_issue, comments_read=fetch_comments)
        return report, seen, verify.call_count

    def test_old_index_plus_new_unindexed_issue_are_strictly_verified_once(self):
        old, new = root(number=1), root(number=2, issue=580)
        snap = index_with((576, 101, old), status="BOUNDED_SEARCH_READ")
        data = {
            (REPO, 576): source_page((101, old, "kinoko34077")),
            (REPO, 580): source_page((920, new, "kinoko34077")),
        }
        output, calls, verified = self.run_union(
            snap, [recent(580, cid=920), recent(576, cid=999)],
            data)
        self.assertEqual(output["status"], "BOUNDED_UNION_READ")
        self.assertEqual(output["indexed_issue_count"], 1)
        self.assertEqual(output["recent_marker_issue_count"], 2)
        self.assertEqual(output["source_issue_count"], 2)
        self.assertEqual(output["new_unindexed_source_issues"], 1)
        self.assertEqual(output["new_in_originals"], 1)
        self.assertEqual(output["live_original_roots"], 2)
        self.assertEqual(verified, 1)
        self.assertEqual(len(calls), 4)
        by_issue = {x["issue_number"]: x for x in output["live_rows"]}
        self.assertEqual(by_issue[576]["source_origin"], "BOTH")
        self.assertEqual(by_issue[580]["source_origin"], "LATEST_COMMENT_SOURCE")
        self.assertEqual(by_issue[580]["index_presence"], "LIVE_ORIGINAL_ONLY")
        self.assertTrue(output["has_unknown_work"])
        self.assertFalse(output["complete_source_universe"])
        self.assertFalse(output["absence_of_work_proven"])
        self.assertFalse(output["recipient_pickup_proven"])
        self.assertFalse(output["can_authorize_execution"])
        self.assertNotIn("private test-only prompt", json.dumps(output))

    def test_issue_closed_without_new_comment_is_detected_for_indexed_source(self):
        msg = root(number=4)
        snap = index_with((576, 133, msg), status="BOUNDED_SEARCH_READ")
        snap["rows"][0]["issue_state"] = "open"
        snap["rows"][0]["reply_observation"] = "PENDING_REPLY"
        result, calls, _ = self.run_union(
            snap, [], {(REPO, 576): source_page((133, msg, "kinoko34077"))},
            states={576: "closed"})
        self.assertEqual(result["status"], "BOUNDED_UNION_READ")
        self.assertEqual(result["recent_marker_issue_count"], 0)
        self.assertEqual(result["state_or_reply_changes_from_snapshot"], 1)
        self.assertEqual(result["live_rows"][0]["issue_state"], "closed")
        self.assertTrue(result["live_rows"][0]["changed_from_snapshot"])
        self.assertEqual(calls, [("issue", REPO, 576), ("comments", REPO, 576)])

    def test_live_only_other_recipient_is_not_executable_assignment(self):
        other = root(number=5, issue=590, recipient="codex")
        snap = index_with(status="BOUNDED_SEARCH_READ")
        report, _, _ = self.run_union(
            snap, [recent(590)], {(REPO, 590): source_page((201, other, "kinoko34077"))},
            recipient="chatgpt")
        self.assertEqual(report["status"], "BOUNDED_UNION_READ")
        self.assertEqual(report["live_original_roots"], 0)
        self.assertEqual(report["new_unindexed_source_issues"], 1)
        self.assertTrue(report["has_unknown_work"])
        self.assertFalse(report["absence_of_work_proven"])

    def test_source_overflow_and_page_overflow_fail_safe(self):
        snap = index_with(status="BOUNDED_SEARCH_READ")
        with self.assertRaisesRegex(InvalidMessage, "UNION_SOURCE_LIMIT"):
            union.read_union(
                snap, recipient="chatgpt",
                recent_read=lambda repo, since=None:
                    [recent(i+1, cid=i+1) for i in range(41)])
        with mock.patch.object(union.strict, "build_search_list", return_value={
                "status": "BOUNDED_SEARCH_READ",
                "observed_at": "2026-10-17T00:00:00Z",
                "rows": [], "errors": []}):
            out = union.read_union(
                snap, recipient="chatgpt",
                recent_read=lambda repo, since=None:
                    [recent(576, cid=i+1, body="ordinary") for i in range(100)])
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["warnings"][0]["reason_code"], "RECENT_WINDOW_TRUNCATED")

    def test_untrusted_api_cross_repo_or_invalid_comment_blocks(self):
        snap = index_with(status="BOUNDED_SEARCH_READ")
        bad = recent(590)
        bad["issue_url"] = "https://api.github.com/repos/another/repo/issues/590"
        with self.assertRaisesRegex(InvalidMessage, "INVALID_LIVE_ISSUE_LOCATOR"):
            union.read_union(snap, recipient="chatgpt",
                             recent_read=lambda repo, since=None: [bad])
        with self.assertRaisesRegex(InvalidMessage, "INVALID_LIVE_COMMENT"):
            union.read_union(snap, recipient="chatgpt",
                             recent_read=lambda repo, since=None: [{"body": MARKER}])

    def test_cached_source_missing_fails_partial_not_fake_success(self):
        msg = root(number=8)
        snap = index_with((576, 344, msg), status="BOUNDED_SEARCH_READ")
        out, _, _ = self.run_union(
            snap, [], {(REPO, 576): source_page()})
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["cached_rows_not_verified_live"], 1)
        self.assertTrue(out["has_unknown_work"])

    def test_empty_bounded_union_never_proves_no_pending_and_does_not_read_issue(self):
        snap = index_with(status="BOUNDED_SEARCH_READ")
        output, calls, _ = self.run_union(snap, [], {})
        self.assertEqual(output["status"], "BOUNDED_UNION_READ")
        self.assertEqual(calls, [])
        self.assertEqual(output["source_issue_count"], 0)
        self.assertFalse(output["absence_of_work_proven"])

    def test_blocked_cli_never_emits_source_body_or_secrets(self):
        with (mock.patch.object(union.cached, "fetch_public_json",
                                side_effect=InvalidMessage("PUBLIC_INDEX_UNAVAILABLE")),
              mock.patch("sys.stdout", new_callable=io.StringIO) as stream):
            rc = union.main(["--recipient", "codex"])
        data = json.loads(stream.getvalue())
        self.assertEqual(rc, 2)
        self.assertEqual(data["status"], "BLOCKED")
        self.assertEqual(data["reason_code"], "PUBLIC_INDEX_UNAVAILABLE")
        self.assertNotIn("Authorization", stream.getvalue())
        self.assertFalse(data["can_authorize_execution"])
