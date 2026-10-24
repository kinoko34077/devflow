"""Static contract checks for the fixed Identity OIDC recipient gate."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ".github/workflows/identity-oidc-recipient-pilot.yml"


class IdentityOidcRecipientWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / PATH).read_text(encoding="utf-8")

    def test_workflow_call_uses_numeric_owner_gate(self):
        self.assertIn("  workflow_call:", self.source)
        guard = self.source.split("    if: >-\n", 1)[1].split("\n    runs-on:", 1)[0]
        self.assertEqual(
            [part.strip() for part in guard.split("&&")],
            [
                "github.repository == 'kinoko34077/testapp'",
                "github.event_name == 'workflow_dispatch'",
                "github.ref == 'refs/heads/main'",
                "github.actor_id == '79015263'",
                "github.actor == 'kinoko34077'",
            ],
        )

    def test_recipient_keeps_narrow_fixed_oidc_boundary(self):
        self.assertIn("id-token: write", self.source)
        self.assertIn("EXPECTED_AUDIENCE: urn:kinotch:identity-read-pilot:v1", self.source)
        self.assertIn(
            "IDENTITY_ENDPOINT: https://api.kinotch.workers.dev/v1/identity/catalog/read",
            self.source,
        )
        self.assertIn("if (first !== 200 || replay !== 403) deny();", self.source)
        self.assertNotIn("secrets.", self.source)
        self.assertNotIn("console.log", self.source)
        self.assertNotIn("Authorization: 'Bearer ' + process.env", self.source)


if __name__ == "__main__":
    unittest.main()
