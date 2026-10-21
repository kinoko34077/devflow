"""Static security/trigger tests for devflow-only PR merge semantic pilot."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YAML = ROOT / ".github/workflows/control-semantic-postmerge.yml"


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = YAML.read_text(encoding="utf-8")

    def test_only_closed_pr_event_not_issue_comment_or_dispatch(self):
        self.assertRegex(
            self.text,
            r"(?m)^on:\s*\n  pull_request:\s*\n    types: \[closed\]",
        )
        for absent in ("pull_request_target:", "workflow_dispatch:", "repository_dispatch:", "issue_comment:", "schedule:"):
            self.assertNotIn(absent, self.text)

    def test_event_guard_is_exact_owner_and_actual_merge(self):
        guard = self.text.split("    if: >-\n", 1)[1].split(
            "\n    runs-on:", 1
        )[0]
        self.assertEqual(
            [x.strip() for x in guard.split("&&")],
            [
                "github.repository == 'kinoko34077/devflow'",
                "github.event.pull_request.merged == true",
            ],
        )

    def test_read_only_permissions_and_no_privileged_checkout(self):
        self.assertIn("\npermissions:\n  contents: read\n  issues: read\n  pull-requests: read\n", self.text)
        self.assertIn("persist-credentials: false", self.text)
        for denied in ("contents: write", "issues: write", "pull-requests: write",
                       "administration: write", "secrets.", "actions: write", "pull_request_target"):
            self.assertNotIn(denied, self.text)

    def test_one_read_only_script_and_explicit_producer_visibility(self):
        self.assertIn("python -m tools.control_semantic_postmerge_event", self.text)
        self.assertIn("--event-path \"$GITHUB_EVENT_PATH\"", self.text)
        self.assertIn("--repository \"$GITHUB_REPOSITORY\"", self.text)
        self.assertIn("exit \"$status\"", self.text)
        self.assertIn("GITHUB_STEP_SUMMARY", self.text)
        self.assertIn("NOT_APPLICABLE, not ALIGNED", self.text)
        self.assertEqual(len(re.findall(r"(?m)^  [a-z-]+:\s*$", self.text.split("\njobs:\n")[1])), 1)

    def test_no_sync_or_automatic_control_writeback(self):
        for forbidden in (
            "gh issue edit", "gh api --method PATCH", "workflow_dispatch",
            "control_semantic_pilot --require-aligned",
            "git push", "GITHUB_TOKEN: " + "$" + "{{ secrets.",
        ):
            self.assertNotIn(forbidden, self.text)


if __name__ == "__main__":
    unittest.main()
