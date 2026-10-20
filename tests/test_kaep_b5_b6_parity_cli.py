"""B5-B6 finite Consumer parity across already-produced reports (no GitHub)."""
from __future__ import annotations
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.kaep_b5_b6_parity_cli import compare_reports, main
from tools.kaep_inbox_reader import InvalidMessage

REPO = "kinoko34077/devflow"
ISSUE = f"https://github.com/{REPO}/issues/576"


def shadow(*, roots=((912, "msg_first"),), issue=ISSUE):
    return {
        "schema_version": "kaep.source-roster-shadow.v0.1",
        "status": "BOUNDED_CANDIDATE_SOURCE_READ",
        "recipient": "claude-code",
        "issues": [{
            "owning_issue": issue,
            "source_state": "AVAILABLE",
            "root_count": len(roots),
            "roots": [
                {"source_comment_id": cid, "source_message_id": mid,
                 "comparison": "ORIGINAL_ONLY"}
                for cid, mid in roots
            ],
        }],
        "errors": [], "read_only": True, "has_unknown_work": True,
        "complete_source_universe": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
    }


def union(*, roots=((912, "msg_first"),), issue=ISSUE):
    repo, num = issue.split("/issues/")
    repo = repo.removeprefix("https://github.com/")
    number = int(num)
    return {
        "schema_version": "kaep.live-union-check.v0.1",
        "kind": "REQUEST_TIME_ORIGINAL_ISSUE_UNION",
        "status": "BOUNDED_UNION_READ", "recipient": "claude-code",
        "source_candidates": [{
            "repository": repo, "issue_number": number,
            "issue_url": issue, "grants_work_authority": False,
            "source_observation": ("ACCEPTED_RECIPIENT_ROOTS" if roots else
                                   "NO_ACCEPTED_RECIPIENT_ROOT_OBSERVED"),
            "matching_recipient_roots": len(roots),
        }],
        "live_rows": [{
            "repository": repo, "issue_number": number,
            "issue_url": issue,
            "source_url": issue + f"#issuecomment-{cid}",
            "source_comment_id": cid, "message_id": mid,
            "recipient": "claude-code", "source_validation": "STRICT_COMPLETE_FOR_CANDIDATE",
        } for cid, mid in roots],
        "source_errors": [],
        "read_only": True, "has_unknown_work": True,
        "complete_source_universe": False,
        "can_authorize_execution": False,
        "recipient_pickup_proven": False,
        "fallback_retirement_authorized": False,
    }


class BoundedParityTests(unittest.TestCase):
    def test_same_issue_root_identity_matches_without_claiming_universe(self):
        report = compare_reports(shadow(), union())
        self.assertEqual(report["status"], "BOUNDED_SHARED_SOURCE_MATCH")
        self.assertEqual(report["shared_issue_compared"], 1)
        self.assertEqual(report["same_source_matches"][0]["issue_url"], ISSUE)
        self.assertEqual(report["same_source_matches"][0]["shadow_only_root_count"], 0)
        self.assertEqual(report["same_source_matches"][0]["union_only_root_count"], 0)
        self.assertFalse(report["source_universe_proven_complete"])
        self.assertFalse(report["same_snapshot_proven"])
        self.assertFalse(report["recipient_pickup_proven"])
        self.assertTrue(report["has_unknown_work"])
        self.assertFalse(report["can_authorize_execution"])

    def test_one_missing_root_is_observed_disagreement_not_executable(self):
        report = compare_reports(
            shadow(roots=((912, "msg_first"), (918, "msg_second"))),
            union())
        self.assertEqual(report["status"], "OBSERVED_DISAGREEMENT")
        self.assertEqual(report["same_source_disagreements"][0]["shadow_only_root_count"], 1)
        self.assertEqual(report["same_source_disagreements"][0]["union_only_root_count"], 0)
        self.assertFalse(report["same_snapshot_proven"])
        self.assertFalse(report["can_authorize_execution"])
        self.assertNotIn("msg_second", json.dumps(report))

    def test_different_message_ids_on_same_comment_are_not_called_same(self):
        report = compare_reports(
            shadow(roots=((912, "msg_first"),)),
            union(roots=((912, "msg_different"),)))
        self.assertEqual(report["status"], "OBSERVED_DISAGREEMENT")
        self.assertEqual(report["same_source_disagreements"][0]["shadow_only_root_count"], 1)
        self.assertEqual(report["same_source_disagreements"][0]["union_only_root_count"], 1)

    def test_other_issue_is_not_a_false_mismatch_or_fake_full_parity(self):
        other = f"https://github.com/{REPO}/issues/590"
        report = compare_reports(shadow(issue=ISSUE), union(issue=other))
        self.assertEqual(report["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(report["shared_issue_compared"], 0)
        self.assertEqual(report["shadow_only_issue_count"], 1)
        self.assertEqual(report["union_only_issue_count"], 1)
        self.assertEqual(report["same_source_matches"], [])
        self.assertFalse(report["source_universe_proven_complete"])

    def test_partial_source_or_error_excludes_invalid_shared_issue(self):
        a = shadow()
        b = union()
        b["source_candidates"][0]["source_observation"] = "SOURCE_VALIDATION_UNKNOWN"
        report = compare_reports(a, b)
        self.assertEqual(report["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(report["shared_issue_unknown"], 1)
        self.assertEqual(report["shared_issue_compared"], 0)
        a = shadow()
        a["status"] = "PARTIAL_UNKNOWN"
        a["errors"] = [{"owning_issue": ISSUE, "reason_code": "INVALID_FIELDS"}]
        out = compare_reports(a, union())
        self.assertEqual(out["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(out["shared_issue_unknown"], 1)

    def test_global_error_never_results_in_complete_claim(self):
        a = shadow()
        a["errors"] = [{"reason_code": "SOURCE_UNAVAILABLE"}]
        report = compare_reports(a, union())
        self.assertEqual(report["status"], "PARTIAL_UNKNOWN")
        self.assertFalse(report["source_universe_proven_complete"])

    def test_invalid_recipient_authority_urls_and_counts_fail_closed(self):
        for key, value in [
            ("recipient", "chatgpt"),
            ("can_authorize_execution", True),
            ("complete_source_universe", True),
            ("read_only", False),
        ]:
            with self.subTest(field=key):
                a = shadow()
                a[key] = value
                with self.assertRaises(InvalidMessage):
                    compare_reports(a, union())
        bad = shadow()
        bad["issues"][0]["owning_issue"] = "https://evil.invalid/issues/576"
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPORT_ISSUE_URL"):
            compare_reports(bad, union())
        bad = union()
        bad["source_candidates"][0]["issue_url"] = "https://evil.invalid/issues/576"
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPORT_ISSUE_URL"):
            compare_reports(shadow(), bad)
        bad = union()
        bad["source_candidates"][0]["matching_recipient_roots"] = 0
        with self.assertRaisesRegex(InvalidMessage, "INVALID_UNION_ROOT_COUNT"):
            compare_reports(shadow(), bad)

    def test_duplicate_roots_and_40_caps_fail_closed(self):
        bad = shadow(roots=((912, "msg_first"), (912, "msg_first")))
        with self.assertRaisesRegex(InvalidMessage, "INVALID_SHADOW_ROOT"):
            compare_reports(bad, union())
        bad = union(roots=((912, "msg_first"), (912, "msg_first")))
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_UNION_ROOT"):
            compare_reports(shadow(), bad)
        a = shadow()
        a["issues"] = a["issues"] * 41
        with self.assertRaisesRegex(InvalidMessage, "INVALID_SHADOW_REPORT"):
            compare_reports(a, union())
        b = union()
        b["source_candidates"] = b["source_candidates"] * 41
        with self.assertRaisesRegex(InvalidMessage, "INVALID_UNION_REPORT"):
            compare_reports(shadow(), b)

    def test_live_union_issue_url_error_excludes_only_affected_source(self):
        other = f"https://github.com/{REPO}/issues/590"
        a = shadow()
        a["issues"].append(shadow(issue=other)["issues"][0])
        b = union()
        extra = union(roots=(), issue=other)
        extra["source_candidates"][0]["source_observation"] = "SOURCE_VALIDATION_UNKNOWN"
        b["source_candidates"].append(extra["source_candidates"][0])
        b["status"] = "PARTIAL_UNKNOWN"
        # Real union output stores URL under issue_url, not owning_issue.
        b["source_errors"] = [{"issue_url": other, "reason_code": "INVALID_FIELDS"}]
        output = compare_reports(a, b)
        self.assertEqual(output["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(output["shared_issue_count"], 2)
        self.assertEqual(output["shared_issue_compared"], 1)
        self.assertEqual(output["shared_issue_unknown"], 1)
        self.assertEqual(len(output["same_source_matches"]), 1)

    def test_global_union_error_invalidates_all_provisional_comparisons(self):
        b = union()
        b["status"] = "PARTIAL_UNKNOWN"
        b["source_errors"] = [{"reason_code": "SOURCE_UNAVAILABLE", "issue_url": None}]
        report = compare_reports(shadow(), b)
        self.assertEqual(report["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(report["shared_issue_compared"], 0)
        self.assertEqual(report["shared_issue_unknown"], 1)
        self.assertEqual(report["same_source_matches"], [])

    def test_shadow_opt_in_40_distinct_issue_limit_matches_merged_shadow_contract(self):
        a = shadow()
        a["issues"] = [shadow(roots=(), issue=f"https://github.com/{REPO}/issues/{n}")["issues"][0]
                       for n in range(1, 41)]
        report = compare_reports(a, union(roots=(), issue=f"https://github.com/{REPO}/issues/1"))
        self.assertEqual(report["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(report["shadow_source_issues_observed"], 40)
        a["issues"].append(shadow(roots=(), issue=f"https://github.com/{REPO}/issues/41")["issues"][0])
        with self.assertRaisesRegex(InvalidMessage, "INVALID_SHADOW_REPORT"):
            compare_reports(a, union())

    def test_cli_offline_input_and_duplicate_json_key_safe_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            a = Path(temp) / "shadow.json"
            b = Path(temp) / "union.json"
            a.write_text(json.dumps(shadow()), encoding="utf-8")
            b.write_text(json.dumps(union()), encoding="utf-8")
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                status = main(["--shadow-report", str(a), "--union-report", str(b)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["status"],
                             "BOUNDED_SHARED_SOURCE_MATCH")
            a.write_text('{"schema_version":"a","schema_version":"b"}', encoding="utf-8")
            with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                status = main(["--shadow-report", str(a), "--union-report", str(b)])
            self.assertEqual(status, 2)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "BLOCKED")
            self.assertEqual(payload["reason_code"], "DUPLICATE_REPORT_FIELD")
            self.assertFalse(payload["can_authorize_execution"])


if __name__ == "__main__":
    unittest.main()
