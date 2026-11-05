"""Static regression checks for the R3 owner-comment audit workflow."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIVER_PATH = ".github/workflows/kinotch-fixed-audit-comment.yml"


class FixedAuditCommentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / RECEIVER_PATH).read_text(encoding="utf-8")

    def test_only_created_issue_comments_trigger(self):
        self.assertRegex(self.workflow, r"(?m)^on:\s*\n  issue_comment:\s*\n    types: \[created\]")
        self.assertNotIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("repository_dispatch:", self.workflow)
        self.assertNotIn("pull_request_target:", self.workflow)

    def test_all_trust_guards_are_and_conjoined(self):
        guard = self.workflow.split("    if: >-\n", 1)[1].split("\n    runs-on:", 1)[0]
        required = [
            "github.repository == 'kinoko34077/devflow'",
            "github.event.issue.pull_request == null",
            "github.event.issue.number == 413",
            "github.event.issue.user.id == 79015263",
            "github.event.comment.user.id == 79015263",
            "github.event.sender.id == 79015263",
            "github.actor_id == '79015263'",
            "github.event.comment.body == '/kinotch audit devflow'",
        ]
        self.assertEqual([part.strip() for part in guard.split("&&")], required)

    def test_exactly_one_job(self):
        self.assertEqual(self.workflow.count("\njobs:\n"), 1)
        self.assertEqual(
            len(re.findall(r"(?m)^  [a-z][a-z0-9-]*:\s*$", self.workflow.split("\njobs:\n", 1)[1])), 1
        )
        self.assertIn("  audit-devflow-control:\n", self.workflow)

    def test_default_permissions_empty_and_job_read_only(self):
        self.assertIn("\npermissions: {}\n", self.workflow)
        segment = self.workflow.split("    permissions:\n", 1)[1].split("\n    concurrency:", 1)[0]
        entries = [line.strip() for line in segment.strip("\n").splitlines()]
        self.assertEqual(entries, [
            "contents: read", "issues: read", "pull-requests: read", "checks: read", "actions: read"
        ])
        for forbidden in ("actions: write", "contents: write", "issues: write", "administration: write"):
            self.assertNotIn(forbidden, self.workflow)

    def test_fixed_readonly_command_no_event_interpolation(self):
        command = self.workflow.split("      - name: Audit only devflow Control 16 (read-only)\n", 1)[1]
        command = command.split("\n      - name: Summarize fixed audit", 1)[0]
        for required in (
            "python scripts/maintenance_audit.py repository",
            "--repository kinoko34077/devflow",
            "--control 16",
            "--token-env GITHUB_TOKEN",
            "--output maintenance-audit-report.json",
        ):
            self.assertIn(required, command)
        for forbidden in ("github.event.", "comment.body", "gh workflow run", "gh api"):
            self.assertNotIn(forbidden, command)

    def test_no_external_credentials_or_untrusted_shell(self):
        self.assertNotIn("secrets.", self.workflow)
        self.assertNotIn("MAINTENANCE_AUDIT_TOKEN", self.workflow)
        self.assertEqual(self.workflow.count("$" + "{{ github.token }}"), 1)
        self.assertNotIn("github.event.comment.body }}", self.workflow)
        self.assertNotIn("eval ", self.workflow)

    def test_pinned_actions_and_report(self):
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", self.workflow)
        self.assertIn("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", self.workflow)
        self.assertIn("actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9", self.workflow)
        self.assertIn("name: kinotch-fixed-audit-report", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)


if __name__ == "__main__":
    unittest.main()
