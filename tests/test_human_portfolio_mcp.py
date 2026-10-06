import unittest
from pathlib import Path

from tools import (
    devflow_mcp_core,
    maintenance_sync_check,
    reconciliation_publication,
)
from tests.test_devflow_mcp_core import FakeReader


REPOSITORY = "kinoko34077/demo"
OBSERVED_AT = "2026-10-06T00:20:00Z"


class HumanPortfolioMCPTests(unittest.TestCase):
    def _task(self, body="## Acceptance\n\nReview this exact task.\n", *, state="open"):
        return {
            "number": 7,
            "title": "[FEATURE] review target",
            "state": state,
            "body": body,
            "created_at": "2026-10-05T20:00:00Z",
            "updated_at": "2026-10-05T21:00:00Z",
            "html_url": "https://github.com/kinoko34077/demo/issues/7",
            "author_association": "OWNER",
        }

    def _publication(self, task):
        digest = maintenance_sync_check.canonical_body_sha256(task["body"])
        return reconciliation_publication.build_publication(
            {
                "contract_version": "development-reconciliation.v1",
                "task_ref": "kinoko34077/demo#7",
                "task_body_sha256": digest,
                "entry_ref": "https://github.com/kinoko34077/demo/issues/7",
                "observed_at": "2026-10-05T21:01:00Z",
                "reason_codes": ["DIFFERENT_REVIEWER_REQUIRED"],
                "human_gate": False,
                "evidence_complete": True,
                "disposition": "NEEDS_REVIEWER",
                "different_reviewer_required": True,
                "pr_number": 12,
                "pr_head_sha": "a" * 40,
                "scope": "Review exact PR head",
            }
        )

    def _control(self, publication=None, *, malformed=False):
        body = (
            "## Repository\n\n`kinoko34077/demo`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Repository State\n\n`ACTIVE`\n\n"
            "## Priority\n\n`P2`\n\n"
            "## Risk\n\n`LOW`\n\n"
            "## Type\n\n`AUDIT`\n\n"
            "## Control Notes\n\nKeep open.\n"
        )
        if malformed:
            body = (
                body.rstrip()
                + "\n\n"
                + reconciliation_publication.PROJECTION_MARKER_BEGIN
                + "\n{not-json}\n"
                + reconciliation_publication.PROJECTION_MARKER_END
            )
        elif publication is not None:
            body = reconciliation_publication.replace_publication_projection(
                body,
                REPOSITORY,
                [publication],
            )
        return {
            "number": 70,
            "title": "[REPO] demo",
            "html_url": "https://github.com/kinoko34077/devflow/issues/70",
            "state": "open",
            "author_association": "OWNER",
            "body": body,
        }

    def _service(self, control, task):
        reader = FakeReader(
            [],
            issues_by_repository={
                devflow_mcp_core.DEVFLOW_REPOSITORY: [control],
                REPOSITORY: [task],
            },
        )
        return devflow_mcp_core.DevflowService(
            reader,
            observed_at_factory=lambda: OBSERVED_AT,
        )

    def _reconciliation_entry(self, result):
        return next(
            entry
            for entry in result["entries"]
            if entry["source_kind"] == "RECONCILIATION"
        )

    def test_valid_publication_is_exposed_as_verified_current_reviewer_demand(self):
        task = self._task()
        publication = self._publication(task)
        result = self._service(self._control(publication), task).get_human_portfolio("demo")

        self.assertEqual(
            devflow_mcp_core.HUMAN_PORTFOLIO_READ_SCHEMA_VERSION,
            result["schema_version"],
        )
        self.assertEqual(REPOSITORY, result["repository"])
        self.assertTrue(result["complete"])
        self.assertEqual("AVAILABLE", result["repository_source"]["status"])
        self.assertEqual("AVAILABLE", result["reconciliation_source"]["status"])
        self.assertEqual("VERIFIED", result["reconciliation_source"]["trust"])
        self.assertEqual([], result["reconciliation_source"]["task_errors"])

        entry = self._reconciliation_entry(result)
        self.assertEqual("NEEDS_REVIEWER", entry["disposition"])
        self.assertEqual("reviewer", entry["role"])
        self.assertEqual("CURRENT", entry["evidence_freshness"])
        self.assertEqual("VERIFIED", entry["evidence_trust"])
        self.assertEqual(publication["publication_id"], entry["publication_id"])

    def test_changed_task_body_degrades_publication_to_needs_evidence(self):
        original = self._task()
        publication = self._publication(original)
        changed = self._task(original["body"] + "\nchanged\n")

        result = self._service(
            self._control(publication),
            changed,
        ).get_human_portfolio("demo")

        self.assertTrue(result["complete"])
        entry = self._reconciliation_entry(result)
        self.assertEqual("NEEDS_EVIDENCE", entry["disposition"])
        self.assertEqual("STALE", entry["evidence_freshness"])

    def test_closed_task_is_not_promoted_and_transport_is_incomplete(self):
        original = self._task()
        publication = self._publication(original)
        closed = self._task(original["body"], state="closed")

        result = self._service(
            self._control(publication),
            closed,
        ).get_human_portfolio("demo")

        self.assertFalse(result["complete"])
        self.assertEqual(
            [{"task_ref": "kinoko34077/demo#7", "error": "owning task is not open"}],
            result["reconciliation_source"]["task_errors"],
        )
        entry = self._reconciliation_entry(result)
        self.assertEqual("NEEDS_EVIDENCE", entry["disposition"])
        self.assertEqual("UNKNOWN", entry["evidence_freshness"])

    def test_malformed_control_publication_fails_closed_without_reviewer_demand(self):
        task = self._task()
        result = self._service(
            self._control(malformed=True),
            task,
        ).get_human_portfolio("demo")

        self.assertFalse(result["complete"])
        self.assertEqual("INVALID", result["reconciliation_source"]["status"])
        self.assertEqual("UNKNOWN", result["reconciliation_source"]["trust"])
        self.assertTrue(result["reconciliation_source"]["error"])
        self.assertFalse(
            any(entry["source_kind"] == "RECONCILIATION" for entry in result["entries"])
        )

    def test_mcp_server_exposes_read_only_human_portfolio_tool(self):
        source = (
            Path(__file__).resolve().parents[1] / "tools" / "devflow_mcp.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def get_human_portfolio(repository: str)", source)
        self.assertNotIn("def update_human_portfolio(", source)
        self.assertNotIn("def publish_human_portfolio(", source)


if __name__ == "__main__":
    unittest.main()
