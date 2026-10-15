"""Offline F2C handoff tests; no GitHub writes or real authority migration."""
from __future__ import annotations

import unittest
from dataclasses import replace

from tools.central_gateway_handoff import (
    CentralEvidence, HandoffIntent, LegacyEvidence,
    evaluate_handoff, project_writer_observation, rollback_review,
)

OLD = "a" * 64


class HandoffSafetyTests(unittest.TestCase):
    def setUp(self):
        self.legacy = LegacyEvidence(
            authority_issue="kinoko34077/execution-coordinator#3",
            snapshot_sha256=OLD, observed_at=1000,
            source_authenticated=True,
            fence_epoch=12, active_claims=0, queued_mutations=0,
            actions_writer_enabled=False, actions_writer_fenced=True,
            stale_actions_reentry_rejected=True,
        )
        self.central = CentralEvidence(
            source_snapshot_sha256=OLD, observed_at=1000,
            source_authenticated=True, epoch=13, writer_enabled=False,
            ledger_atomic_cas=True, stale_epoch_rejected=True,
            queue_quiescent=True, store_available=True,
            github_api_available=True, policy_and_identity_authenticated=True,
        )
        self.intent = HandoffIntent(
            expected_legacy_sha256=OLD, next_epoch=13,
            repositories=("kinoko34077/devflow", "kinoko34077/sample"),
        )

    def assess(self, *, legacy=None, central=None, intent=None, now=1040):
        return evaluate_handoff(
            self.legacy if legacy is None else legacy,
            self.central if central is None else central,
            self.intent if intent is None else intent,
            now=now,
        )

    def test_complete_offline_checklist_is_still_non_authorizing(self):
        result = self.assess()
        self.assertEqual(result.status, "REVIEW_ONLY")
        self.assertEqual(result.reason, "FENCING_PREFLIGHT_PASSED")
        self.assertTrue(result.non_authorizing)
        self.assertEqual(len(result.evidence_sha256), 64)
        self.assertNotIn("authorization", repr(result).lower())
        self.assertEqual(self.assess(), result)

    def test_digest_binds_scope_snapshot_and_generation_without_secrets(self):
        original = self.assess()
        different = replace(self.intent, repositories=("kinoko34077/devflow",))
        changed = self.assess(intent=different)
        self.assertNotEqual(original.evidence_sha256, changed.evidence_sha256)
        self.assertFalse("token" in repr(changed).lower())

    def test_actions_outage_is_not_a_fence(self):
        for changes in (
            {"actions_writer_enabled": True},
            {"actions_writer_fenced": False},
            {"stale_actions_reentry_rejected": False},
        ):
            with self.subTest(changes=changes):
                result = self.assess(legacy=replace(self.legacy, **changes))
                self.assertEqual((result.status, result.reason),
                                 ("HOLD", "LEGACY_WRITER_NOT_FENCED"))

    def test_inflight_claims_or_pending_mutations_block_cutover(self):
        for changes in ({"active_claims": 1}, {"queued_mutations": 3}):
            with self.subTest(changes=changes):
                self.assertEqual(
                    self.assess(legacy=replace(self.legacy, **changes)).reason,
                    "LEGACY_WORK_NOT_QUIESCENT",
                )

    def test_central_lane_already_active_rejects(self):
        for changes in ({"writer_enabled": True}, {"queue_quiescent": False}):
            with self.subTest(changes=changes):
                self.assertEqual(
                    self.assess(central=replace(self.central, **changes)).reason,
                    "CENTRAL_LANE_ALREADY_ACTIVE",
                )

    def test_missing_authenticated_source_blocks(self):
        for evidence in (
            self.assess(legacy=replace(self.legacy, source_authenticated=False)),
            self.assess(central=replace(self.central, source_authenticated=False)),
        ):
            self.assertEqual(evidence.reason, "UNAUTHENTICATED_SNAPSHOT")

    def test_exact_source_snapshot_binding(self):
        for evidence in (
            self.assess(legacy=replace(self.legacy, snapshot_sha256="b" * 64)),
            self.assess(central=replace(self.central, source_snapshot_sha256="b" * 64)),
            self.assess(intent=replace(self.intent, expected_legacy_sha256="b" * 64)),
        ):
            self.assertEqual(evidence.reason, "SOURCE_SNAPSHOT_MISMATCH")

    def test_no_false_claim_when_storage_or_identity_missing(self):
        for changes in (
            {"store_available": False},
            {"github_api_available": False},
            {"policy_and_identity_authenticated": False},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    self.assess(central=replace(self.central, **changes)).reason,
                    "CENTRAL_TRUST_OR_AVAILABILITY_MISSING",
                )

    def test_atomic_writer_and_fence_rejection_required(self):
        for changes in (
            {"ledger_atomic_cas": False},
            {"stale_epoch_rejected": False},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    self.assess(central=replace(self.central, **changes)).reason,
                    "NO_SINGLE_WRITER_FENCE_PROOF",
                )

    def test_no_equal_decrement_or_skipped_epoch(self):
        for candidate in (11, 12, 14, 15):
            with self.subTest(epoch=candidate):
                actual = replace(self.central, epoch=candidate)
                plan = replace(self.intent, next_epoch=candidate)
                self.assertEqual(
                    self.assess(central=actual, intent=plan).reason,
                    "NONMONOTONIC_OR_MISMATCHED_EPOCH",
                )
        self.assertEqual(
            self.assess(intent=replace(self.intent, next_epoch=14)).reason,
            "NONMONOTONIC_OR_MISMATCHED_EPOCH",
        )

    def test_stale_future_and_invalid_time(self):
        for now in (999, 1121, -1, True, "1040"):
            with self.subTest(now=now):
                wanted = ("MALFORMED_EVIDENCE" if type(now) is not int or now < 0
                          else "STALE_OR_FUTURE_SNAPSHOT")
                self.assertEqual(self.assess(now=now).reason, wanted)

    def test_stale_independent_observations_not_merged(self):
        self.assertEqual(
            self.assess(central=replace(self.central, observed_at=900)).reason,
            "STALE_OR_FUTURE_SNAPSHOT",
        )
        self.assertEqual(
            self.assess(legacy=replace(self.legacy, observed_at=1200)).reason,
            "STALE_OR_FUTURE_SNAPSHOT",
        )

    def test_malformed_repository_policy_denied(self):
        for repos in (
            (), ("kinoko34077/devflow",) * 2, ("Other/Case",),
            ("-owner/repo",), ("kinoko34077/.github",),
            ("kinoko34077/repo.git",),
            ("kinoko34077/repo",) * 33,
            (["malformed"],),
        ):
            with self.subTest(repos=repos):
                self.assertEqual(
                    self.assess(intent=replace(self.intent, repositories=repos)).reason,
                    "INVALID_SCOPE_OR_SNAPSHOT",
                )

    def test_injection_of_malformed_numeric_or_boolean_fields(self):
        checks = [
            self.assess(legacy=replace(self.legacy, fence_epoch=True)),
            self.assess(legacy=replace(self.legacy, active_claims=-1)),
            self.assess(legacy=replace(self.legacy, queued_mutations=1.5)),
            self.assess(central=replace(self.central, epoch=True)),
        ]
        self.assertTrue(all(x.reason == "INVALID_SCOPE_OR_SNAPSHOT" for x in checks))
        for x in (
            self.assess(legacy=replace(self.legacy, actions_writer_fenced=1)),
            self.assess(central=replace(self.central, store_available="yes")),
        ):
            self.assertEqual(x.reason, "INVALID_EVIDENCE_TYPES")

    def test_wrong_legacy_authority_and_scope_cannot_be_reassigned(self):
        self.assertEqual(
            self.assess(legacy=replace(
                self.legacy, authority_issue="evil/coordinator#1"
            )).reason,
            "INVALID_SCOPE_OR_SNAPSHOT",
        )
        self.assertEqual(
            self.assess(intent=replace(self.intent, boundary="ACTIVATE")).reason,
            "INVALID_SCOPE_OR_SNAPSHOT",
        )

    def test_writer_observation_fails_closed_on_split_brain(self):
        view = project_writer_observation(
            old_writer_active=True, central_writer_active=True,
            old_epoch=12, central_epoch=13,
        )
        self.assertEqual((view.status, view.reason, view.non_authorizing),
                         ("HOLD", "SPLIT_BRAIN_OBSERVED", True))

    def test_only_central_observed_is_not_permission(self):
        cases = (
            (False, True, 12, 13, "CENTRAL_OBSERVED_ONLY_NOT_AUTHORIZED"),
            (True, False, 12, 13, "LEGACY_OBSERVED_ONLY"),
            (False, False, 12, 13, "NO_ACTIVE_WRITER"),
            (False, True, 13, 13, "CENTRAL_STALE_EPOCH"),
        )
        for old, new, oe, ce, reason in cases:
            with self.subTest(reason=reason):
                result = project_writer_observation(
                    old_writer_active=old, central_writer_active=new,
                    old_epoch=oe, central_epoch=ce,
                )
                self.assertEqual(result.status, "HOLD")
                self.assertEqual(result.reason, reason)
                self.assertTrue(result.non_authorizing)

    def test_rollback_never_restores_previous_epoch(self):
        result = rollback_review(
            previous_epoch=12, current_epoch=13,
            old_actions_still_fenced=True,
        )
        self.assertEqual(result.reason,
                         "ROLLBACK_REQUIRES_NEW_EPOCH_AND_HUMAN_REVIEW")
        self.assertTrue(result.non_authorizing)
        self.assertEqual(
            rollback_review(previous_epoch=12, current_epoch=13,
                            old_actions_still_fenced=False).reason,
            "OLD_PATH_REACTIVATION_UNSAFE",
        )
        self.assertEqual(
            rollback_review(previous_epoch=13, current_epoch=13,
                            old_actions_still_fenced=True).reason,
            "NONMONOTONIC_ROLLBACK",
        )

    def test_bad_objects_fail_with_finite_reasons(self):
        bad_cases = (
            (None, self.central, self.intent),
            (self.legacy, None, self.intent),
            (self.legacy, self.central, None),
        )
        for old, central, intent in bad_cases:
            self.assertEqual(
                evaluate_handoff(old, central, intent, now=1040).reason,
                "MALFORMED_EVIDENCE",
            )


if __name__ == "__main__":
    unittest.main()
