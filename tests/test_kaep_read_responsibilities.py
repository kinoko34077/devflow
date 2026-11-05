"""Contract-led tests for the separated KAEP Search/read/verify/view owners."""
from __future__ import annotations

import json
import unittest

from tools.kaep_issue_search_view import build_search_list
from tests.test_kaep_issue_search_view import (
    DEV, OWNER, comment, issue, pages, root, searched,
)


class KAEPReadResponsibilityBoundaryTests(unittest.TestCase):
    def test_search_errors_first_seen_dedup_and_untrimmed_count_are_preserved(self):
        msg = root(n=576, number=1)
        query = {
            "total_count": 5, "incomplete_results": True,
            "items": [
                {"html_url": f"https://github.com/{DEV}/issues/576"},
                {"html_url": f"https://github.com/{DEV}/issues/576"},
                {"html_url": "https://untrusted.example/issues/7"},
                {"html_url": f"https://github.com/{DEV}/issues/577"},
                {"html_url": f"https://github.com/{DEV}/issues/578"},
            ],
        }
        seen = []
        def issue_read(repo, number):
            seen.append(("issue", number))
            return issue(n=number)
        def comments_read(repo, number):
            seen.append(("comments", number))
            return pages([comment(6000 + number, msg)]) if number == 576 else pages([])
        out = build_search_list(
            [DEV], {DEV: query}, fetch_original_issue=issue_read,
            fetch_comments=comments_read, expected_actor=OWNER,
            recipient="claude-code", max_candidates=2,
        )
        self.assertEqual(out["searched_candidates"], 3)
        self.assertEqual([e["reason_code"] for e in out["errors"]],
                         ["SEARCH_PAGE_INCOMPLETE", "SEARCH_LOCATOR_MISMATCH",
                          "CANDIDATE_LIMIT"])
        self.assertEqual(seen, [("issue", 576), ("comments", 576),
                                ("issue", 577), ("comments", 577)])
        self.assertEqual(out["validated_source_issues"], 2)
        self.assertEqual(out["unmatched_candidates"], 1)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertFalse(out["can_authorize_execution"])

    def test_bad_original_mailbox_keeps_ordered_partial_error_and_good_rows(self):
        a = root(n=576, number=21)
        b = root(n=577, number=22)
        called = []
        def issue_read(repo, number):
            called.append(("issue", number))
            return issue(n=number)
        def comments_read(repo, number):
            called.append(("comments", number))
            return (pages([comment(2001, a)]) if number == 576
                    else "{not json")
        for workers in (1, 2):
            with self.subTest(workers=workers):
                called.clear()
                result = build_search_list(
                    [DEV], {DEV: searched(DEV, [576, 577])},
                    fetch_original_issue=issue_read,
                    fetch_comments=comments_read,
                    expected_actor=OWNER, recipient="claude-code",
                    source_workers=workers,
                )
                self.assertEqual(result["status"], "PARTIAL_UNKNOWN")
                self.assertEqual(result["validated_source_issues"], 1)
                self.assertEqual(result["partial_source_issues"], 0)
                self.assertEqual(result["errors"], [{
                    "owning_issue": f"https://github.com/{DEV}/issues/577",
                    "reason_code": "INVALID_GITHUB_JSON",
                }])
                self.assertEqual(len(result["rows"]), 1)
                self.assertEqual(result["rows"][0]["issue_number"], 576)
                self.assertEqual(len(called), 4)
                self.assertFalse(result["can_authorize_execution"])
                self.assertFalse(result["complete_source_universe"])

    def test_actor_exclusion_and_quarantine_are_not_display_authority(self):
        valid = root(n=576, number=31)
        excluded = root(n=576, number=32)
        bad = comment(2003, root(n=576, number=33))
        bad["body"] += "\nnon-machine historical note"
        out = build_search_list(
            [DEV], {DEV: searched(DEV, [576])},
            fetch_original_issue=lambda r, n: issue(n=n),
            fetch_comments=lambda r, n: pages([
                comment(2001, valid),
                comment(2002, excluded, actor="other-actor"),
                bad,
            ]),
            expected_actor=OWNER, recipient="all",
        )
        self.assertEqual(out["partial_source_issues"], 1)
        self.assertEqual(out["validated_source_issues"], 0)
        self.assertEqual(out["errors"], [{
            "owning_issue": f"https://github.com/{DEV}/issues/576",
            "comment_id": 2003,
            "reason_code": "QUARANTINED_INVALID_WRAPPER",
        }])
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["reply_observation"],
                         "UNVERIFIED_DUE_TO_SOURCE_QUARANTINE")
        self.assertEqual(out["rows"][0]["source_validation"], "PARTIAL_UNKNOWN")
        self.assertNotIn("other-actor", json.dumps(out))
        self.assertFalse(out["can_authorize_execution"])


if __name__ == "__main__":
    unittest.main()
