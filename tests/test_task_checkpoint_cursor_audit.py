"""Snapshot-only, pagination-complete audit tests for #576."""
import unittest
from tools.task_checkpoint_cursor import CursorState, render_cursor_comment
from tools.task_checkpoint_cursor_audit import classify_cursor, audit_issue_ids, discover_open_issue_ids

REPO = "kinoko34077/devflow"
TASK = REPO + "#576"
STATE = CursorState(1, TASK, 1, "M0", "M1", "a"*40, (),
                    "2026-10-15T13:40:00Z")


def c(body, trusted=True):
    return {"id": 1, "body": body, "author_association": "OWNER" if trusted else "NONE",
            "user": {"login": "test"}}


class Fake:
    def __init__(self, comments):
        self.comments = comments
        self.calls = []
    def get_json(self, path):
        self.calls.append(path)
        n = int(path.split("/")[-1])
        return {"number": n, "html_url": "https://github.com/" + REPO + "/issues/" + str(n)}
    def get_paginated(self, path):
        self.calls.append(path)
        return list(self.comments)


class CursorAuditTests(unittest.TestCase):
    def test_good_and_normalizable(self):
        body = render_cursor_comment(STATE)
        self.assertEqual(classify_cursor(TASK, [c(body)])["status"], "PASS")
        frac = body.replace("2026-10-15T13:40:00Z", "2026-10-15T13:40:00.123Z")
        r = classify_cursor(TASK, [c(frac)])
        self.assertEqual(r["status"], "NORMALIZABLE")
        self.assertIn("WARN_NORMALIZED", r["warnings"])

    def test_missing_and_exemption_not_automatically_guessed(self):
        self.assertEqual(classify_cursor(TASK, [])["status"], "NEEDS_EVIDENCE")
        self.assertEqual(classify_cursor(TASK, [], eligible=True)["status"], "MISSING_ELIGIBLE")
        self.assertEqual(classify_cursor(TASK, [], eligible=False)["status"], "EXEMPT")

    def test_stale_only_when_verified_frontier_is_supplied(self):
        r = classify_cursor(TASK, [c(render_cursor_comment(STATE))],
                            verified_first_unfinished="M3")
        self.assertEqual(r["status"], "STALE_FRONTIER")
        plain = classify_cursor(TASK, [c(render_cursor_comment(STATE))])
        self.assertEqual(plain["status"], "PASS")
        self.assertFalse(plain["frontier_verified"])

    def test_duplicate_or_malformed_rejects_auto_decision(self):
        body = render_cursor_comment(STATE)
        self.assertEqual(classify_cursor(TASK, [c(body),c(body)])["status"], "TRUST_CONFLICT")
        self.assertEqual(classify_cursor(TASK, [c(body.replace("M1","BAD STAGE"))])["status"], "TRUST_CONFLICT")

    def test_full_bounded_collection_and_unknown_identity(self):
        fake = Fake([c(render_cursor_comment(STATE))])
        report = audit_issue_ids(fake, REPO, [576], expected={576:"M1"}, eligible={576:True})
        self.assertTrue(report["coverage_complete_for_explicit_set"])
        self.assertEqual(report["frontiers_independently_verified"], 1)
        self.assertTrue(report["semantic_coverage_complete"])
        self.assertFalse(report["mutation"])
        self.assertEqual(report["counts"]["PASS"], 1)
        self.assertEqual(len(fake.calls), 2)
        with self.assertRaises(ValueError):
            audit_issue_ids(fake, REPO, [576,576])
        with self.assertRaises(ValueError):
            audit_issue_ids(fake, REPO, list(range(1,103)))

    def test_untrusted_only_never_becomes_valid_or_missing_repair(self):
        body = render_cursor_comment(STATE)
        r = classify_cursor(TASK, [c(body, False)], eligible=True)
        self.assertEqual(r["status"], "TRUST_CONFLICT")
        self.assertIn("WARN_UNTRUSTED_MARKER", r["warnings"])

    def test_trusted_cursor_plus_untrusted_copy_is_not_format_only(self):
        body = render_cursor_comment(STATE)
        result = classify_cursor(TASK, [c(body), c(body, False)], eligible=True)
        self.assertEqual(result["cursor_code"], "OK_CURSOR")
        self.assertEqual(result["status"], "TRUST_CONFLICT")
        self.assertIn("WARN_UNTRUSTED_MARKER", result["warnings"])

    def test_format_diagnostics_remain_distinct_from_trust(self):
        body = render_cursor_comment(STATE)
        fractional = body.replace("2026-10-15T13:40:00Z", "2026-10-15T13:40:00.123Z")
        result = classify_cursor(TASK, [c(fractional)])
        self.assertEqual(result["status"], "NORMALIZABLE")
        self.assertFalse(result["frontier_verified"])

    def test_provenance_conflict_is_not_hidden_by_stale_frontier(self):
        body = render_cursor_comment(STATE)
        result = classify_cursor(
            TASK, [c(body), c(body, False)],
            verified_first_unfinished="M3",
        )
        self.assertEqual(result["status"], "TRUST_CONFLICT")
        self.assertIn("WARN_CHECKPOINT_DRIFT", result["warnings"])
        self.assertIn("WARN_UNTRUSTED_MARKER", result["warnings"])


    def test_discovery_coverage_and_pr_filter(self):
        class Discovery:
            def get_paginated(self, path):
                self.path = path
                return [
                    {"number": 10, "html_url": "https://github.com/example/issues/10"},
                    {"number": 11, "pull_request": {"url": "https://api.github.com"}},
                    {"number": 12},
                ]
        d = Discovery()
        self.assertEqual(discover_open_issue_ids(d, REPO), [10, 12])
        self.assertIn("state=open", d.path)
        with self.assertRaises(ValueError):
            discover_open_issue_ids(d, REPO, max_issues=1)



if __name__ == "__main__":
    unittest.main()
