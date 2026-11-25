"""Shared native page mechanism independent of transport and domain."""
import unittest
from urllib.parse import parse_qs, urlsplit

from devflow_mapped_read import MappedReadError
from devflow_mapped_read.github_pages import (RepositoryIssueQuery, iter_list_pages,
                                             read_linked_rows)

REPO = "kinoko34077/devflow"


class NativePagesTests(unittest.TestCase):
    def test_native_plan_preserves_legacy_query_and_default_sort(self):
        plan = RepositoryIssueQuery(REPO, "issue_comment", sort="updated",
                                    direction="desc", native_since="2026-11-20T00:00:00Z")
        self.assertEqual(plan.path(2),
            "/repos/kinoko34077/devflow/issues/comments?sort=updated&direction=desc&per_page=100&page=2&since=2026-11-20T00:00:00Z")
        issue = RepositoryIssueQuery(REPO, "issue", state="all", per_page=10)
        u = urlsplit(issue.path(1))
        self.assertEqual(u.path, "/repos/" + REPO + "/issues")
        self.assertEqual(parse_qs(u.query), {"per_page": ["10"], "state": ["all"], "page": ["1"]})

    def test_rejects_invalid_path_filters_and_dates(self):
        for args in ({"repository": "../repo"}, {"repository": "a/../b"},
                     {"kind": "issue_comment", "state": "all"},
                     {"native_since": "2026-02-30T00:00:00Z"},
                     {"per_page": True}, {"direction": "other"}):
            with self.subTest(args=args), self.assertRaises(MappedReadError):
                RepositoryIssueQuery(**{"repository": REPO, "kind": "issue", **args})
        with self.assertRaises(MappedReadError):
            RepositoryIssueQuery(REPO, "issue").path(True)

    def test_link_and_short_page_are_distinct(self):
        calls = []
        def fetch(n):
            calls.append(n)
            return ([{"id": n}], n == 1)
        pages = list(iter_list_pages(fetch, per_page=2, max_pages=3))
        self.assertEqual(calls, [1, 2])
        self.assertEqual([p.has_next for p in pages], [True, False])
        calls.clear()
        pages = list(iter_list_pages(lambda n: (calls.append(n) or [1, 2], False),
                                    per_page=2, max_pages=3))
        self.assertEqual(calls, [1])
        self.assertFalse(pages[-1].has_next)

    def test_budget_and_early_break_never_make_extra_get(self):
        calls = []
        def fetch(n):
            calls.append(n)
            return [1, 2], None
        pages = list(iter_list_pages(fetch, per_page=2, max_pages=2))
        self.assertEqual(calls, [1, 2])
        self.assertTrue(pages[-1].has_next)
        calls.clear()
        for page in iter_list_pages(fetch, per_page=2, max_pages=10):
            break
        self.assertEqual(calls, [1])

    def test_invalid_page_and_failure_are_not_empty_success(self):
        for result in (({}, None), ([1, 2, 3], None), ([], True), ([1], "false")):
            with self.subTest(result=result), self.assertRaises(MappedReadError):
                list(iter_list_pages(lambda n: result, per_page=2, max_pages=2))
        calls = []
        with self.assertRaises(MappedReadError):
            list(iter_list_pages(lambda n: calls.append(n), per_page=0, max_pages=2))
        self.assertEqual(calls, [])
        def failed(n):
            if n == 2:
                raise RuntimeError("transport failed")
            return [1], True
        with self.assertRaisesRegex(RuntimeError, "transport failed"):
            list(iter_list_pages(failed, per_page=2, max_pages=2))

    def test_complete_link_read_uses_declared_plan_and_does_not_follow_link_url(self):
        plan = RepositoryIssueQuery(REPO, "issue", state="all", per_page=2,
                                    native_since="2026-11-20T00:00:00Z")
        calls = []
        def get(path):
            calls.append(path)
            page = parse_qs(urlsplit(path).query)["page"]
            if page == ["1"]:
                # A short page with explicit next still has a next page.
                return [{"id": 1}], '<https://untrusted.example/other>; rel="next"'
            return [{"id": 2}, {"id": 3}], ""
        self.assertEqual(read_linked_rows(plan.path, get, per_page=plan.per_page, max_pages=3),
                         [{"id": 1}, {"id": 2}, {"id": 3}])
        self.assertEqual(calls, [plan.path(1), plan.path(2)])

    def test_complete_link_read_refuses_budget_and_invalid_header(self):
        plan = RepositoryIssueQuery(REPO, "issue", per_page=2)
        calls = []
        def get(path):
            calls.append(path)
            return [1], '<https://api.github.com/example>; rel="next"'
        with self.assertRaisesRegex(MappedReadError, "PAGE_LIMIT"):
            read_linked_rows(plan.path, get, per_page=2, max_pages=2)
        self.assertEqual(calls, [plan.path(1), plan.path(2)])
        for invalid in (None, True, []):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                    MappedReadError, "INVALID_LINK_HEADER"):
                read_linked_rows(plan.path, lambda path: ([], invalid),
                                 per_page=2, max_pages=2)

    def test_complete_link_read_never_returns_failed_prefix(self):
        plan = RepositoryIssueQuery(REPO, "issue", per_page=2)
        def get(path):
            if path == plan.path(1):
                return [1, 2], '<https://api.github.com/example>; rel="next"'
            raise RuntimeError("existing transport failed")
        with self.assertRaisesRegex(RuntimeError, "existing transport failed"):
            read_linked_rows(plan.path, get, per_page=2, max_pages=2)
        with self.assertRaisesRegex(MappedReadError, "INVALID_LIST_PAGE"):
            read_linked_rows(plan.path, lambda path: ([], 'rel="next"'),
                             per_page=2, max_pages=2)
