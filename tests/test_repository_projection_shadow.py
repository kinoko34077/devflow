import unittest
from pathlib import Path

from scripts import repository_projection_shadow as shadow


ROOT = Path(__file__).resolve().parents[1]


class RepositoryProjectionShadowReportTests(unittest.TestCase):
    def test_build_shadow_report_records_projection_and_control_comparison(self):
        portfolio = {
            "observed_at": "2026-10-04T04:00:00Z",
            "repository_count": 2,
            "source_unavailable_count": 1,
            "open_issue_count": 5,
            "machine_task_count": 1,
            "legacy_hint_count": 2,
            "unclassified_count": 1,
            "invalid_metadata_count": 0,
            "untrusted_metadata_count": 1,
            "repositories": [
                {
                    "repository": "kinoko34077/alpha",
                    "source_status": "AVAILABLE",
                    "source_freshness": "CURRENT",
                    "source_error": None,
                    "open_issue_count": 5,
                    "machine_task_count": 1,
                    "legacy_hint_count": 2,
                    "unclassified_count": 1,
                    "invalid_metadata_count": 0,
                    "untrusted_metadata_count": 1,
                    "machine_type_counts": {"BUG": 1},
                    "legacy_hint_type_counts": {"SPEC": 2},
                    "task_records": [{"issue_number": 7}],
                },
                {
                    "repository": "kinoko34077/beta",
                    "source_status": "UNAVAILABLE",
                    "source_freshness": "UNKNOWN",
                    "source_error": "unavailable",
                    "open_issue_count": 0,
                    "machine_task_count": 0,
                    "legacy_hint_count": 0,
                    "unclassified_count": 0,
                    "invalid_metadata_count": 0,
                    "untrusted_metadata_count": 0,
                    "machine_type_counts": {},
                    "legacy_hint_type_counts": {},
                    "task_records": [],
                },
            ],
        }
        controls = {
            "kinoko34077/alpha": {
                "issue_number": 10,
                "work_status": "IMPLEMENTING",
                "active_work": "alpha#7 active implementation",
            },
            "kinoko34077/beta": {
                "issue_number": 11,
                "work_status": "BLOCKED",
                "active_work": "",
            },
        }

        result = shadow.build_shadow_report(portfolio, controls)

        self.assertEqual(result["schema_version"], shadow.SCHEMA_VERSION)
        self.assertEqual(result["repository_count"], 2)
        self.assertEqual(result["source_unavailable_count"], 1)
        self.assertEqual(result["machine_record_count"], 1)
        self.assertEqual(result["machine_task_count"], 1)
        self.assertEqual(result["legacy_or_unclassified_count"], 3)
        self.assertAlmostEqual(result["legacy_or_unclassified_rate"], 0.6)
        self.assertEqual(result["untrusted_metadata_count"], 1)
        self.assertEqual(result["non_machine_metadata_count"], 4)
        self.assertAlmostEqual(result["machine_metadata_coverage_rate"], 0.2)
        self.assertEqual(result["repositories_with_machine_tasks"], 1)
        self.assertEqual(
            result["repositories_with_open_issues_without_machine_tasks"],
            0,
        )
        self.assertEqual(
            result["operator_decision_ambiguous_repository_count"],
            1,
        )
        self.assertEqual(result["repositories_with_control_active_work_text"], 1)
        self.assertEqual(
            result["repositories"][0]["machine_task_refs"],
            ["kinoko34077/alpha#7"],
        )

    def test_collect_shadow_reads_controls_for_projected_managed_repositories(self):
        class Service:
            def __init__(self):
                self.controls = []

            def get_portfolio_projection(self):
                return {
                    "observed_at": "2026-10-04T04:00:00Z",
                    "repository_count": 1,
                    "source_unavailable_count": 0,
                    "open_issue_count": 0,
                    "machine_task_count": 0,
                    "legacy_hint_count": 0,
                    "unclassified_count": 0,
                    "invalid_metadata_count": 0,
                    "untrusted_metadata_count": 0,
                    "repositories": [
                        {
                            "repository": "kinoko34077/alpha",
                            "source_status": "AVAILABLE",
                            "source_freshness": "CURRENT",
                            "source_error": None,
                            "open_issue_count": 0,
                            "machine_task_count": 0,
                            "legacy_hint_count": 0,
                            "unclassified_count": 0,
                            "invalid_metadata_count": 0,
                            "untrusted_metadata_count": 0,
                            "machine_type_counts": {},
                            "legacy_hint_type_counts": {},
                            "task_records": [],
                        }
                    ],
                }

            def get_repository_control(self, repository):
                self.controls.append(repository)
                return {
                    "issue_number": 10,
                    "work_status": "AUDITED",
                    "active_work": "None.",
                }

        service = Service()
        report = shadow.collect_shadow(service)
        self.assertEqual(service.controls, ["kinoko34077/alpha"])
        self.assertEqual(report["repository_count"], 1)
        self.assertEqual(report["repositories_with_control_active_work_text"], 1)
        self.assertEqual(report["repositories_with_open_issues_without_machine_tasks"], 0)
        self.assertEqual(report["operator_decision_ambiguous_repository_count"], 0)

    def test_shadow_workflow_is_manual_read_only_and_artifact_only(self):
        path = ROOT / ".github" / "workflows" / "maintenance-audit.yml"
        self.assertTrue(path.exists(), "central maintenance workflow must exist")
        source = path.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", source)
        self.assertIn("- projection-shadow", source)
        self.assertIn("projection-shadow:", source)
        shadow_job = source.split("\n  projection-shadow:\n", 1)[1].split(
            "\n  publish:\n", 1
        )[0]
        self.assertIn("contents: read", source)
        self.assertIn("issues: read", source)
        self.assertNotIn("contents: write", shadow_job)
        self.assertNotIn("issues: write", shadow_job)
        self.assertNotIn("pull-requests: write", shadow_job)
        self.assertIn("MAINTENANCE_AUDIT_TOKEN", shadow_job)
        self.assertIn("repository_projection_shadow.py", shadow_job)
        self.assertIn("actions/upload-artifact@", shadow_job)


if __name__ == "__main__":
    unittest.main()
