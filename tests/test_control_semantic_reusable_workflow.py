"""Reusable workflow permission and scope assertions (#726)."""
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / ".github/workflows/control-semantic-reusable.yml").read_text(encoding="utf-8")

class ReusableWorkflowTests(unittest.TestCase):
    def test_only_explicit_caller_and_merge(self):
        self.assertIn("  workflow_call:", SOURCE)
        self.assertIn("github.event.pull_request.merged == true", SOURCE)
        self.assertIn("startsWith(github.repository", SOURCE)
        for denied in ("pull_request_target:", "schedule:", "workflow_dispatch:", "repository_dispatch:"):
            self.assertNotIn(denied, SOURCE)

    def test_pinned_shared_source_and_read_only_token(self):
        self.assertIn("repository: kinoko34077/devflow", SOURCE)
        self.assertIn("inputs.source_sha", SOURCE)
        self.assertIn("^[0-9a-f]{40}$", SOURCE)
        self.assertIn("persist-credentials: false", SOURCE)
        self.assertIn("permissions:\n  contents: read\n  issues: read\n  pull-requests: read", SOURCE)
        self.assertIn("github.token", SOURCE)
        self.assertIn("--control \"$CONTROL_ISSUE\"", SOURCE)
        self.assertIn("--repository \"$GITHUB_REPOSITORY\"", SOURCE)
        for denied in ("contents: write", "issues: write", "pull-requests: write", "secrets.", "gh issue edit", "git push"):
            self.assertNotIn(denied, SOURCE)

if __name__ == "__main__":
    unittest.main()
