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


if __name__ == "__main__":
    unittest.main()
