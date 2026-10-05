import json
import unittest

from tools import human_portfolio
from tools import reconciliation_publication
from tools import repository_projection


BEGIN = repository_projection.ISSUE_METADATA_MARKER_BEGIN
END = repository_projection.ISSUE_METADATA_MARKER_END


def _issue(
    number,
    *,
    work_status="READY_FOR_IMPLEMENTATION",
    requires_user_confirmation=False,
    external_wait=False,
    scope_ready=True,
    author_association="OWNER",
):
    metadata = {
        "schema_version": 1,
        "record_role": "TASK",
        "type": "FEATURE",
        "work_status": work_status,
        "scope_ready": scope_ready,
        "requires_user_confirmation": requires_user_confirmation,
        "external_wait": external_wait,
    }
    return {
        "number": number,
        "title": f"[FEATURE] task {number}",
        "state": "open",
        "created_at": f"2026-10-05T00:{number:02d}:00Z",
        "updated_at": f"2026-10-05T01:{number:02d}:00Z",
        "html_url": f"https://github.com/owner/repo/issues/{number}",
        "body": f"{BEGIN}\n{json.dumps(metadata)}\n{END}",
        "author_association": author_association,
    }


def _projection(repository="owner/repo", issues=None, *, status="AVAILABLE"):
    issues = list(issues or [])
    return repository_projection.build_repository_projection(
        repository,
        issues,
        observed_at="2026-10-05T02:00:00Z",
        source_status=status,
        source_error="source unavailable" if status == "UNAVAILABLE" else None,
    )


def _reviewer_publication(task_number=7, *, head="a" * 40):
    repository = "owner/repo"
    return reconciliation_publication.build_publication(
        {
            "contract_version": "development-reconciliation.v1",
            "task_ref": f"{repository}#{task_number}",
            "task_body_sha256": "sha256:" + "c" * 64,
            "entry_ref": f"https://github.com/{repository}/issues/{task_number}",
            "observed_at": "2026-10-05T02:00:00Z",
            "reason_codes": ["DIFFERENT_REVIEWER_REQUIRED"],
            "human_gate": False,
            "evidence_complete": True,
            "disposition": "NEEDS_REVIEWER",
            "different_reviewer_required": True,
            "pr_number": 12,
            "pr_head_sha": head,
            "scope": "Review exact PR head",
        }
    )


def _recovery_publication(task_number=8):
    repository = "owner/repo"
    return reconciliation_publication.build_publication(
        {
            "contract_version": "development-reconciliation.v1",
            "task_ref": f"{repository}#{task_number}",
            "task_body_sha256": "sha256:" + "d" * 64,
            "entry_ref": f"https://github.com/{repository}/issues/{task_number}",
            "observed_at": "2026-10-05T02:00:00Z",
            "reason_codes": ["STALE_SESSION_WITH_PARTIAL_ARTIFACT"],
            "human_gate": False,
            "evidence_complete": True,
            "disposition": "NEEDS_RECOVERY",
            "predecessor_session_id": "session-8",
            "checkpoint": "implementation checkpoint",
            "next_action": "resume verification",
            "recovery_transition": "RECOVERY_ASSESSMENT",
            "artifact_refs": [],
            "scope": "Recover bounded task",
        }
    )


class HumanPortfolioReadModelTests(unittest.TestCase):
    def test_combines_machine_attention_task_queue_and_reconciliation_demand(self):
        projection = _projection(
            issues=[
                _issue(1, work_status="READY_FOR_IMPLEMENTATION"),
                _issue(2, requires_user_confirmation=True),
                _issue(3, work_status="IMPLEMENTING"),
            ]
        )
        reviewer = _reviewer_publication(7)
        recovery = _recovery_publication(8)

        result = human_portfolio.build_repository_human_portfolio(
            projection,
            reconciliation_publications=[reviewer, recovery],
            reconciliation_task_body_sha256={
                "owner/repo#7": "sha256:" + "c" * 64,
                "owner/repo#8": "sha256:" + "d" * 64,
            },
            reconciliation_source_trust="VERIFIED",
        )

        self.assertTrue(result.complete)
        by_identity = {
            (entry.task_ref, entry.role, entry.disposition)
            for entry in result.entries
        }
        self.assertIn(("owner/repo#1", "TASK", "READY"), by_identity)
        self.assertIn(("owner/repo#2", "TASK", "NEEDS_HUMAN"), by_identity)
        self.assertIn(("owner/repo#3", "TASK", "IMPLEMENTING"), by_identity)
        self.assertIn(("owner/repo#7", "reviewer", "NEEDS_REVIEWER"), by_identity)
        self.assertIn(("owner/repo#8", "recovery", "NEEDS_RECOVERY"), by_identity)

    def test_attention_disposition_prevents_ready_promotion(self):
        projection = _projection(
            issues=[
                _issue(
                    1,
                    work_status="READY_FOR_IMPLEMENTATION",
                    requires_user_confirmation=True,
                )
            ]
        )

        result = human_portfolio.build_repository_human_portfolio(projection)

        self.assertEqual(1, len(result.entries))
        self.assertEqual("NEEDS_HUMAN", result.entries[0].disposition)

    def test_external_wait_and_scope_evidence_are_visible(self):
        projection = _projection(
            issues=[
                _issue(1, external_wait=True),
                _issue(2, scope_ready=False),
            ]
        )

        result = human_portfolio.build_repository_human_portfolio(projection)

        dispositions = {entry.task_ref: entry.disposition for entry in result.entries}
        self.assertEqual("WAIT_EXTERNAL", dispositions["owner/repo#1"])
        self.assertEqual("NEEDS_EVIDENCE", dispositions["owner/repo#2"])

    def test_untrusted_machine_metadata_surfaces_needs_evidence(self):
        projection = _projection(
            issues=[_issue(1, author_association="NONE")]
        )

        result = human_portfolio.build_repository_human_portfolio(projection)

        self.assertEqual(1, len(result.entries))
        self.assertEqual("NEEDS_EVIDENCE", result.entries[0].disposition)
        self.assertEqual("UNKNOWN", result.entries[0].role)

    def test_unavailable_source_fails_closed_without_promoting_publications(self):
        projection = _projection(status="UNAVAILABLE")
        reviewer = _reviewer_publication(7)

        result = human_portfolio.build_repository_human_portfolio(
            projection,
            reconciliation_publications=[reviewer],
            reconciliation_task_body_sha256={
                "owner/repo#7": "sha256:" + "c" * 64,
            },
            reconciliation_source_trust="VERIFIED",
        )

        self.assertFalse(result.complete)
        self.assertEqual("UNAVAILABLE", result.source_status)
        self.assertEqual((), result.entries)

    def test_reconciliation_demand_without_current_digest_becomes_needs_evidence(self):
        projection = _projection()
        reviewer = _reviewer_publication(7)

        result = human_portfolio.build_repository_human_portfolio(
            projection,
            reconciliation_publications=[reviewer],
            reconciliation_source_trust="VERIFIED",
        )

        self.assertEqual(1, len(result.entries))
        self.assertEqual("NEEDS_EVIDENCE", result.entries[0].disposition)
        self.assertEqual("UNKNOWN", result.entries[0].evidence_freshness)
        self.assertEqual("VERIFIED", result.entries[0].evidence_trust)

    def test_stale_reconciliation_task_digest_is_not_promoted(self):
        projection = _projection()
        reviewer = _reviewer_publication(7)

        result = human_portfolio.build_repository_human_portfolio(
            projection,
            reconciliation_publications=[reviewer],
            reconciliation_task_body_sha256={
                "owner/repo#7": "sha256:" + "e" * 64,
            },
            reconciliation_source_trust="VERIFIED",
        )

        self.assertEqual("NEEDS_EVIDENCE", result.entries[0].disposition)
        self.assertEqual("STALE", result.entries[0].evidence_freshness)

    def test_unverified_reconciliation_source_is_not_promoted(self):
        projection = _projection()
        reviewer = _reviewer_publication(7)

        result = human_portfolio.build_repository_human_portfolio(
            projection,
            reconciliation_publications=[reviewer],
            reconciliation_task_body_sha256={
                "owner/repo#7": "sha256:" + "c" * 64,
            },
            reconciliation_source_trust="UNKNOWN",
        )

        self.assertEqual("NEEDS_EVIDENCE", result.entries[0].disposition)
        self.assertEqual("UNKNOWN", result.entries[0].evidence_trust)

    def test_duplicate_reconciliation_task_role_fails_closed(self):
        projection = _projection()
        first = _reviewer_publication(7, head="a" * 40)
        second = _reviewer_publication(7, head="b" * 40)

        with self.assertRaisesRegex(ValueError, "duplicate task/role"):
            human_portfolio.build_repository_human_portfolio(
                projection,
                reconciliation_publications=[first, second],
                reconciliation_task_body_sha256={
                    "owner/repo#7": "sha256:" + "c" * 64,
                },
                reconciliation_source_trust="VERIFIED",
            )

    def test_multi_repository_output_is_deterministic_and_requires_projection(self):
        first = _projection("owner/z")
        second = _projection("owner/a")

        result = human_portfolio.build_human_portfolio([first, second])
        self.assertEqual(["owner/a", "owner/z"], [item.repository for item in result])

        with self.assertRaisesRegex(ValueError, "without projections"):
            human_portfolio.build_human_portfolio(
                [first],
                reconciliation_publications={"owner/missing": []},
            )


if __name__ == "__main__":
    unittest.main()
