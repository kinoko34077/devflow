"""Standalone KAEP browser list: filters, partial-source alerts, safe HTML."""
from __future__ import annotations

import html as html_module
import io
import json
import re
import unittest
from unittest import mock

from tools.kaep_issue_list_html import to_html, _safe_link
from tools import kaep_issue_search_view


def report():
    return {
        "status": "PARTIAL_UNKNOWN",
        "observed_at": "2026-10-17T01:23:45+00:00",
        "source_coverage": "SEARCH_INDEX_NOT_AUTHORITATIVE",
        "repositories": ["kinoko34077/devflow", "kinoko34077/testapp"],
        "searched_candidates": 2,
        "validated_source_issues": 1,
        "partial_source_issues": 1,
        "rows": [
            {
                "repository": "kinoko34077/devflow",
                "issue_number": 576,
                "issue_url": "https://github.com/kinoko34077/devflow/issues/576",
                "source_url": "https://github.com/kinoko34077/devflow/issues/576#issuecomment-6193914061",
                "title_hint": "[QUOTE] <img src=x onerror=alert(1)> — 試験",
                "issue_state": "open",
                "issue_role": "UNCLASSIFIED",
                "issue_type": "SPEC",
                "recipient": "claude-code",
                "intent": "ANALYZE",
                "reply_observation": "UNVERIFIED_DUE_TO_SOURCE_QUARANTINE",
                "source_validation": "PARTIAL_UNKNOWN",
                "source_comment_id": 6193914061,
                "head_freshness": "NOT_REVALIDATED",
                "is_authoritative_assignment": False,
            },
            {
                "repository": "kinoko34077/testapp",
                "issue_number": 30,
                "issue_url": "javascript:alert(1)",
                "source_url": "https://github.com/notkinoko/testapp/issues/30#issuecomment-1",
                "title_hint": "<script>alert(document.cookie)</script>",
                "issue_state": "closed",
                "issue_role": "TASK",
                "issue_type": "AUDIT",
                "recipient": "codex",
                "intent": "TEST",
                "reply_observation": "ANSWER_OBSERVED",
                "source_validation": "STRICT_COMPLETE_FOR_CANDIDATE",
                "source_comment_id": 901,
                "head_freshness": "NOT_REVALIDATED",
                "is_authoritative_assignment": False,
            },
        ],
        "errors": [
            {"owning_issue": "https://github.com/kinoko34077/devflow/issues/576",
             "reason_code": "QUARANTINED_INVALID_WRAPPER", "comment_id": 6221821907},
            {"owning_issue": "javascript:alert(1)",
             "reason_code": "<unsafe>"},
        ],
        "has_unknown_work": True,
        "complete_source_universe": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
    }


class HtmlListTests(unittest.TestCase):
    def test_offline_document_includes_controls_without_project_or_api(self):
        text = to_html(report())
        for keyword in ('id="q"', 'id="repository"', 'id="role"',
                        'id="recipient"', 'id="reply"', 'id="state"',
                        'id="sort"', 'id="validation"',
                        'PARTIAL / UNKNOWN', 'Source diagnostics (2)',
                        '6193914061', 'UNCLASSIFIED',
                        'has_unknown_work' if False else 'no live refresh'):
            self.assertIn(keyword.lower(), text.lower())
        self.assertIn('charset="utf-8"', text)
        self.assertIn('source_validation' if False else 'PARTIAL_UNKNOWN', text)
        self.assertIn("script-src &#x27;sha256-", text)
        self.assertIn("connect-src &#x27;none&#x27;", text)
        self.assertNotIn("api.github.com", text)
        self.assertNotIn("fetch(", text)
        self.assertNotIn("localStorage", text)
        self.assertNotIn("github/projects", text.lower())

    def test_non_ascii_output_works_in_cp932_and_keeps_unicode_as_entities(self):
        content = to_html(report())
        content.encode("cp932")
        self.assertTrue(content.isascii())
        self.assertIn("&#", content)
        self.assertNotIn("試験", content)
        self.assertEqual(html_module.unescape(content).count("試験"), 2)  # Cell and client-side search key

    def test_untrusted_html_js_and_links_never_became_executable(self):
        content = to_html(report())
        self.assertNotIn("<img src=x onerror", content)
        self.assertNotIn("<script>alert", content)
        self.assertIn("&lt;img", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertNotIn('href="javascript:', content)
        self.assertNotIn("notkinoko/testapp/issues/30#issuecomment-1", content)
        self.assertIn('href="https://github.com/kinoko34077/devflow/issues/576"', content)
        self.assertIn("unverified link", content)
        self.assertFalse(_safe_link("https://github.com/kinoko34077/devflow/issues/576/extra",source=False))
        self.assertFalse(_safe_link("javascript:alert(1)",source=False))

    def test_error_bounded_result_is_not_presented_as_complete(self):
        data = report()
        data["rows"] = []
        data["errors"] = [{"reason_code": "SOURCE_READ_UNAVAILABLE"}]
        data["status"] = "PARTIAL_UNKNOWN"
        out = to_html(data)
        self.assertIn("0 / 0 rows", out)
        self.assertIn("SOURCE_READ_UNAVAILABLE", out)
        self.assertIn("PARTIAL / UNKNOWN", out)
        self.assertIn("not a complete issue universe", out.lower())
        self.assertIn("Source diagnostics (1)", out)

    def test_browser_no_js_still_has_all_rows_and_diagnostics(self):
        rendered = to_html(report())
        self.assertIn("Filtering requires JavaScript", rendered)
        self.assertEqual(rendered.count("<tr data-"), 2)
        self.assertIn("QUARANTINED_INVALID_WRAPPER", rendered)
        self.assertIn("ANSWER_OBSERVED", rendered)

    def test_malformed_display_input_blocks_before_generation(self):
        with self.assertRaisesRegex(ValueError, "INVALID_DISPLAY_RESULT"):
            to_html({"rows": None, "errors": []})
        with self.assertRaisesRegex(ValueError, "INVALID_DISPLAY_ROW"):
            to_html({"rows": [42], "errors": []})
        bad = report()
        bad["rows"][0]["issue_number"] = "576"
        with self.assertRaisesRegex(ValueError, "INVALID_DISPLAY_ISSUE"):
            to_html(bad)

    def test_cli_html_opt_in_prints_offline_document_and_retains_rc2(self):
        with (mock.patch.object(kaep_issue_search_view, "search_repository",
                                return_value={"items": [], "total_count": 0,
                                              "incomplete_results": False}),
              mock.patch.object(kaep_issue_search_view, "build_search_list",
                                return_value=report()),
              mock.patch("sys.stdout", new_callable=io.StringIO) as stdout):
            rc = kaep_issue_search_view.main(
                ["--repository", "kinoko34077/devflow",
                 "--expect-source-actor", "kinoko34077", "--format", "html"])
        self.assertEqual(rc, 2)  # Partial unknown remains an explicit nonzero RC.
        self.assertTrue(stdout.getvalue().startswith("<!doctype html>"))
        self.assertIn("KAEP", stdout.getvalue())
        self.assertTrue(stdout.getvalue().isascii())

    def test_blocked_cli_renders_explicit_failure_not_empty_success(self):
        with (mock.patch.object(kaep_issue_search_view, "search_repository",
                                side_effect=kaep_issue_search_view.InvalidMessage("SEARCH_FAILED")),
              mock.patch("sys.stdout", new_callable=io.StringIO) as stdout):
            rc = kaep_issue_search_view.main(
                ["--repository", "kinoko34077/devflow",
                 "--expect-source-actor", "kinoko34077", "--format", "html"])
        self.assertEqual(rc, 2)
        self.assertTrue(stdout.getvalue().startswith("<!doctype html>"))
        self.assertIn("PARTIAL / UNKNOWN", stdout.getvalue())
        self.assertIn("SEARCH_FAILED", stdout.getvalue())
        self.assertIn("0 / 0 rows", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
