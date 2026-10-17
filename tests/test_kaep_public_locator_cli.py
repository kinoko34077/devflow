"""Public KAEP marker locator discovery: pagination and fail-closed limits."""
from __future__ import annotations

import io
import json
from unittest import TestCase, mock

from tools import kaep_public_locator_cli as scan
from tools.kaep_inbox_reader import MARKER

OWNER = "kinoko34077"


def repo(name: str, *, private: bool = False):
    return {"full_name": f"{OWNER}/{name}", "owner": {"login": OWNER},
            "private": private}


def comment(name: str, issue: int, cid: int, *, kaep: bool = True):
    return {"issue_url": f"https://api.github.com/repos/{OWNER}/{name}/issues/{issue}",
            "id": cid, "body": (MARKER + "\njson payload secret") if kaep else "ordinary"}


class PublicLocatorsTests(TestCase):
    def test_public_owner_enumeration_is_automatic_and_only_emits_links(self):
        calls = []
        def fetch(path):
            calls.append(path)
            if path.startswith("/users/"):
                return [repo("devflow"), repo("execution-coordinator")]
            if path.startswith(f"/repos/{OWNER}/devflow/"):
                return [comment("devflow", 503, 5001),
                        comment("devflow", 504, 5002, kaep=False)]
            if path.startswith(f"/repos/{OWNER}/execution-coordinator/"):
                return [comment("execution-coordinator", 142, 9001)]
            self.fail(f"unexpected API call: {path}")
        out = scan.discover(fetch=fetch)
        self.assertEqual(out["status"], "BOUNDED_PUBLIC_MARKER_READ")
        self.assertEqual(out["repository_count_observed"], 2)
        self.assertEqual(out["repositories_with_all_comment_pages_read"], 2)
        self.assertEqual(out["locator_count"], 2)
        self.assertEqual(
            [x["locator"] for x in out["locators"]],
            ["devflow#503@5001", "execution-coordinator#142@9001"])
        self.assertTrue(out["public_only"])
        self.assertFalse(out["complete_source_universe"])
        self.assertFalse(out["recipient_pickup_proven"])
        self.assertFalse(out["can_authorize_execution"])
        self.assertEqual(len(calls), 3)
        raw = json.dumps(out)
        self.assertNotIn("json payload secret", raw)
        self.assertNotIn("ordinary", raw)
        self.assertNotIn("Authorization", raw)

    def test_multiple_comment_pages_are_scanned_until_short_page(self):
        calls = []
        first = [comment("devflow", 20, n + 1, kaep=(n == 1))
                 for n in range(100)]
        def fetch(path):
            calls.append(path)
            if path.startswith("/users/"):
                return [repo("devflow")]
            if path.endswith("&page=1"):
                return first
            if path.endswith("&page=2"):
                return [comment("devflow", 22, 101)]
            self.fail(path)
        result = scan.discover(fetch=fetch, max_comment_pages=3)
        self.assertEqual(result["status"], "BOUNDED_PUBLIC_MARKER_READ")
        self.assertEqual(result["locator_count"], 2)
        self.assertEqual(len(calls), 3)
        self.assertIn("page=2", calls[-1])

    def test_partial_when_comment_page_limit_expires(self):
        def fetch(path):
            return [repo("devflow")] if path.startswith("/users/") else (
                [comment("devflow", 1, n + 1) for n in range(100)])
        out = scan.discover(fetch=fetch, max_comment_pages=1)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["locators"][0]["locator"], "devflow#1@1")
        self.assertEqual(out["incomplete_scopes"][0]["next_page"], 2)
        self.assertEqual(out["incomplete_scopes"][0]["reason_code"], "COMMENT_PAGE_CAP")
        self.assertFalse(out["absence_of_work_proven"])

    def test_private_or_mismatched_repo_metadata_is_never_scanned(self):
        for item in [repo("hidden", private=True),
                     {"full_name": "someone-else/project",
                      "owner": {"login": "someone-else"}, "private": False}]:
            with self.subTest(item=item):
                calls = []
                def fetch(path):
                    calls.append(path)
                    return [item]
                out = scan.discover(fetch=fetch)
                self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
                self.assertEqual(out["repository_count_observed"], 0)
                self.assertEqual(out["locators"], [])
                self.assertEqual(len(calls), 1)
                self.assertFalse(out["repository_enumeration_complete"])

    def test_cross_repository_comment_locator_mismatch_is_not_accepted(self):
        bad = comment("devflow", 3, 88)
        bad["issue_url"] = "https://api.github.com/repos/someone/other/issues/3"
        def fetch(path):
            return [repo("devflow")] if path.startswith("/users/") else [bad]
        out = scan.discover(fetch=fetch)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["locators"], [])
        self.assertEqual(out["incomplete_scopes"][0]["reason_code"],
                         "COMMENT_PAGE_UNKNOWN")

    def test_repositories_page_limit_never_proves_complete(self):
        names = [repo(f"public-{n}") for n in range(100)]
        calls = []
        def fetch(path):
            calls.append(path)
            return names if path.startswith("/users/") else []
        out = scan.discover(fetch=fetch, max_repo_pages=1)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["repository_count_observed"], 100)
        self.assertEqual(out["repositories_with_all_comment_pages_read"], 100)
        self.assertFalse(out["repository_enumeration_complete"])
        self.assertIn("REPOSITORY_PAGE_CAP",
                      [x["reason_code"] for x in out["incomplete_scopes"]])
        self.assertTrue(out["has_unknown_work"])

    def test_global_request_budget_marks_unread_repositories(self):
        def fetch(path):
            return [repo("a"), repo("b"), repo("c")] if path.startswith("/users/") else []
        out = scan.discover(fetch=fetch, max_repo_pages=1,
                            max_api_calls=2)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["repositories_with_all_comment_pages_read"], 1)
        self.assertEqual(out["api_requests_used"], 2)
        self.assertEqual([x["scope"] for x in out["incomplete_scopes"]],
                         [f"{OWNER}/b", f"{OWNER}/c"])
        self.assertFalse(out["complete_comment_pages_for_observed_public_repos"])

    def test_mid_repository_budget_marks_each_unread_scope_once(self):
        def fetch(path):
            if path.startswith("/users/"):
                return [repo("a"), repo("b")]
            if f"/{OWNER}/a/" in path:
                return [comment("a", 1, n+1) for n in range(100)]
            self.fail("second repo should not be fetched over budget")
        out = scan.discover(fetch=fetch, max_repo_pages=1,
                            max_comment_pages=3, max_api_calls=2)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["api_requests_used"], 2)
        self.assertEqual([(g["scope"], g["next_page"])
                          for g in out["incomplete_scopes"]],
                         [(f"{OWNER}/a", 2), (f"{OWNER}/b", 1)])
        self.assertFalse(out["absence_of_work_proven"])

    def test_failed_repo_comment_get_does_not_hide_other_repo_or_claim_empty(self):
        def fetch(path):
            if path.startswith("/users/"):
                return [repo("a"), repo("b")]
            if f"/{OWNER}/a/" in path:
                raise OSError("private failed network detail")
            return [comment("b", 4, 404)]
        out = scan.discover(fetch=fetch)
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["locators"][0]["locator"], "b#4@404")
        self.assertEqual(out["incomplete_scopes"][0]["scope"], f"{OWNER}/a")
        self.assertNotIn("private failed network detail", json.dumps(out))

    def test_invalid_bounds_rejected_before_get(self):
        for limits in [
            {"max_repo_pages": 0}, {"max_comment_pages": 101},
            {"max_api_calls": 0}, {"max_repo_pages": 3, "max_api_calls": 2},
        ]:
            with self.subTest(limits=limits):
                with self.assertRaisesRegex(Exception, "INVALID_SCAN_BOUNDS"):
                    scan.discover(fetch=lambda _: self.fail("network called"),
                                  **limits)

    def test_text_output_shows_only_locators_and_partial_diagnostics(self):
        report = {
            "status": "PARTIAL_UNKNOWN",
            "locators": [{"locator": "execution-coordinator#142@9001"}],
            "repository_count_observed": 3,
            "repositories_with_all_comment_pages_read": 2,
            "incomplete_scopes": [{"scope": f"{OWNER}/devflow",
                                   "next_page": 2, "reason_code": "COMMENT_PAGE_CAP"}],
        }
        with (mock.patch.object(scan, "discover", return_value=report),
              mock.patch("sys.stdout", new_callable=io.StringIO) as stream):
            code = scan.main(["--format", "lines"])
        self.assertEqual(code, 2)
        output = stream.getvalue()
        self.assertIn("execution-coordinator#142@9001", output)
        self.assertIn("PARTIAL_UNKNOWN", output)
        self.assertIn("UNKNOWN kinoko34077/devflow page=2", output)
