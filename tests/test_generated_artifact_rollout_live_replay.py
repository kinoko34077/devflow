"""R2 single-attempt receipt replay workflow guardrails (non-production testapp only)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/generated-artifact-rollout.yml"


class SameReceiptWorkflowTests(unittest.TestCase):
    def setUp(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        pre, self.writer = content.split("\n  write:\n", 1)
        self.producer, self.verify = pre.split("\n  verify:\n", 1)

    def test_privileged_scope_is_only_testapp_after_readonly_verification(self):
        self.assertNotIn("contents: write", self.producer)
        self.assertNotIn("contents: write", self.verify)
        self.assertIn("MODE: dry-run", self.verify)
        self.assertIn("needs: verify", self.writer)
        self.assertIn("github.repository == 'kinoko34077/testapp'", self.writer)
        self.assertIn("contents: write", self.writer)
        self.assertIn("test \"$GITHUB_REF\" = \"refs/heads/main\"", self.writer)
        for marker in ("actions/checkout@", "npm run ", "pip install", "secrets: inherit"):
            self.assertNotIn(marker, self.writer)

    def test_two_calls_are_same_pinned_api_entry_and_same_job(self):
        invocation = "from tools.generated_artifact_rollout_testapp_write import main"
        self.assertEqual(self.writer.count(invocation), 2)
        self.assertEqual(self.writer.count("python3 -I -c "), 2)
        self.assertIn('tee "$RUNNER_TEMP/writeback-first.json"', self.writer)
        self.assertIn('tee "$RUNNER_TEMP/writeback-replay.json"', self.writer)
        self.assertIn('test "$GITHUB_REPOSITORY" = "kinoko34077/testapp"', self.writer)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', self.writer)
        self.assertIn("Same Actions run ID/attempt", self.writer)
        self.assertEqual(self.writer.count("GITHUB_RUN_ATTEMPT"), 0)

    def test_replay_is_asserted_not_merely_logged(self):
        self.assertIn('replay.get("status") == "NO_OP_REPLAY"', self.writer)
        self.assertIn('replay.get("target_head") == first.get("new_head")', self.writer)
        self.assertIn('replay.get("writes_performed") is False', self.writer)
        self.assertIn('first.get("producer_run_id") == replay.get("producer_run_id")', self.writer)
        self.assertIn('replay.get("file_count") == 1', self.writer)
        self.assertIn('elif first.get("status") == "NO_OP"', self.writer)
        self.assertIn("ACCEPTED: exact same-receipt idempotence", self.writer)


if __name__ == "__main__":
    unittest.main()
