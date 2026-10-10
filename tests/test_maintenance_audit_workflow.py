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
        cls.publish = cls.text.split("\n  publish:\n", 1)[1].split(
            "\n  catalog-maintenance-publish:\n", 1
        )[0]
        cls.projection_cache = cls.text.split("\n  projection-cache:\n", 1)[1]

    def test_daily_schedule_is_exact_and_non_cancelling(self):
        self.assertIn("schedule:", self.text)
        self.assertIn("- cron: '30 13 * * *'", self.text)
        self.assertIn("concurrency:", self.audit)
        self.assertIn(
            "group: maintenance-audit-${{ github.repository }}",
            self.audit,
        )
        self.assertIn("cancel-in-progress: false", self.audit)

    def test_schedule_can_enter_only_read_only_audit_job(self):
        self.assertIn(
            "github.event.schedule == '30 13 * * *'",
            self.audit,
        )
        self.assertIn(
            "github.event_name == 'workflow_dispatch' && inputs.mode == 'audit'",
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

    def test_projection_cache_has_distinct_central_schedule_and_non_cancelling_concurrency(self):
        self.assertIn("- cron: '0 14 * * *'", self.text)
        self.assertIn(
            "github.event.schedule == '30 13 * * *'",
            self.audit,
        )
        self.assertIn(
            "github.event.schedule == '0 14 * * *'",
            self.projection_cache,
        )
        self.assertIn(
            "group: repository-projection-cache-${{ github.repository }}",
            self.projection_cache,
        )
        self.assertIn("cancel-in-progress: false", self.projection_cache)
        self.assertNotIn("schedule:", self.publish)

    def test_scheduled_projection_cache_uses_fleet_mode_without_target_inputs(self):
        self.assertIn("--fleet", self.projection_cache)
        self.assertIn("github.event_name == 'schedule'", self.projection_cache)
        self.assertIn(
            "github.event_name == 'workflow_dispatch' && inputs.mode == 'projection-cache'",
            self.projection_cache,
        )
        self.assertIn("issues: write", self.projection_cache)
        self.assertNotIn("MAINTENANCE_SUPPLY_TOKEN", self.projection_cache)

    def test_manual_projection_cache_without_target_reuses_same_central_fleet_job(self):
        self.assertIn(
            '-z "$CACHE_REPOSITORY" && -z "$CACHE_CONTROL"',
            self.projection_cache,
        )
        self.assertIn(
            'requires both repository and control, or neither for fleet mode',
            self.projection_cache,
        )
    def test_manual_maintenance_select_is_read_only(self):
        self.assertIn("- maintenance-select", self.text)
        self.assertIn("inputs.mode == 'maintenance-select'", self.text)
        select_job = self.text.split("\n  maintenance-select:\n", 1)[1].split("\n  publish:\n", 1)[0]
        self.assertIn("python scripts/maintenance_audit.py select-maintenance", select_job)
        self.assertIn("maintenance-selection.json", select_job)
        self.assertNotIn("--apply", select_job)
        self.assertNotIn("issues: write", select_job)
        self.assertNotIn("MAINTENANCE_SUPPLY_TOKEN", select_job)

    def test_manual_portfolio_maintenance_select_is_read_only(self):
        self.assertIn("- maintenance-select-portfolio", self.text)
        self.assertIn("inputs.mode == 'maintenance-select-portfolio'", self.text)
        select_job = self.text.split("\n  maintenance-select:\n", 1)[1].split(
            "\n  publish:\n",
            1,
        )[0]
        self.assertIn(
            "python scripts/maintenance_audit.py select-maintenance-portfolio",
            select_job,
        )
        self.assertIn("maintenance-selection.json", select_job)
        self.assertNotIn("--apply", select_job)
        self.assertNotIn("issues: write", select_job)
        self.assertNotIn("MAINTENANCE_SUPPLY_TOKEN", select_job)

    def test_manual_catalog_publish_and_withdraw_modes_are_explicit_and_not_scheduled(self):
        self.assertIn("- maintenance-publish", self.text)
        self.assertIn("- maintenance-withdraw", self.text)
        self.assertIn("inputs.mode == 'maintenance-publish'", self.text)
        self.assertIn("inputs.mode == 'maintenance-withdraw'", self.text)
        job = self.text.split("\n  catalog-maintenance-publish:\n", 1)[1].split(
            "\n  projection-cache:\n",
            1,
        )[0]
        self.assertIn("MAINTENANCE_SUPPLY_TOKEN", job)
        self.assertIn("publish-maintenance", job)
        self.assertIn("withdraw-maintenance", job)
        self.assertIn("--apply", job)
        self.assertNotIn("schedule:", job)
        self.assertNotIn("issues: write", job)

    def test_manual_trusted_catalog_completion_is_dispatch_only_and_fail_closed(self):
        self.assertIn('- maintenance-complete', self.text)
        self.assertIn("inputs.mode == 'maintenance-complete'", self.text)
        job = self.text.split('\n  catalog-maintenance-complete:\n', 1)[1].split(
            '\n  projection-cache:\n', 1
        )[0]
        self.assertIn("github.event_name == 'workflow_dispatch'", job)
        self.assertNotIn('schedule:', job)
        self.assertIn('issues: read', job)
        self.assertNotIn('issues: write', job)
        self.assertIn('MAINTENANCE_SUPPLY_TOKEN: ${{ secrets.MAINTENANCE_SUPPLY_TOKEN }}', job)
        self.assertNotIn('GITHUB_TOKEN:', job)
        self.assertIn('python scripts/maintenance_audit.py complete-maintenance', job)
        self.assertIn('--token-env MAINTENANCE_SUPPLY_TOKEN', job)
        self.assertIn('--apply', job)
        self.assertIn('cancel-in-progress: false', job)
        self.assertIn(
            'group: catalog-maintenance-publish-${{ github.repository }}-${{ inputs.repository }}',
            job,
        )
        self.assertIn('maintenance-completion-result.json', job)
        self.assertIn('Upload typed completion result', job)

    def test_completion_argument_boundary_uses_env_and_rejects_unbounded_inputs(self):
        job = self.text.split('\n  catalog-maintenance-complete:\n', 1)[1].split(
            '\n  projection-cache:\n', 1
        )[0]
        for field in ('repository', 'control', 'run_id', 'lens', 'result',
                      'owner', 'evidence_ref', 'attempt_id'):
            self.assertIn('inputs.' + field, job)
        self.assertIn('invalid_input()', job)
        self.assertIn('INVALID_INPUT', job)
        self.assertIn('MAINTENANCE_EVIDENCE_REF', job)
        self.assertIn('MAINTENANCE_RUN_ID', job)
        self.assertIn('MAINTENANCE_RESULT', job)
        self.assertIn('MAINTENANCE_FINDINGS_SUMMARY: ${{ inputs.owner }}', job)
        self.assertIn('${#MAINTENANCE_FINDINGS_SUMMARY} -le 512', job)
        self.assertIn('"$MAINTENANCE_EVIDENCE_REF"', job)
        self.assertIn('"$MAINTENANCE_FINDINGS_SUMMARY"', job)
        self.assertNotIn('${{ inputs.', job.split('        run: |', 1)[1])

    def test_dispatch_keeps_at_most_ten_top_level_inputs(self):
        section = self.text.split('  workflow_dispatch:\n    inputs:\n', 1)[1].split('\npermissions:', 1)[0]
        keys = [line for line in section.splitlines() if line.startswith('      ') and line.rstrip().endswith(':') and not line.startswith('        ')]
        self.assertLessEqual(len(keys), 10)
        self.assertEqual(len(keys), len(set(keys)))
    def test_completion_mode_does_not_modify_existing_read_only_audit(self):
        self.assertNotIn('complete-maintenance', self.audit)
        self.assertNotIn('MAINTENANCE_SUPPLY_TOKEN:', self.audit)
        self.assertNotIn('maintenance-complete', self.publish)

    def test_failure_evidence_remains_typed_and_uploaded(self):
        self.assertIn(
            "if: always() && hashFiles('maintenance-audit-report.json') != ''",
            self.audit,
        )
        self.assertIn("Upload machine report", self.audit)
        self.assertIn("maintenance-audit-report.json", self.audit)


if __name__ == "__main__":
    unittest.main()
