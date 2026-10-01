import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TaskCheckpointCursorContractTests(unittest.TestCase):
    def test_operator_doc_defines_marker_and_warning_resume_contract(self):
        text = (ROOT / "docs/operations/TASK_CHECKPOINT_CURSOR.md").read_text(encoding="utf-8")
        self.assertIn("<!-- devflow-task-checkpoint-cursor:v1 -->", text)
        self.assertIn("first_unfinished", text)
        self.assertIn("WARN_CHECKPOINT_DRIFT", text)
        self.assertIn("WARN_REVISION_DRIFT", text)
        self.assertIn("WARN_POST_WRITE_DRIFT", text)
        self.assertIn("single canonical recovery frontier", text)
        self.assertIn("not readiness authority", text)
        self.assertIn("not claim, lease, lock, CAS, or fencing authority", text)
        self.assertNotIn("optional compact projection", text)

    def test_durable_progress_policy_pairs_detail_surface_with_cursor(self):
        text = (ROOT / "docs/operations/DURABLE_PROGRESS_EXTERNALIZATION.md").read_text(encoding="utf-8")
        self.assertIn("designated durable progress surface", text)
        self.assertIn("dedicated progress Issue / ledger", text)
        self.assertIn("Task Checkpoint Cursor", text)
        self.assertIn("use both layers together", text)
        self.assertIn("must not wait for the user to restate the progress Issue number", text)
        self.assertIn("frontier changes", text)
        self.assertIn("directly affected durable surface", text)

    def test_agents_resume_reads_cursor_before_historical_reconstruction(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Task Checkpoint Cursor", text)
        self.assertIn("first_unfinished", text)
        self.assertIn("before reconstructing historical checkpoint chronology", text)
        self.assertIn("readiness and safety gates", text)

    def test_machine_workflow_declares_dual_layer_projection_without_new_authority(self):
        text = (ROOT / ".devflow/WORKFLOW.yaml").read_text(encoding="utf-8")
        self.assertIn("task_checkpoint_cursor:", text)
        self.assertIn("status: required_when_eligible_single_frontier", text)
        self.assertIn("role: roadmap_and_current_frontier_projection", text)
        self.assertIn("detailed_progress_owner: designated_durable_progress_surface", text)
        self.assertIn("pairs_with_durable_progress_surface: true", text)
        self.assertIn("designated_progress_surface_must_be_discovered_and_consumed: true", text)
        self.assertIn("user_reminder_required_for_progress_surface_or_cursor: false", text)
        self.assertIn("dedicated_progress_issue_allowed: true", text)
        self.assertIn("first_unfinished_projection: true", text)
        self.assertIn("single_frontier_only: true", text)
        self.assertIn("ordinary_drift_action: warn_reread_and_reconcile_both_layers", text)
        self.assertIn("readiness_authority: false", text)
        self.assertIn("claim_lease_fencing_authority: false", text)
        self.assertIn("github_project_is_display_only: true", text)

    def test_current_main_reconciliation_uses_required_when_eligible_semantics(self):
        text = (ROOT / "docs/superpowers/specs/2026-09-30-task-checkpoint-cursor-v1-reconciliation.md").read_text(encoding="utf-8")
        self.assertIn("required for eligible single-frontier multi-step work", text)
        self.assertIn("operational gap", text)
        self.assertNotIn("Task Checkpoint Cursor v1 is an optional compact", text)


if __name__ == "__main__":
    unittest.main()
