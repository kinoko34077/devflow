import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK_ORDER_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "work-order.md"
CONTROL_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "repository-control.md"
REPOSITORY_ISSUE_MANUAL = ROOT / "docs" / "operations" / "REPOSITORY_ISSUE_MANUAL.md"


class WorkOrderTemplateContractTests(unittest.TestCase):
    def test_new_control_template_omits_redundant_current_state_heading(self):
        text = CONTROL_TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn("## Detailed Current State\n", text)
        for heading in ("## Active Work\n", "## Next Action\n", "## Canonical Entry Points\n", "## Control Notes\n"):
            self.assertIn(heading, text)

    def test_control_template_and_issue_manual_do_not_force_local_task_state_copy(self):
        template = CONTROL_TEMPLATE.read_text(encoding="utf-8")
        manual = REPOSITORY_ISSUE_MANUAL.read_text(encoding="utf-8")

        # Reverting to a per-local-Issue-update obligation would conflict with
        # the adopted source-of-truth and exact-Consumer R6/R7 migration policy.
        self.assertIn("Update this Control only when its independent", template)
        self.assertIn("do not require synchronized Control edits", template)
        self.assertIn("Human, security or policy decisions", template)
        self.assertNotIn("Update this Control when Audit SHA, state", template)

        self.assertIn("Do not update the Control merely because a local task", manual)
        self.assertIn("Required `Active Work` and `Next Action` headings", manual)
        self.assertIn("Human, security or policy gate/decision", manual)
        self.assertNotIn("Update the Control Issue when the local task changes:", manual)
        self.assertNotIn("When the local task finishes, replace stale active references", manual)

    def test_work_order_template_exposes_exact_project_sync_next_action_heading(self):
        text = WORK_ORDER_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("## Next Action\n", text)
        self.assertNotIn("## Current blocker / Next Action\n", text)


if __name__ == "__main__":
    unittest.main()
