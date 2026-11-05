"""Project Sync native Issue command security contract.

These tests assert the new two-stage no-secret admission boundary without
invoking GitHub Actions or any privileged Project operation.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / ".github/workflows/project-sync.yml"
PREFLIGHT = ROOT / "tools/project_sync_event_admission.py"
SCRIPT = ROOT / "scripts/project_sync.py"


class NativeProjectSyncCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATH.read_text(encoding="utf-8")
        cls.admission = PREFLIGHT.read_text(encoding="utf-8")
        cls.cli = SCRIPT.read_text(encoding="utf-8")

    def test_preserves_existing_issue_and_manual_dispatch(self):
        self.assertIn("issues:\n    types: [opened, edited, reopened, closed]", self.source)
        self.assertIn("workflow_dispatch:", self.source)
        self.assertIn("issue_comment:\n    types: [created]", self.source)
        self.assertIn("if: github.event_name == 'issues' && github.event.issue.title", self.source)
        self.assertIn("inputs.mode", self.source)
        self.assertIn("inputs.issue_number", self.source)

    def test_before_secret_admission_denies_untrusted_comments_and_prs(self):
        self.assertIn("  actor-admission:", self.source)
        self.assertIn("needs: actor-admission", self.source)
        self.assertIn("needs.actor-admission.outputs.admitted == 'true'", self.source)
        self.assertIn("python tools/project_sync_event_admission.py", self.source)
        self.assertIn("project_sync_event_admission.admitted_from_env()", self.cli)
        self.assertIn("event_name == \"issue_comment\"", self.admission)
        self.assertIn('"pull_request" in issue', self.admission)
        self.assertIn("github_issue_trust.TRUSTED_PRINCIPAL_IDS", self.admission)
        self.assertIn("event.get(\"sender\")", self.admission)

    def test_only_fixed_full_scope_modes_are_executable(self):
        self.assertIn('COMMANDS = frozenset({"/kinotch sync verify", "/kinotch sync reconcile"})', self.admission)
        self.assertIn('inputs.get("mode") in {"verify", "reconcile"}', self.admission)
        self.assertIn("'verify' || 'reconcile'", self.source)
        self.assertIn("if: github.event_name == 'workflow_dispatch' || github.event_name == 'issue_comment'", self.source)
        self.assertNotIn("${{ github.event.comment.body }}", self.source)
        self.assertIn('python scripts/project_sync.py "${args[@]}"', self.source)
        self.assertIn("ISSUE_NUMBER: ${{ inputs.issue_number }}", self.source)

    def test_privileged_job_is_serialized_and_untrusted_has_no_project_secret(self):
        self.assertIn("group: project-sync", self.source)
        self.assertEqual(self.source.count("    concurrency:"), 1)
        self.assertNotIn("\nconcurrency:\n", self.source)
        part1, part2 = self.source.split("\n  sync:\n", 1)
        self.assertNotIn("PROJECTS_TOKEN", part1)
        self.assertNotIn("MAINTENANCE_AUDIT_TOKEN", part1)
        self.assertIn("    permissions:\n      contents: read", part1)
        self.assertNotIn("issues: write", part1)
        self.assertLess(part2.index("needs: actor-admission"), part2.index("concurrency:"))
        self.assertLess(part2.index("concurrency:"), part2.index("runs-on: ubuntu-latest"))
        self.assertIn("permissions:\n      contents: read\n      issues: write", part2)
        self.assertIn("cancel-in-progress: false", self.source)
        self.assertEqual(self.source.count("PROJECTS_TOKEN: ${{ secrets.PROJECTS_TOKEN }}"), 2)
        self.assertNotIn("actions: write", self.source)
        self.assertNotIn("schedule:", self.source)


if __name__ == "__main__":
    unittest.main()
