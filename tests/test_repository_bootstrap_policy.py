from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryBootstrapPolicyTests(unittest.TestCase):
    def test_agents_routes_explicit_new_repository_requests_through_v1_contract(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("repository-bootstrap.v1", text)
        self.assertIn("[REPO CREATE] <repository-name>", text)
        self.assertIn("docs/operations/REPOSITORY_BOOTSTRAP.md", text)
        self.assertIn("docs/spec/REPOSITORY_BOOTSTRAP.md", text)

    def test_machine_workflow_declares_bootstrap_request_control_and_human_gate(self):
        text = (ROOT / ".devflow" / "WORKFLOW.yaml").read_text(encoding="utf-8")
        self.assertIn("repository_bootstrap:", text)
        self.assertIn("repository-bootstrap.v1", text)
        self.assertIn("[REPO CREATE]", text)
        self.assertIn("REPOSITORY_BOOTSTRAP_TOKEN", text)
        self.assertIn("human_confirmation", text)

    def test_canonical_spec_distinguishes_create_request_from_repository_control(self):
        text = (ROOT / "docs" / "spec" / "REPOSITORY_BOOTSTRAP.md").read_text(encoding="utf-8")
        self.assertIn("Repository Bootstrap", text)
        self.assertIn("[REPO CREATE] <repository-name>", text)
        self.assertIn("[REPO] <repository-name>", text)
        self.assertIn("repository-bootstrap.v1", text)

    def test_canonical_spec_and_operations_manual_define_the_same_freshness_fence(self):
        spec = (ROOT / "docs" / "spec" / "REPOSITORY_BOOTSTRAP.md").read_text(encoding="utf-8")
        operations = (ROOT / "docs" / "operations" / "REPOSITORY_BOOTSTRAP.md").read_text(encoding="utf-8")
        for text in (spec, operations):
            normalized_text = " ".join(text.split())
            self.assertIn("Current request freshness", normalized_text)
            self.assertIn("`updated_at`", normalized_text)
            self.assertIn("`DEVFLOW_TOKEN`", normalized_text)
            self.assertIn("`REPOSITORY_BOOTSTRAP_TOKEN`", normalized_text)
            self.assertIn("The workflow injects `REPOSITORY_BOOTSTRAP_TOKEN` into the gated provision step environment before Python performs the final Issue recheck.", normalized_text)
            self.assertIn("A failed final check prevents Python from reading or using that value and from constructing the executor; it does not mean the credential was absent from the step environment.", normalized_text)
            self.assertIn("not an atomic compare-and-swap", normalized_text)
            self.assertIn("Re-running a stale or closed historical snapshot is expected to fail freshness checks", normalized_text)
            self.assertIn("an unchanged open snapshot remains retryable", normalized_text)
        self.assertIn("positive numeric Issue ID", spec)
        self.assertIn("repeat the current-Issue comparison and trusted author check", spec)
        self.assertIn("current Issue identity, its `[REPO CREATE]` title, and trusted author", spec)
        self.assertIn("read failures and unverified identities", spec)
        self.assertIn("stale revision prevents Python from reading or using that external credential", " ".join(operations.split()))

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
