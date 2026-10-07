import unittest
from pathlib import Path

from tools import chat_worker_bootstrap as cwb


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".devflow" / "WORKFLOW.yaml"
AGENTS = ROOT / "AGENTS.md"
BOOTSTRAP = ROOT / "docs" / "spec" / "CHAT_WORKER_BOOTSTRAP.md"
INTEGRATION = ROOT / "docs" / "operations" / "CHAT_WORKER_INTEGRATION.md"
MAINTENANCE = ROOT / "docs" / "operations" / "MAINTENANCE_AUDIT.md"


class StandingMaintenanceFallbackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.documents = [
            AGENTS.read_text(encoding="utf-8"),
            BOOTSTRAP.read_text(encoding="utf-8"),
            INTEGRATION.read_text(encoding="utf-8"),
            MAINTENANCE.read_text(encoding="utf-8"),
        ]
        cls.joined = "\n".join(cls.documents)

    def test_workflow_publishes_standing_maintenance_policy(self):
        self.assertIn("standing_maintenance:", self.workflow)
        self.assertIn("rollout_values:", self.workflow)
        for value in ("DISABLED", "PILOT", "ENABLED"):
            self.assertIn(f"- {value}", self.workflow)
        self.assertIn("bootstrap_v1_classifier_unchanged: true", self.workflow)
        self.assertIn("repository_scope_auto_widen: forbidden", self.workflow)
        self.assertIn("publication_requires_new_execution_attempt: true", self.workflow)

    def test_generic_broad_work_has_outer_fallback_order(self):
        expected = (
            "recoverable_work",
            "normal_runnable_work",
            "predefined_maintenance",
            "alternate_or_deeper_maintenance",
            "portfolio_maintenance",
            "NO_ELIGIBLE_WORK",
        )
        cursor = -1
        for item in expected:
            next_cursor = self.workflow.find(f"- {item}", cursor + 1)
            self.assertGreater(next_cursor, cursor, item)
            cursor = next_cursor

    def test_repository_scoped_broad_work_never_silently_widens(self):
        for document in self.documents:
            self.assertIn("repository-scoped", document)
            self.assertIn("must not", document.lower())
            self.assertIn("portfolio", document.lower())

    def test_3c_publication_requires_a_fresh_attempt_before_pickup(self):
        self.assertIn("attempt A", self.joined)
        self.assertIn("attempt B", self.joined)
        self.assertIn("new `execution_attempt_id`", self.joined)
        self.assertIn("PUBLISHED_BY_THIS_ATTEMPT", self.joined)

    def test_true_no_eligible_work_requires_maintenance_exhaustion(self):
        self.assertIn("true `NO_ELIGIBLE_WORK`", self.joined)
        self.assertIn("maintenance exhaustion", self.joined)

    def test_bootstrap_v1_result_vocabulary_is_unchanged(self):
        self.assertEqual(
            (
                "CLAIM_AND_WORK",
                "REVIEW_WORK",
                "RECOVERY_WORK",
                "NEEDS_HUMAN",
                "WAIT_EXTERNAL",
                "NO_ELIGIBLE_WORK",
                "NEEDS_EVIDENCE",
            ),
            cwb.DISPOSITIONS,
        )
        self.assertNotIn("MAINTENANCE_WORK", cwb.DISPOSITIONS)
        self.assertNotIn("MAINTENANCE_SELECTED", cwb.REASON_CODES)
        self.assertNotIn("MAINTENANCE_EXHAUSTED", cwb.REASON_CODES)


if __name__ == "__main__":
    unittest.main()
