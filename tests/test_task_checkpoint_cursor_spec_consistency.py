import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "docs/superpowers/specs/2026-09-29-task-checkpoint-cursor-design.md"
RECONCILIATION = ROOT / "docs/superpowers/specs/2026-09-30-task-checkpoint-cursor-v1-reconciliation.md"


class TaskCheckpointCursorSpecConsistencyTests(unittest.TestCase):
    def test_design_declares_accepted_implementation_state(self):
        text = DESIGN.read_text(encoding="utf-8")
        self.assertIn("Status: Accepted design", text)
        self.assertIn("PR #257", text)
        self.assertIn("PR #261", text)
        self.assertNotIn("Status: Proposed written specification for review", text)

    def test_design_example_uses_full_exact_head(self):
        text = DESIGN.read_text(encoding="utf-8")
        self.assertIn("head: 0123456789abcdef0123456789abcdef01234567", text)
        self.assertNotIn("head: abcdef1234567890\n", text)

    def test_design_records_accepted_canonical_validation_hardening(self):
        text = DESIGN.read_text(encoding="utf-8")
        self.assertIn("canonical positive base-10 decimal", text)
        self.assertIn("may not contain the cursor sentinel", text)
        self.assertIn("no-op frontier", text)
        self.assertIn("explicit `reconcile`", text)

    def test_reconciliation_labels_historical_base_and_initial_review_boundary(self):
        text = RECONCILIATION.read_text(encoding="utf-8")
        self.assertIn("Implementation base at reconciliation", text)
        self.assertNotIn("Current accepted devflow base", text)
        self.assertIn("Initial v1 acceptance", text)
        self.assertIn("Later bounded maintenance", text)


if __name__ == "__main__":
    unittest.main()
