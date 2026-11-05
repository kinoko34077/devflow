from __future__ import annotations

import unittest

from tools.kaep_link_validation import safe_comment_link, safe_issue_link


class KaepLinkValidationTests(unittest.TestCase):
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
