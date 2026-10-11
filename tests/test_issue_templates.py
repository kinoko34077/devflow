import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK_ORDER_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "work-order.md"
CONTROL_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "repository-control.md"


class WorkOrderTemplateContractTests(unittest.TestCase):
    def test_new_control_template_omits_redundant_current_state_heading(self):
        text = CONTROL_TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn("## Detailed Current State\n", text)
        for heading in ("## Active Work\n", "## Next Action\n", "## Canonical Entry Points\n", "## Control Notes\n"):
            self.assertIn(heading, text)

    def test_work_order_template_exposes_exact_project_sync_next_action_heading(self):
        text = WORK_ORDER_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("## Next Action\n", text)
        self.assertNotIn("## Current blocker / Next Action\n", text)


if __name__ == "__main__":
    unittest.main()
