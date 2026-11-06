"""Offline contract tests for fixed live KAEP authenticated gh API probe."""
from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from tools import kaep_gh_read_profile as probe


def source_page(issue: int, *, secret: str = "fixture private body") -> str:
    return json.dumps([[{
        "id": 1000 + issue,
        "body": secret,
        "user": {"login": "kinoko34077", "id": 79015263},
    }]])


class KAEPGhReadProfileTests(unittest.TestCase):
    def test_cli_denies_no_opt_in_without_calling_real_source(self):
        with mock.patch.object(probe, "profile",
                               side_effect=AssertionError("no source reads")):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(probe.main([]), 2)
        self.assertEqual(out.getvalue().strip(), "KAEP_GH_READ_PROFILE=OPT_IN_REQUIRED")

    def test_exact_sources_and_no_raw_payload_output(self):
        calls = []
        def read_issue(repo, num):
            calls.append(("issue", repo, num))
            return {"number": num,
                    "html_url": f"https://github.com/{repo}/issues/{num}",
                    "body": "fixture private body"}
        def read_comments(repo, num):
            calls.append(("comments", repo, num))
            return source_page(num)
        def read_recent(repo):
            calls.append(("recent", repo))
            return [{"body": "fixture private body", "id": 1}]
        result = probe.profile(issue_read=read_issue, comments_read=read_comments,
                               recent_read=read_recent)
        self.assertEqual(calls, [
            ("issue", probe.REPOSITORY, 847),
            ("comments", probe.REPOSITORY, 847),
            ("issue", probe.REPOSITORY, 680),
            ("comments", probe.REPOSITORY, 680),
            ("recent", probe.REPOSITORY),
        ])
        self.assertEqual(result["status"], "BOUNDED_READ")
        self.assertEqual([row["items"] for row in result["observations"]],
                         [1, 1, 1, 1, 1])
        self.assertFalse(result["can_authorize_execution"])
        self.assertFalse(result["complete_source_universe"])
        self.assertNotIn("fixture private body", json.dumps(result))

    def test_read_failure_does_not_log_exception_details_or_claim_empty(self):
        def read_issue(repo, num):
            raise OSError("secret token in traceback")
        def read_comments(repo, num):
            raise probe.InvalidMessage("GITHUB_READ_FAILED")
        def read_recent(repo):
            return []
        out = probe.profile(issue_read=read_issue, comments_read=read_comments,
                            recent_read=read_recent)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual([x["status"] for x in out["observations"][:4]],
                         ["READ_UNAVAILABLE"] * 4)
        self.assertEqual(out["observations"][4]["status"], "READ_OK")
        self.assertNotIn("secret token", json.dumps(out))
        self.assertFalse(out["can_authorize_execution"])

    def test_mismatched_issue_or_invalid_comment_page_cannot_pass(self):
        def read_issue(repo, num):
            return {"number": num, "html_url": "https://evil.example/issue"}
        def read_comments(repo, num):
            return '{"malformed":"page"}'
        out = probe.profile(issue_read=read_issue, comments_read=read_comments,
                            recent_read=lambda repo: [])
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual([x["status"] for x in out["observations"][:4]],
                         ["READ_UNAVAILABLE"] * 4)
        self.assertIsNone(out["observations"][0]["items"])


if __name__ == "__main__":
    unittest.main()
