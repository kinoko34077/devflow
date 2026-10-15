"""Static least-privilege and manual-only contract for #576 audit pilot."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "task-cursor-audit.yml"


class TaskCursorAuditWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_manual_dispatch_only(self):
        s = self.source
        self.assertIn("\non:\n  workflow_dispatch:\n", s)
        self.assertNotIn("  schedule:", s)
        self.assertNotIn("  pull_request:", s)
        self.assertNotIn("  push:", s)

    def test_read_only_permissions_and_fixed_repo(self):
        s = self.source
        self.assertIn("permissions:\n  contents: read\n  issues: read\n", s)
        self.assertNotIn("issues: write", s)
        self.assertNotIn("contents: write", s)
        self.assertNotIn("actions: write", s)
        self.assertNotIn("secrets.", s)
        self.assertIn("--repository kinoko34077/devflow", s)

    def test_numeric_input_is_env_and_bounded(self):
        s = self.source
        self.assertIn("ISSUE_INPUT: ${{ inputs.issue }}", s)
        self.assertIn('[[ ! "$ISSUE_INPUT" =~ ^[1-9][0-9]{0,5}$ ]]', s)
        self.assertIn('--issue "$CURSOR_AUDIT_ISSUE"', s)
        self.assertIn("timeout-minutes: 5", s)

    def test_pinned_actions_and_no_untrusted_runner_source(self):
        s = self.source
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", s)
        self.assertIn("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", s)
        self.assertNotIn("curl ", s)
        self.assertNotIn("pip install ", s)


if __name__ == "__main__":
    unittest.main()
