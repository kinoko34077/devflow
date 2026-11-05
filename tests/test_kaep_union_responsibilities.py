"""B6 union provenance and bounded window interpretation responsibility tests."""
from __future__ import annotations

import unittest

from tools import kaep_live_union_cli as union
from tools.kaep_inbox_reader import InvalidMessage
from tests.test_kaep_live_candidate_cli import REPO, index_with, root, source_page, issue_object
from tests.test_kaep_live_union_cli import recent


class UnionReadResponsibilityTests(unittest.TestCase):
    def test_origin_precedence_and_verified_candidate_agreement(self):
        def origin(*, indexed=False, updated=False, marker=False):
            key = (REPO, 576)
            return union._source_origin(
                *key,
                indexed_sources={key} if indexed else set(),
                recent_sources={key} if updated else set(),
                marker_in_scope={key} if marker else set(),
            )
        self.assertEqual(origin(indexed=True, updated=True, marker=True), "BOTH")
        self.assertEqual(origin(indexed=True, marker=True), "INDEXED_SOURCE")
        self.assertEqual(origin(updated=True, marker=True), "LATEST_COMMENT_SOURCE")
        self.assertEqual(origin(marker=True), "INCREMENTAL_MARKER_SOURCE")
        self.assertEqual(origin(), "PREVIOUS_REPORT_SOURCE")

        msg = root(number=501)
        snap = index_with((576, 901, msg), status="BOUNDED_SEARCH_READ")
        out = union.read_union(
            snap, recipient="claude-code",
            recent_read=lambda repo, since=None: [recent(576, cid=902)],
            issue_read=lambda repo, number: issue_object(number),
            comments_read=lambda repo, number: source_page((901, msg, "kinoko34077")),
        )
        self.assertEqual(out["status"], "BOUNDED_UNION_READ")
        self.assertEqual(out["live_rows"][0]["source_origin"], "BOTH")
        self.assertEqual(out["source_candidates"][0]["origin"], "BOTH")
        self.assertFalse(out["source_candidates"][0]["grants_work_authority"])

    def test_updated_page_diagnostics_keep_overlap_then_cap_warning_order(self):
        def recent_window(repo, since=None):
            self.assertEqual(repo, REPO)
            return {
                "comments": [recent(576, cid=905, body="ordinary")],
                "truncated": True,
                "read_pages": 2,
                "page_limit": 2,
                "page_boundary_overlap_count": 1,
            }
        sources, counts, pages, warnings = union._collect_recent_source_hints(
            [REPO], recent_read=recent_window, since=None,
        )
        self.assertEqual(sources, set())
        self.assertEqual(counts, {REPO: 1})
        self.assertEqual(pages, {REPO: 2})
        self.assertEqual(warnings, [
            {"repository": REPO, "reason_code": "UPDATED_PAGE_BOUNDARY_OVERLAP"},
            {"repository": REPO, "reason_code": "RECENT_WINDOW_TRUNCATED"},
        ])

    def test_malformed_updated_window_fails_before_any_original_get(self):
        seen = []
        def recent_window(repo, since=None):
            return {
                "comments": [],
                "truncated": False,
                "read_pages": 2,
                "page_limit": 1,
                "page_boundary_overlap_count": 0,
            }
        with self.assertRaisesRegex(InvalidMessage, "INVALID_UPDATED_PAGE_RESULT"):
            union.read_union(
                index_with(status="BOUNDED_SEARCH_READ"),
                recipient="claude-code",
                recent_read=recent_window,
                issue_read=lambda *args: seen.append("issue"),
                comments_read=lambda *args: seen.append("comments"),
            )
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
