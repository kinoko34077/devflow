import json
import unittest
from pathlib import Path

from tools import development_reconciler as dr

try:
    from tools import maintenance_audit as ma
except ImportError:
    ma = None


FIXTURES = Path(__file__).parent / "fixtures" / "maintenance_audit"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class MaintenanceAuditTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ma, "maintenance_audit module must exist")

    def test_maintenance_engine_reuses_development_reconciliation_dispositions(self):
        self.assertEqual(ma.DISPOSITIONS, dr.DISPOSITIONS)
        self.assertEqual(set(ma.DISPOSITIONS), {
            "AUTO_ADVANCE", "NEEDS_REVIEWER", "NEEDS_RECOVERY",
            "NEEDS_HUMAN", "WAIT_EXTERNAL", "NEEDS_EVIDENCE", "NO_ACTION",
        })

    def test_missing_required_source_fails_closed(self):
        value = fixture("clean")
        del value["control"]
        with self.assertRaises(ma.AuditContractError):
            ma.normalize_observation(value)

    def test_identity_mismatch_fails_closed(self):
        value = fixture("clean")
        value["control"]["repository"] = "other/repo"
        with self.assertRaises(ma.AuditContractError):
            ma.normalize_observation(value)

    def test_duplicate_control_fails_closed(self):
        value = fixture("clean")
        value["control_count"] = 2
        with self.assertRaises(ma.AuditContractError):
            ma.normalize_observation(value)

    def test_untrusted_control_fails_closed(self):
        value = fixture("clean")
        value["control"]["trusted"] = False
        with self.assertRaises(ma.AuditContractError):
            ma.normalize_observation(value)

    def test_report_identity_ignores_observation_timestamp(self):
        first = fixture("clean")
        second = fixture("clean")
        second["observed_at"] = "2026-10-01T00:01:00Z"
        self.assertEqual(ma.classify_repository(first)["report_id"],
                         ma.classify_repository(second)["report_id"])

    def test_report_identity_changes_when_authoritative_revision_changes(self):
        first = fixture("clean")
        second = fixture("clean")
        second["control"]["revision"] = "b" * 40
        self.assertNotEqual(ma.classify_repository(first)["report_id"],
                            ma.classify_repository(second)["report_id"])

    def test_fixture_rules(self):
        cases = {
            "clean": ("NO_ACTION", None),
            "stale-control-owner-terminal": ("AUTO_ADVANCE", "CONTROL_ACTIVE_WORK_TERMINAL"),
            "active-producer-yield": ("NO_ACTION", "ACTIVE_PRODUCER_YIELD"),
            "reviewer-gate": ("NEEDS_REVIEWER", "REVIEW_GATE_YIELD"),
            "human-gate": ("NEEDS_HUMAN", "HUMAN_GATE_YIELD"),
            "source-unavailable": ("NEEDS_EVIDENCE", "SOURCE_UNAVAILABLE_OR_AMBIGUOUS"),
            "semantic-projection-suspected": ("NEEDS_EVIDENCE", "SEMANTIC_PROJECTION_SUSPECTED"),
            "search-stale-exact-terminal": ("AUTO_ADVANCE", "CONTROL_ACTIVE_WORK_TERMINAL"),
        }
        for name, (disposition, finding) in cases.items():
            with self.subTest(name=name):
                report = ma.classify_repository(fixture(name))
                self.assertEqual(report["disposition"], disposition)
                if finding is not None:
                    self.assertIn(finding, report["finding_classes"])

    def test_clean_has_no_synthetic_transition(self):
        report = ma.classify_repository(fixture("clean"))
        self.assertIsNone(report.get("next_transition"))

    def test_stale_control_proposes_bounded_sync_check_only(self):
        report = ma.classify_repository(fixture("stale-control-owner-terminal"))
        self.assertEqual(report["next_transition"], "WITHDRAW_STALE_CONTROL_CANDIDATE")

    def test_terminal_prose_owner_without_candidate_is_triage_only(self):
        value = fixture("stale-control-owner-terminal")
        value["control"]["candidate_present"] = False
        report = ma.classify_repository(value)
        self.assertEqual(report["disposition"], "NEEDS_EVIDENCE")
        self.assertIn(
            "SEMANTIC_PROJECTION_SUSPECTED",
            report["finding_classes"],
        )
        self.assertIsNone(report.get("next_transition"))

    def test_search_state_is_diagnostic_only(self):
        report = ma.classify_repository(fixture("search-stale-exact-terminal"))
        self.assertIn("SEARCH_STATE_STALE", report["reason_codes"])
        self.assertEqual(report["disposition"], "AUTO_ADVANCE")

    def test_portfolio_is_sorted_by_repository(self):
        values = [fixture("clean"), fixture("active-producer-yield")]
        values[0]["repository"] = "z/repo"
        values[0]["control"]["repository"] = "z/repo"
        values[0]["owner"]["repository"] = "z/repo"
        values[1]["repository"] = "a/repo"
        values[1]["control"]["repository"] = "a/repo"
        values[1]["owner"]["repository"] = "a/repo"
        reports = ma.classify_portfolio(values)
        self.assertEqual([r["repository"] for r in reports], ["a/repo", "z/repo"])


if __name__ == "__main__":
    unittest.main()
