import unittest

try:
    from tools import reconciliation_publication as rp
except ImportError:
    rp = None


HEAD = "a" * 40
OTHER = "b" * 40
DIGEST = "sha256:" + "c" * 64
OTHER_DIGEST = "sha256:" + "d" * 64


def common(**overrides):
    data = {
        "contract_version": "development-reconciliation.v1",
        "task_ref": "owner/repository#7",
        "task_body_sha256": DIGEST,
        "entry_ref": "https://github.com/owner/repository/issues/7",
        "observed_at": "2026-09-28T05:00:00Z",
        "reason_codes": ["DIFFERENT_REVIEWER_REQUIRED"],
        "human_gate": False,
        "evidence_complete": True,
    }
    data.update(overrides)
    return data


def reviewer(**overrides):
    data = common(
        disposition="NEEDS_REVIEWER",
        different_reviewer_required=True,
        pr_number=12,
        pr_head_sha=HEAD,
        scope="Review PR #12 at exact head",
    )
    data.update(overrides)
    return data


def recovery(**overrides):
    data = common(
        disposition="NEEDS_RECOVERY",
        reason_codes=["STALE_SESSION_WITH_PARTIAL_ARTIFACT"],
        predecessor_session_id="session-7",
        checkpoint="implementation committed",
        next_action="run the repository regression suite",
        recovery_transition="RECOVERY_ASSESSMENT",
        artifact_refs=["refs/heads/work/7", "owner/repository#7"],
        scope="Resume from the recorded unfinished boundary",
    )
    data.update(overrides)
    return data


class ReconciliationPublicationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(rp, "reconciliation_publication module must exist")

    def test_reviewer_publication_is_exact_head_and_versioned(self):
        publication = rp.build_publication(reviewer())
        self.assertEqual(publication["schema_version"], "development-reconciliation-work.v1")
        self.assertEqual(publication["role"], "reviewer")
        self.assertEqual(publication["disposition"], "NEEDS_REVIEWER")
        self.assertEqual(publication["context"]["pr_number"], 12)
        self.assertEqual(publication["context"]["pr_head_sha"], HEAD)
        self.assertTrue(publication["publication_id"].startswith("sha256:"))
        self.assertFalse(publication["requires_user_confirmation"])

    def test_reviewer_publication_requires_explicit_different_reviewer_gate(self):
        with self.assertRaises(ValueError):
            rp.build_publication(reviewer(different_reviewer_required=False))

    def test_non_publication_disposition_returns_none(self):
        self.assertIsNone(rp.build_publication(common(disposition="AUTO_ADVANCE")))

    def test_human_gate_suppresses_publication(self):
        self.assertIsNone(rp.build_publication(reviewer(human_gate=True)))

    def test_incomplete_or_invalid_freshness_fails_closed(self):
        with self.assertRaises(ValueError):
            rp.build_publication(reviewer(evidence_complete=False))
        with self.assertRaises(ValueError):
            rp.build_publication(reviewer(task_body_sha256="bad"))
        with self.assertRaises(ValueError):
            rp.build_publication(reviewer(pr_head_sha="bad"))
        with self.assertRaises(ValueError):
            rp.build_publication(reviewer(entry_ref="https://example.invalid/7"))

    def test_recovery_publication_binds_predecessor_checkpoint_and_artifacts(self):
        publication = rp.build_publication(recovery())
        self.assertEqual(publication["role"], "recovery")
        self.assertEqual(publication["context"]["predecessor_session_id"], "session-7")
        self.assertEqual(publication["context"]["checkpoint"], "implementation committed")
        self.assertEqual(
            publication["context"]["next_action"],
            "run the repository regression suite",
        )
        self.assertEqual(publication["context"]["recovery_transition"], "RECOVERY_ASSESSMENT")
        self.assertEqual(publication["context"]["artifact_refs"], ["owner/repository#7", "refs/heads/work/7"])

    def test_successor_eligibility_is_valid_recovery_publication(self):
        publication = rp.build_publication(
            recovery(
                recovery_transition="SUCCESSOR_ELIGIBILITY_EVALUATION",
                artifact_refs=[],
                next_action="re-read the owning task before successor work",
            )
        )
        self.assertEqual(publication["role"], "recovery")
        self.assertEqual(
            publication["context"]["recovery_transition"],
            "SUCCESSOR_ELIGIBILITY_EVALUATION",
        )

    def test_same_evidence_has_stable_logical_identity(self):
        first = rp.build_publication(reviewer(observed_at="2026-09-28T05:00:00Z"))
        second = rp.build_publication(reviewer(observed_at="2026-09-28T05:30:00Z"))
        self.assertEqual(first["publication_id"], second["publication_id"])

    def test_head_change_supersedes_old_reviewer_publication(self):
        old = rp.build_publication(reviewer())
        new = rp.build_publication(reviewer(pr_head_sha=OTHER))
        result = rp.reconcile_publications(
            [old],
            task_ref="owner/repository#7",
            role="reviewer",
            desired=new,
        )
        self.assertEqual(result["active"], [new])
        self.assertEqual(result["superseded_ids"], [old["publication_id"]])

    def test_resolved_gate_supersedes_existing_publication_without_new_record(self):
        old = rp.build_publication(reviewer())
        result = rp.reconcile_publications(
            [old],
            task_ref="owner/repository#7",
            role="reviewer",
            desired=None,
        )
        self.assertEqual(result["active"], [])
        self.assertEqual(result["superseded_ids"], [old["publication_id"]])

    def test_unrelated_publications_are_preserved(self):
        old = rp.build_publication(reviewer())
        unrelated = rp.build_publication(
            recovery(task_ref="owner/repository#8", entry_ref="https://github.com/owner/repository/issues/8")
        )
        result = rp.reconcile_publications(
            [old, unrelated],
            task_ref="owner/repository#7",
            role="reviewer",
            desired=old,
        )
        self.assertEqual(result["active"], [old, unrelated])
        self.assertEqual(result["superseded_ids"], [])

    def test_publication_contains_no_provider_or_assignment_fields(self):
        publication = rp.build_publication(reviewer())
        flattened = repr(publication).lower()
        for forbidden in ("provider", "worker_id", "claim_id", "lease", "assigned"):
            self.assertNotIn(forbidden, flattened)

    def test_task_body_digest_change_changes_identity(self):
        first = rp.build_publication(reviewer())
        second = rp.build_publication(reviewer(task_body_sha256=OTHER_DIGEST))
        self.assertNotEqual(first["publication_id"], second["publication_id"])


if __name__ == "__main__":
    unittest.main()
