from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "repository-bootstrap.yml"
CLI = ROOT / "scripts" / "repository_bootstrap.py"


class RepositoryBootstrapWorkflowTests(unittest.TestCase):
    def test_workflow_is_issue_event_only_and_has_required_types(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("issues:", text)
        self.assertIn("opened", text)
        self.assertIn("edited", text)
        self.assertIn("reopened", text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("schedule:", text)

    def test_validation_job_has_no_bootstrap_secret_and_provision_is_gated(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        validate_start = text.index("  validate:")
        provision_start = text.index("  provision:")
        validate_block = text[validate_start:provision_start]
        provision_block = text[provision_start:]

        self.assertNotIn("REPOSITORY_BOOTSTRAP_TOKEN", validate_block)
        self.assertIn("needs: validate", provision_block)
        self.assertIn("needs.validate.outputs.valid == 'true'", provision_block)
        self.assertIn("needs.validate.outputs.authorized == 'true'", provision_block)
        self.assertIn("REPOSITORY_BOOTSTRAP_TOKEN", provision_block)
        self.assertIn("secrets.REPOSITORY_BOOTSTRAP_TOKEN", provision_block)

    def test_external_actions_are_pinned_to_full_commit_sha(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        refs = re.findall(r"uses:\s*[^@\s]+@([^\s#]+)", text)
        self.assertGreaterEqual(len(refs), 2)
        for ref in refs:
            self.assertRegex(ref, r"^[0-9a-f]{40}$")

    def test_cli_exposes_validate_and_execute_without_embedding_secret_name_as_value(self):
        text = CLI.read_text(encoding="utf-8")
        self.assertIn("validate-event", text)
        self.assertIn("execute-event", text)
        self.assertIn("GITHUB_EVENT_PATH", text)
        self.assertIn("REPOSITORY_BOOTSTRAP_TOKEN", text)
        self.assertIn("DEVFLOW_TOKEN", text)
        self.assertNotRegex(text, r"REPOSITORY_BOOTSTRAP_TOKEN\s*=\s*['\"][^'\"]+['\"]")


if __name__ == "__main__":
    unittest.main()
