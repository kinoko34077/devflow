from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryBootstrapPolicyTests(unittest.TestCase):
    def test_agents_routes_explicit_new_repository_requests_through_v1_contract(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("repository-bootstrap.v1", text)
        self.assertIn("[REPO CREATE] <repository-name>", text)
        self.assertIn("docs/operations/REPOSITORY_BOOTSTRAP.md", text)

    def test_machine_workflow_declares_bootstrap_request_control_and_human_gate(self):
        text = (ROOT / ".devflow" / "WORKFLOW.yaml").read_text(encoding="utf-8")
        self.assertIn("repository_bootstrap:", text)
        self.assertIn("repository-bootstrap.v1", text)
        self.assertIn("[REPO CREATE]", text)
        self.assertIn("REPOSITORY_BOOTSTRAP_TOKEN", text)
        self.assertIn("human_confirmation", text)

    def test_canonical_spec_distinguishes_create_request_from_repository_control(self):
        text = (ROOT / "docs" / "spec" / "CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md").read_text(encoding="utf-8")
        self.assertIn("Repository Bootstrap", text)
        self.assertIn("[REPO CREATE] <repository-name>", text)
        self.assertIn("[REPO] <repository-name>", text)
        self.assertIn("repository-bootstrap.v1", text)

    def test_operations_manual_documents_safe_defaults_and_credential_gate(self):
        text = (ROOT / "docs" / "operations" / "REPOSITORY_BOOTSTRAP.md").read_text(encoding="utf-8")
        self.assertIn("visibility", text)
        self.assertIn("private", text)
        self.assertIn("license", text)
        self.assertIn("Repository Base", text)
        self.assertIn("REPOSITORY_BOOTSTRAP_TOKEN", text)
        self.assertIn("Human Gate", text)
        self.assertIn("Idempotency", text)


if __name__ == "__main__":
    unittest.main()
