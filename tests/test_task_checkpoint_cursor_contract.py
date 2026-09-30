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

    def test_durable_progress_policy_treats_cursor_as_optional_projection(self):
        text = (ROOT / "docs/operations/DURABLE_PROGRESS_EXTERNALIZATION.md").read_text(encoding="utf-8")
        self.assertIn("Task Checkpoint Cursor", text)
        self.assertIn("optional compact projection", text)
        self.assertIn("does not replace the durable progress surface", text)
        self.assertIn("frontier changes", text)
        self.assertIn("directly affected durable surface", text)

    def test_agents_resume_reads_cursor_before_historical_reconstruction(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Task Checkpoint Cursor", text)
        self.assertIn("first_unfinished", text)
        self.assertIn("before reconstructing historical checkpoint chronology", text)
        self.assertIn("readiness and safety gates", text)

    def test_machine_workflow_declares_projection_without_new_authority(self):
        text = (ROOT / ".devflow/WORKFLOW.yaml").read_text(encoding="utf-8")
        self.assertIn("task_checkpoint_cursor:", text)
        self.assertIn("status: optional_projection", text)
        self.assertIn("first_unfinished_projection: true", text)
        self.assertIn("single_frontier_only: true", text)
        self.assertIn("ordinary_drift_action: warn_and_reread", text)
        self.assertIn("readiness_authority: false", text)
        self.assertIn("claim_lease_fencing_authority: false", text)
        self.assertIn("github_project_is_display_only: true", text)


if __name__ == "__main__":
    unittest.main()
