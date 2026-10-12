"""R2 structure regression: separate writer cannot inherit producer authority."""
import pathlib
import unittest

FLOW = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/generated-artifact-rollout.yml"


class R2WorkflowTests(unittest.TestCase):
    def setUp(self):
        text = FLOW.read_text(encoding="utf-8")
        self.assertIn("\n  produce:\n", text)
        self.assertIn("\n  verify:\n", text)
        self.assertIn("\n  write:\n", text)
        self.produce = text.split("\n  produce:\n", 1)[1].split("\n  verify:\n", 1)[0]
        self.verify = text.split("\n  verify:\n", 1)[1].split("\n  write:\n", 1)[0]
        self.writer = text.split("\n  write:\n", 1)[1]

    def test_permissions_separate_and_never_shared_with_target_source(self):
        self.assertIn("permissions:\n      contents: read", self.produce)
        self.assertIn("permissions:\n      contents: read", self.verify)
        self.assertNotIn("contents: write", self.produce + self.verify)
        self.assertIn("permissions:\n      contents: write", self.writer)
        self.assertEqual((self.produce + self.verify + self.writer).count("contents: write"), 1)
        self.assertNotIn("secrets:", self.writer)

    def test_verifier_always_dry_run_and_writer_is_testapp_only(self):
        self.assertIn("MODE: dry-run", self.verify)
        self.assertIn("needs: verify", self.writer)
        self.assertIn("inputs.mode == 'write'", self.writer)
        self.assertIn("github.repository == 'kinoko34077/testapp'", self.writer)
        self.assertIn("inputs.recipe_id == 'testapp-public-fixture-v1'", self.writer)
        self.assertIn('[[ "$TARGET_BRANCH" == "artifact/writeback-testapp/e2e-20261012" ]]', self.writer)
        self.assertIn("MODE: write", self.writer)
        self.assertIn("generated_artifact_rollout_testapp_writer import main", self.writer)

    def test_writer_does_not_checkout_or_execute_untrusted_code(self):
        self.assertNotIn("actions/checkout@", self.writer)
        self.assertNotIn("npm ", self.writer)
        self.assertNotIn("setup-node", self.writer)
        self.assertNotIn("pip install", self.writer)
        self.assertNotIn("git push", self.writer)
        self.assertIn("python3 -I", self.writer)
        self.assertIn("git init -q devflow", self.writer)
        self.assertIn("test \"$(git -C devflow rev-parse HEAD)\" = \"$DEVFLOW_SHA\"", self.writer)


if __name__ == "__main__":
    unittest.main()
