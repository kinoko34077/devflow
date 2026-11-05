"""R7: verified B6 root projection owns two distinct baseline comparison policies."""
from __future__ import annotations

import unittest
from tools import kaep_live_union_cli as union

REPO = "kinoko34077/devflow"


class VerifiedUnionProjectionTests(unittest.TestCase):
    def row(self, number, message, *, state="open", observation="PENDING_REPLY"):
        return {
            "repository": REPO,
            "issue_number": number,
            "issue_url": f"https://github.com/{REPO}/issues/{number}",
            "source_url": f"https://github.com/{REPO}/issues/{number}#issuecomment-901",
            "source_comment_id": 901,
            "message_id": message,
            "issue_state": state,
            "reply_observation": observation,
            "source_validation": "STRICT_COMPLETE_FOR_CANDIDATE",
        }

    def project(self, current, indexed, previous=None, recent=(), marker=()):
        return union._project_verified_union_rows(
            current, indexed_by_key=indexed, prior_rows=previous or {},
            recipient="claude-code",
            indexed_sources={(x[0], x[1]) for x in indexed},
            recent_sources={(REPO, n) for n in recent},
            marker_in_scope={(REPO, n) for n in marker},
        )

    def test_snapshot_missing_fields_does_not_claim_change_but_previous_compares_strict(self):
        key = (REPO, 576, 901, "msg_valid123")
        current = self.row(576, "msg_valid123", state="closed", observation="ANSWER_OBSERVED")
        partial_old = {"issue_state": None, "reply_observation": None}
        prior = {"issue_state": "open", "reply_observation": "PENDING_REPLY"}
        rows, snapshot_changes, previous_changes = self.project(
            {key: current}, {key: partial_old}, {key: prior},
        )
        self.assertEqual(snapshot_changes, 0)
        self.assertEqual(previous_changes, 1)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["changed_from_snapshot"])
        self.assertTrue(rows[0]["changed_from_previous_report"])
        self.assertEqual(rows[0]["index_presence"], "INDEXED_AND_LIVE")
        self.assertFalse(rows[0]["incremental_marker_observed"])

    def test_new_original_and_sorted_roots_do_not_infer_old_comparison(self):
        new_key = (REPO, 580, 901, "msg_new123")
        old_key = (REPO, 576, 901, "msg_old123")
        current = {
            new_key: self.row(580, "msg_new123"),
            old_key: self.row(576, "msg_old123"),
        }
        rows, snapshot_changes, previous_changes = self.project(
            current, {}, recent=(580,), marker=(580,),
        )
        self.assertEqual([r["issue_number"] for r in rows], [576, 580])
        self.assertEqual(snapshot_changes, 0)
        self.assertEqual(previous_changes, 0)
        self.assertEqual(rows[1]["source_origin"], "LATEST_COMMENT_SOURCE")
        self.assertEqual(rows[1]["index_presence"], "LIVE_ORIGINAL_ONLY")
        self.assertTrue(rows[1]["incremental_marker_observed"])
        self.assertFalse(rows[1]["changed_from_previous_report"])

    def test_snapshot_reply_change_detected_without_state_change_and_no_extra_fields(self):
        key = (REPO, 576, 901, "msg_valid123")
        current = self.row(576, "msg_valid123", observation="ANSWER_OBSERVED")
        old = {"issue_state": "open", "reply_observation": "PENDING_REPLY"}
        rows, snap, previous = self.project({key: current}, {key: old})
        self.assertEqual((snap, previous), (1, 0))
        self.assertTrue(rows[0]["changed_from_snapshot"])
        self.assertEqual(set(rows[0]), {
            "changed_from_previous_report", "repository", "issue_number",
            "issue_url", "source_url", "source_comment_id", "message_id",
            "recipient", "issue_state", "reply_observation",
            "source_validation", "head_freshness", "incremental_marker_observed",
            "source_origin", "changed_from_snapshot", "index_presence",
        })
        self.assertEqual(rows[0]["head_freshness"], "NOT_REVALIDATED")


if __name__ == "__main__":
    unittest.main()
