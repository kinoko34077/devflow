"""F8E workflow deployment guard: static assertions, never start Actions or post."""
from pathlib import Path
import unittest

WF = Path(__file__).resolve().parents[1] / ".github/workflows/gpt-liveness-f8-manual.yml"


class F8ManualWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WF.read_text(encoding="utf-8")

    def test_no_auto_trigger_default_preview_only(self):
        triggers = self.text.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        self.assertIn("default: preview", triggers)
        for other in ("\n  push:", "\n  schedule:", "\n  issues:",
                      "\n  repository_dispatch:", "\n  issue_comment:",
                      "\n  pull_request:"):
            self.assertNotIn(other, triggers)

    def test_single_known_target_no_dynamic_operator_shell_splicing(self):
        self.assertIn("'kinoko34077/devflow#554'", self.text)
        self.assertIn("github.repository == 'kinoko34077/devflow'", self.text)
        self.assertIn("github.actor == 'kinoko34077'", self.text)
        self.assertIn("github.ref == 'refs/heads/main'", self.text)
        self.assertIn("inputs.operation == 'send'", self.text)
        self.assertIn("inputs.confirm_mailbox == 'kinoko34077/devflow#554'", self.text)
        self.assertNotIn("${{ inputs.", self.text)
        self.assertNotIn("execution-coordinator", self.text)

    def test_preview_cannot_write_send_receives_narrow_issue_rights(self):
        top, body = self.text.split("\njobs:\n", 1)
        self.assertIn("permissions:\n  contents: read", top)
        self.assertNotIn("issues: write", top)
        before_send, send_job = body.split("\n  send:\n", 1)
        self.assertIn("issues: read", before_send)
        self.assertNotIn("issues: write", before_send)
        self.assertIn("needs: [preview]", send_job)
        self.assertIn("issues: write", send_job)
        self.assertIn("--send --confirm-mailbox 'kinoko34077/devflow#554'", send_job)

    def test_sender_validates_authoritative_readback_result(self):
        self.assertIn('result["status"] == "SENT_AND_READ_BACK"', self.text)
        self.assertIn('result["readback_confirmed"] is True', self.text)
        self.assertIn('type(result["posted_comment_id"]) is int', self.text)
        self.assertIn("F8_MANUAL_NO_NEW_PING", self.text)
        self.assertIn("F8_MANUAL_READONLY_PREVIEW_PASS", self.text)

    def test_no_other_credential_or_automatic_process(self):
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("cron:", self.text)
        self.assertNotIn("cloudflare", self.text.casefold())
        self.assertEqual(self.text.count("GH_TOKEN: ${{ github.token }}"), 2)
        self.assertEqual(self.text.count("timeout-minutes: 3"), 2)
        self.assertEqual(self.text.count("persist-credentials: false"), 2)
        self.assertIn("cancel-in-progress: false", self.text)


if __name__ == "__main__":
    unittest.main()
