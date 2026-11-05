"""Snapshot-only, pagination-complete audit tests for #576."""
import unittest
from tools.task_checkpoint_cursor import CursorState, render_cursor_comment
from tools.task_checkpoint_cursor_audit import (classify_cursor, audit_issue_ids,
                                                discover_open_issue_ids,
                                                audit_open_issue_shards)

REPO = "kinoko34077/devflow"
TASK = REPO + "#576"
STATE = CursorState(1, TASK, 1, "M0", "M1", "a"*40, (),
                    "2026-10-15T13:40:00Z")


def c(body, trusted=True):
    return {"id": 1, "body": body, "author_association": "OWNER" if trusted else "NONE",
            "user": {"id": 79015263 if trusted else 123456789,
                     "login": "kinoko34077" if trusted else "test"}}


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




class ShardedFake:
    def __init__(self, ids, *, final_ids=None, missing=None, bad_owner=None):
        self.ids = list(ids)
        self.final_ids = list(ids if final_ids is None else final_ids)
        self.missing = missing
        self.bad_owner = bad_owner
        self.discoveries = 0
        self.issue_reads = []
    def get_paginated(self, path):
        if "/issues?state=open" in path:
            self.discoveries += 1
            ids = self.ids if self.discoveries == 1 else self.final_ids
            return [{"number": n, "state": "open"} for n in ids] + [
                {"number": 1000, "pull_request": {"url": "PR"}, "state": "open"}
            ]
        n = int(path.split("/issues/")[1].split("/")[0])
        if n == self.missing:
            return None
        return []
    def get_json(self, path):
        n = int(path.split("/")[-1])
        self.issue_reads.append(n)
        if n == self.bad_owner:
            return {"number": n, "pull_request": {"url": "PR"}}
        return {"number": n, "html_url": "https://github.com/" + REPO + "/issues/" + str(n)}


class ShardedCursorAuditTests(unittest.TestCase):
    def test_101_owners_complete_deterministic_and_unknown_not_semantic_pass(self):
        ids = list(range(1, 102))
        fake = ShardedFake(ids)
        report = audit_open_issue_shards(fake, REPO, shard_size=40)
        self.assertEqual(report["checked"], 101)
        self.assertEqual([s["count"] for s in report["shards"]], [40, 40, 21])
        self.assertEqual(report["counts"]["NEEDS_EVIDENCE"], 101)
        self.assertFalse(report["semantic_coverage_complete"])
        self.assertEqual(report["frontiers_independently_verified"], 0)
        self.assertEqual(report["eligibility_independently_supplied"], 0)
        self.assertTrue(report["coverage_complete_for_discovered_set"])
        self.assertFalse(report["snapshot_atomic"])
        self.assertEqual(fake.discoveries, 2)
        self.assertEqual(fake.issue_reads, ids)
        self.assertNotIn(1000, fake.issue_reads)
        again = audit_open_issue_shards(ShardedFake(list(reversed(ids))), REPO,
                                        shard_size=40)
        self.assertEqual(again["discovery_digest"], report["discovery_digest"])
        self.assertEqual(again["shards"], report["shards"])

    def test_oversize_invalid_duplicate_or_cohort_churn_fail_closed(self):
        cases = (
            ShardedFake(range(1, 102)),     # cap101
            ShardedFake([1, 1]),            # duplicates
            ShardedFake([1, 2], final_ids=[1, 3]),  # race
            ShardedFake([1, 2], missing=2), # missing paginated comments
            ShardedFake([1, 2], bad_owner=2),# unexpected PR in owner read
        )
        for fake in cases:
            with self.subTest(case=fake.__dict__), self.assertRaises(ValueError):
                audit_open_issue_shards(fake, REPO, max_total=100)
        for bad in (0, 101, True):
            with self.assertRaises(ValueError):
                audit_open_issue_shards(ShardedFake([1]), REPO, shard_size=bad)
        for bad in (0, 501, True):
            with self.assertRaises(ValueError):
                audit_open_issue_shards(ShardedFake([1]), REPO, max_total=bad)

    def test_shard_trust_conflict_is_not_lost_and_partial_semantic_claim_is_false(self):
        class Mixed(ShardedFake):
            def get_paginated(self, path):
                if "/issues?state=open" in path:
                    return super().get_paginated(path)
                n = int(path.split("/issues/")[1].split("/")[0])
                return [c(render_cursor_comment(STATE), trusted=False)] if n == 576 else []
        m = Mixed([575, 576, 577])
        report = audit_open_issue_shards(m, REPO, shard_size=1,
                                          eligible={575: False, 576: True},
                                          expected={576: "M1"})
        self.assertEqual(report["counts"]["TRUST_CONFLICT"], 1)
        self.assertEqual(report["counts"]["EXEMPT"], 1)
        self.assertEqual(report["counts"]["NEEDS_EVIDENCE"], 1)
        self.assertEqual(report["frontiers_independently_verified"], 1)
        self.assertFalse(report["semantic_coverage_complete"])
        self.assertEqual(report["eligibility_independently_supplied"], 2)



if __name__ == "__main__":
    unittest.main()
