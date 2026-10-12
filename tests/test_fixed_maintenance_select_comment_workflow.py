"""Offline contract checks for one fixed R4 maintenance-selection ingress."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ".github/workflows/kinotch-fixed-maintenance-select-comment.yml"


class FixedMaintenanceSelectCommentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / PATH).read_text(encoding="utf-8")

    def test_only_new_issue_comment_event(self):
        self.assertRegex(self.source, r"(?m)^on:\s*\n  issue_comment:\s*\n    types: \[created\]")
        for forbidden in ("workflow_dispatch:", "repository_dispatch:", "pull_request_target:"):
            self.assertNotIn(forbidden, self.source)

    def test_exact_owner_issue_and_full_command_conjunction(self):
        guard = self.source.split("    if: >-\n", 1)[1].split("\n    runs-on:", 1)[0]
        conditions = [part.strip() for part in guard.split("&&")]
        self.assertEqual(conditions, [
            "github.repository == 'kinoko34077/devflow'",
            "github.event.issue.pull_request == null",
            "github.event.issue.number == 413",
            "github.event.issue.user.login == 'kinoko34077'",
            "github.event.comment.user.login == 'kinoko34077'",
            "github.event.sender.login == 'kinoko34077'",
            "github.actor == 'kinoko34077'",
            "github.event.comment.body == '/kinotch maintenance select devflow'",
        ])

    def test_only_one_readonly_job(self):
        self.assertEqual(self.source.count("\njobs:\n"), 1)
        jobs = self.source.split("\njobs:\n", 1)[1]
        self.assertEqual(
            re.findall(r"(?m)^  ([a-z][a-z0-9-]*):\s*$", jobs),
            ["select-devflow-maintenance"],
        )
        self.assertIn("\npermissions: {}\n", self.source)
        grant = self.source.split("    permissions:\n", 1)[1].split("\n    concurrency:", 1)[0]
        self.assertEqual([s.strip() for s in grant.strip("\n").splitlines()], [
            "contents: read", "issues: read", "pull-requests: read",
            "checks: read", "actions: read",
        ])

    def test_hardcoded_select_only_not_claim_or_publish(self):
        run = self.source.split("      - name: Select read-only maintenance candidate for devflow\n", 1)[1]
        run = run.split("\n      - name: Upload selection", 1)[0]
        for required in (
            "python scripts/maintenance_audit.py select-maintenance",
            "--repository kinoko34077/devflow",
            "--control 16",
            "--token-env GITHUB_TOKEN",
            "--output maintenance-selection.json",
        ):
            self.assertIn(required, run)
        for forbidden in ("github.event.", "comment.body", "--apply", "gh workflow run",
                          "claim", "publish-supply", "maintenance-publish", "--owner"):
            self.assertNotIn(forbidden, run)

    def test_no_additional_credentials_or_write_permissions(self):
        self.assertNotIn("secrets.", self.source)
        self.assertNotIn("MAINTENANCE_SUPPLY_TOKEN", self.source)
        self.assertNotIn("MAINTENANCE_AUDIT_TOKEN", self.source)
        self.assertEqual(self.source.count("$" + "{{ github.token }}"), 1)
        for forbidden in ("actions: write", "contents: write", "issues: write",
                          "pull-requests: write", "administration: write"):
            self.assertNotIn(forbidden, self.source)

    def test_action_pins_and_report(self):
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", self.source)
        self.assertIn("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", self.source)
        self.assertIn("actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9", self.source)
        self.assertIn("name: kinotch-fixed-maintenance-selection", self.source)
        self.assertIn("cancel-in-progress: false", self.source)

    def test_preserves_separate_accepted_audit_command(self):
        old = (ROOT / ".github/workflows/kinotch-fixed-audit-comment.yml").read_text(encoding="utf-8")
        self.assertIn("github.event.comment.body == '/kinotch audit devflow'", old)
        self.assertNotIn("/kinotch maintenance select devflow", old)
        self.assertNotIn("/kinotch audit devflow", self.source)


if __name__ == "__main__":
    unittest.main()
