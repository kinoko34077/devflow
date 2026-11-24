"""Bounded GitHub-native updated range contract; no network or new auth."""
import unittest
from urllib.parse import parse_qs, urlsplit

from tools.devflow_mcp_core import DevflowMCPError, GitHubReader

REPO = "kinoko34077/devflow"
API = "https://api.github.com/repos/" + REPO
LOW = "2026-11-20T00:00:00Z"
HIGH = "2026-11-21T00:00:00Z"


def issue(identity, timestamp, **extra):
    return {"id": identity, "number": identity, "state": "open",
            "repository_url": API, "updated_at": timestamp, **extra}


def comment(identity, timestamp, **extra):
    return {"id": identity, "issue_url": API + "/issues/1",
            "updated_at": timestamp, **extra}


class UpdatedRangeTests(unittest.TestCase):
    def reader(self, *pages):
        calls = []
        def transport(url, headers):
            calls.append((urlsplit(url).path, parse_qs(urlsplit(url).query)))
            if len(calls) > len(pages):
                self.fail("unexpected GET")
            page = pages[len(calls) - 1]
            if isinstance(page, Exception):
                raise page
            return page
        return GitHubReader(transport=transport), calls

    def test_issue_native_since_and_local_half_open_range(self):
        reader, calls = self.reader(
            [issue(4, HIGH), issue(3, LOW, pull_request={})],
            [issue(2, LOW), issue(1, "2026-11-19T23:59:59Z")],
            [],
        )
        result = reader.read_updated_range(REPO, kind="issue", from_utc=LOW,
                                           to_utc=HIGH, per_page=2)
        self.assertEqual([x["id"] for x in result["items"]], [2])
        self.assertEqual(result["status"], "BOUNDED_WINDOW_READ")
        self.assertFalse(result["snapshot_atomic"])
        self.assertEqual(result["read_pages"], 3)
        self.assertEqual(calls[0][0], "/repos/" + REPO + "/issues")
        self.assertEqual(calls[0][1]["since"], ["2026-11-19T23:59:59Z"])
        self.assertEqual(calls[0][1]["state"], ["all"])
        self.assertEqual([q["page"] for _, q in calls], [["1"], ["2"], ["3"]])

    def test_comments_page_limit_and_duplicates(self):
        reader, calls = self.reader([comment(1, LOW)], [comment(1, LOW)])
        result = reader.read_updated_range(REPO, kind="issue_comment",
                                           per_page=1, max_pages=2)
        self.assertEqual(result["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(result["reason_codes"], ["DUPLICATE_RECORD_ID", "PAGE_LIMIT"])
        self.assertEqual(len(result["items"]), 1)
        self.assertFalse(result["page_exhausted"])
        self.assertEqual(calls[0][0], "/repos/" + REPO + "/issues/comments")
        self.assertNotIn("state", calls[0][1])

    def test_empty_read_is_bounded_not_atomic(self):
        reader, _ = self.reader([])
        result = reader.read_updated_range(REPO, kind="issue")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["status"], "BOUNDED_WINDOW_READ")
        self.assertTrue(result["requires_source_revalidation"])

    def test_rejects_invalid_filters_before_get(self):
        for args in (
            {"kind": "unknown"}, {"kind": "issue", "max_pages": True},
            {"kind": "issue", "per_page": 0}, {"kind": "issue", "state": "unknown"},
            {"kind": "issue_comment", "state": "open"},
            {"kind": "issue", "from_utc": "2026-02-30T00:00:00Z"},
            {"kind": "issue", "from_utc": HIGH, "to_utc": LOW},
            {"kind": "issue", "from_utc": LOW, "to_utc": LOW},
        ):
            with self.subTest(args=args):
                reader, calls = self.reader()
                with self.assertRaises(DevflowMCPError):
                    reader.read_updated_range(REPO, **args)
                self.assertEqual(calls, [])

    def test_rejects_bad_rows_and_cross_repository(self):
        for kind, row in (
            ("issue", issue(1, "bad")),
            ("issue", issue(1, LOW, repository_url="https://api.github.com/repos/other/repo")),
            ("issue_comment", comment(1, LOW, issue_url="https://api.github.com/repos/other/repo/issues/1")),
            ("issue_comment", comment(True, LOW)),
            ("issue_comment", None),
        ):
            with self.subTest(kind=kind, row=row):
                reader, _ = self.reader([row])
                with self.assertRaises(DevflowMCPError):
                    reader.read_updated_range(REPO, kind=kind)

    def test_transport_failure_is_not_empty_success(self):
        reader, _ = self.reader([comment(1, LOW)], RuntimeError("failed"))
        with self.assertRaises(DevflowMCPError):
            reader.read_updated_range(REPO, kind="issue_comment", per_page=1)

    def test_legacy_recent_reader_remains_one_page(self):
        row = {"id": 1}
        reader, calls = self.reader([row])
        self.assertEqual(reader.list_recent_repository_comments(REPO), [row])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
