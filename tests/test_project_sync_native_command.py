"""Native GitHub Issue command transport may run Project Sync without an App key.

These contract tests intentionally do not dispatch a privileged workflow.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / ".github/workflows/project-sync.yml"


class NativeProjectSyncCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATH.read_text(encoding="utf-8")

    def test_preserves_existing_issue_and_manual_dispatch(self):
        self.assertIn("issues:\n    types: [opened, edited, reopened, closed]", self.source)
        self.assertIn("workflow_dispatch:", self.source)
        self.assertIn("issue_comment:\n    types: [created]", self.source)
        self.assertIn("if: github.event_name == 'issues' && github.event.issue.title", self.source)
        self.assertIn("inputs.mode", self.source)
        self.assertIn("inputs.issue_number", self.source)

    def test_job_level_guard_denies_untrusted_comments_and_prs(self):
        self.assertIn("github.repository == 'kinoko34077/devflow'", self.source)
        self.assertIn("github.event.issue.pull_request == null", self.source)
        self.assertIn("github.event.issue.user.id == 79015263", self.source)
        self.assertIn("github.event.comment.user.id == 79015263", self.source)
        self.assertIn("github.event.sender.id == 79015263", self.source)
        self.assertIn("github.event_name != 'issue_comment'", self.source)

    def test_only_fixed_full_scope_modes_are_executable(self):
        self.assertIn("github.event.comment.body == '/kinotch sync verify'", self.source)
        self.assertIn("github.event.comment.body == '/kinotch sync reconcile'", self.source)
        self.assertIn("'verify' || 'reconcile'", self.source)
        self.assertIn("if: github.event_name == 'workflow_dispatch' || github.event_name == 'issue_comment'", self.source)
        self.assertNotIn("${{ github.event.comment.body }}", self.source)
        self.assertIn('python scripts/project_sync.py "${args[@]}"', self.source)
        self.assertIn("ISSUE_NUMBER: ${{ inputs.issue_number }}", self.source)

    def test_privileged_job_is_serialized_without_new_permissions(self):
        self.assertIn("group: project-sync", self.source)
        self.assertEqual(self.source.count("    concurrency:"), 1)
        self.assertNotIn("\nconcurrency:\n", self.source)
        self.assertLess(self.source.index("    if: >-"), self.source.index("    concurrency:"))
        self.assertLess(self.source.index("    concurrency:"), self.source.index("    runs-on: ubuntu-latest"))
        self.assertIn("cancel-in-progress: false", self.source)
        self.assertIn("permissions:\n  contents: read\n  issues: write", self.source)
        self.assertEqual(self.source.count("PROJECTS_TOKEN: ${{ secrets.PROJECTS_TOKEN }}"), 2)
        self.assertNotIn("actions: write", self.source)
        self.assertNotIn("schedule:", self.source)


if __name__ == "__main__":
    unittest.main()
