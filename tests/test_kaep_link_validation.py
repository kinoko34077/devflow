from __future__ import annotations

import unittest
from pathlib import Path

from tools.kaep_link_validation import (
    owner_comment_url,
    owner_issue_url,
    safe_comment_link,
    safe_issue_link,
)


class KaepLinkValidationTests(unittest.TestCase):
    def test_direct_public_routes_use_shared_owner_issue_formatter(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "tools/kaep_gh_read_profile.py",
            "tools/kaep_live_delta_view.py",
            "tools/kaep_route_notice.py",
            "tools/kaep_transport_compare.py",
        ):
            with self.subTest(relative=relative):
                source = (root / relative).read_text(encoding="utf-8")
                self.assertNotIn("https://github.com/{", source)

    def test_owner_url_formatters_preserve_canonical_shape(self) -> None:
        issue = owner_issue_url("kinoko34077/devflow", 576)
        comment = owner_comment_url("kinoko34077/devflow", 576, 123)
        self.assertEqual(issue, "https://github.com/kinoko34077/devflow/issues/576")
        self.assertEqual(comment, issue + "#issuecomment-123")
        self.assertEqual(safe_issue_link(issue), issue)
        self.assertEqual(safe_comment_link(comment), comment)

    def test_owner_issue_and_comment_links_are_separately_allowlisted(self) -> None:
        issue = "https://github.com/kinoko34077/devflow/issues/576"
        comment = issue + "#issuecomment-123"
        self.assertEqual(safe_issue_link(issue), issue)
        self.assertEqual(safe_comment_link(comment), comment)
        self.assertIsNone(safe_issue_link(comment))
        self.assertIsNone(safe_comment_link(issue))

    def test_untrusted_or_non_string_values_fail_closed(self) -> None:
        for value in (
            "https://github.com/other-owner/devflow/issues/576",
            "https://github.com/kinoko34077/devflow/issues/576/extra",
            "javascript:alert(1)",
            None,
            576,
        ):
            with self.subTest(value=value):
                self.assertIsNone(safe_issue_link(value))
                self.assertIsNone(safe_comment_link(value))


if __name__ == "__main__":
    unittest.main()
