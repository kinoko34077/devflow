import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReviewPolicyTextTests(unittest.TestCase):
    def test_operating_manual_uses_v2_default_review_contract(self):
        text = (ROOT / "docs/operations/AGENT_OPERATING_MANUAL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Reviewer != Implementer is NOT required by default.", text)
        self.assertIn("Review Provenance v2", text)
        self.assertNotIn("Independent Review is required when any of the following applies", text)
        self.assertNotIn("Every agent-produced formal Review uses Review Provenance v1", text)

    def test_issue_manual_accepts_implementer_authored_review_by_default(self):
        text = (ROOT / "docs/operations/REPOSITORY_ISSUE_MANUAL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("implementer-authored formal Review is valid by default", text)
        self.assertIn("Review Provenance v2", text)
        self.assertNotIn("Review Provenance v1", text)

    def test_pr_template_declares_gate_not_derived_relation(self):
        text = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
        self.assertIn("Formal review required: yes | no", text)
        self.assertIn("Different reviewer required: no | yes", text)
        self.assertNotIn("Required review role", text)


if __name__ == "__main__":
    unittest.main()
