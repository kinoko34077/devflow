import json
import unittest
from pathlib import Path

try:
    from tools import development_reconciler as dr
    from tools import maintenance_audit as ma
except ImportError:
    dr = None
    ma = None

FIXTURES = Path(__file__).parent / "fixtures" / "maintenance_audit"


class MaintenanceAuditContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(dr)
        self.assertIsNotNone(ma)

    def test_maintenance_engine_reuses_development_reconciliation_dispositions(self):
        self.assertEqual(tuple(ma.DISPOSITIONS), tuple(dr.DISPOSITIONS))

    def test_missing_required_source_fails_closed(self):
        with self.assertRaises(ma.AuditContractError):
            ma.normalize_observation({"repository": "o/r"})

    def test_identity_mismatch_fails_closed(self):
        value = self.fixture("clean.json")
        value["control"]["repository"] = "other/repo"
        with self.assertRaises(ma.AuditContractError):
            ma.normalize_observation(value)

    def test_duplicate_control_fails_closed(self):
        value = self.fixture("clean.json")
        value["controls"] = [value.pop("control"), dict(value["control"]) if "control" in value else {}]
        with self.assertRaises(ma.AuditContractError):
            ma.normalize_observation(value)

    def test_untrusted_control_fails_closed(self):
        value = self.fixture("clean.json")
        value["control"]["trusted"] = False
        with self.assertRaises(ma.AuditContractError):
            ma.normalize_observation(value)

    def test_report_identity_ignores_observation_timestamp(self):
        value = self.fixture("clean.json")
        a = ma.classify_repository(value)
        value["observed_at"] = "2026-10-01T00:01:00Z"
        b = ma.classify_repository(value)
        self.assertEqual(a["report_id"], b["report_id"])

    def test_report_identity_changes_when_authoritative_revision_changes(self):
        value = self.fixture("clean.json")
        a = ma.classify_repository(value)
        value["control"]["revision"] = "sha256:changed"
        b = ma.classify_repository(value)
        self.assertNotEqual(a["report_id"], b["report_id"])

    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_clean_future_spec_is_no_action(self):
        report = ma.classify_repository(self.fixture("clean.json"))
        self.assertEqual(report["disposition"], "NO_ACTION")
        self.assertNotIn("next_transition", report)

    def test_terminal_owner_stale_control_proposes_sync_check(self):
        report = ma.classify_repository(self.fixture("stale-control-owner-terminal.json"))
        self.assertEqual(report["disposition"], "AUTO_ADVANCE")
        self.assertIn("CONTROL_ACTIVE_WORK_TERMINAL", report["finding_classes"])
        self.assertEqual(report["next_transition"], "WITHDRAW_STALE_CONTROL_CANDIDATE")

    def test_active_producer_yields(self):
        report = ma.classify_repository(self.fixture("active-producer-yield.json"))
        self.assertEqual(report["disposition"], "NO_ACTION")
        self.assertIn("ACTIVE_PRODUCER_YIELD", report["finding_classes"])

    def test_reviewer_gate_yields(self):
        report = ma.classify_repository(self.fixture("reviewer-gate.json"))
        self.assertEqual(report["disposition"], "NEEDS_REVIEWER")
        self.assertIn("REVIEW_GATE_YIELD", report["finding_classes"])

    def test_human_gate_yields(self):
        report = ma.classify_repository(self.fixture("human-gate.json"))
        self.assertEqual(report["disposition"], "NEEDS_HUMAN")
        self.assertIn("HUMAN_GATE_YIELD", report["finding_classes"])

    def test_source_unavailable_fails_closed(self):
        report = ma.classify_repository(self.fixture("source-unavailable.json"))
        self.assertEqual(report["disposition"], "NEEDS_EVIDENCE")
        self.assertIn("SOURCE_UNAVAILABLE_OR_AMBIGUOUS", report["finding_classes"])

    def test_semantic_projection_is_triage_only(self):
        report = ma.classify_repository(self.fixture("semantic-projection-suspected.json"))
        self.assertEqual(report["disposition"], "NEEDS_EVIDENCE")
        self.assertIn("SEMANTIC_PROJECTION_SUSPECTED", report["finding_classes"])
        self.assertNotIn("next_transition", report)

    def test_exact_terminal_truth_wins_over_stale_search(self):
        report = ma.classify_repository(self.fixture("search-stale-exact-terminal.json"))
        self.assertEqual(report["disposition"], "AUTO_ADVANCE")
        self.assertIn("SEARCH_INDEX_DISAGREES_WITH_EXACT", report["finding_classes"])


if __name__ == "__main__":
    unittest.main()
