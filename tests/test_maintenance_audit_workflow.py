import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "maintenance-audit.yml"


class MaintenanceAuditWorkflowScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.audit = cls.text.split("\n  audit:\n", 1)[1].split(
            "\n  publish:\n", 1
        )[0]
        cls.publish = cls.text.split("\n  publish:\n", 1)[1]

    def test_daily_schedule_is_exact_and_non_cancelling(self):
        self.assertIn("schedule:", self.text)
        self.assertIn("- cron: '23 18 * * *'", self.text)
        self.assertIn("concurrency:", self.audit)
        self.assertIn(
            "group: maintenance-audit-${{ github.repository }}",
            self.audit,
        )
        self.assertIn("cancel-in-progress: false", self.audit)

    def test_schedule_can_enter_only_read_only_audit_job(self):
        self.assertIn(
            "if: ${{ github.event_name == 'schedule' || inputs.mode == 'audit' }}",
            self.audit,
        )
        self.assertIn(
            "if: ${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'publish' }}",
            self.publish,
        )
        self.assertIn("MAINTENANCE_AUDIT_TOKEN:", self.audit)
        self.assertNotIn("MAINTENANCE_SUPPLY_TOKEN:", self.audit)
        self.assertNotIn("MAINTENANCE_SYNC_TOKEN:", self.audit)
        self.assertNotIn("--apply", self.audit)

    def test_failure_evidence_remains_typed_and_uploaded(self):
        self.assertIn(
            "if: always() && hashFiles('maintenance-audit-report.json') != ''",
            self.audit,
        )
        self.assertIn("Upload machine report", self.audit)
        self.assertIn("maintenance-audit-report.json", self.audit)


if __name__ == "__main__":
    unittest.main()
