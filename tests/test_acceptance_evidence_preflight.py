import hashlib
import unittest
from datetime import datetime, timezone

from tools.acceptance_evidence_preflight import (
    acceptance_preflight,
    outcome_observation_preflight,
)
from tools.development_reconciler import evaluate_pr

TASK = "kinoko34077/devflow#798"
BODY = "Current owning Issue body: local MCP accepted; Inbox completeness excluded"
SHA = hashlib.sha256(BODY.encode()).hexdigest()


def proof(**overrides):
    value = {
        "task_ref": TASK, "issue_body_sha256": SHA,
        "issue_read_at": "2026-10-27T00:00:00Z",
        "acceptance_scope": "bounded Windows local MCP availability",
        "status": "SATISFIED", "source_verified": True,
        "source_complete": True, "decision_authorized": True,
        "evidence_refs": ["https://github.com/kinoko34077/devflow/issues/531#issuecomment-6366311495"],
        "excluded_scopes": ["global Inbox completeness", "original historical failure cause"],
    }
    value.update(overrides)
    return value


class AcceptanceEvidenceTests(unittest.TestCase):
    def check(self, value):
        return acceptance_preflight(value, task_ref=TASK, observed_issue_body_sha256=SHA, now=datetime(2026, 10, 27, 0, 5, tzinfo=timezone.utc))

    def test_bounded_current_issue_acceptance_passes_without_overclaim(self):
        result = self.check(proof())
        self.assertEqual(result["status"], "VERIFIED_SCOPE_DECISION")
        self.assertTrue(result["scope_acceptance_satisfied"])
        self.assertFalse(result["acceptance_satisfied"])
        self.assertEqual(result["excluded_scopes"], ("global Inbox completeness", "original historical failure cause"))

    def test_older_pr_claim_cannot_override_current_issue_revision(self):
        result = self.check(proof(issue_body_sha256="a"*64))
        self.assertEqual(result["reason"], "STALE_OWNING_ISSUE_REVISION")
        self.assertFalse(result["evidence_complete"])

    def test_merge_and_ci_alone_do_not_attest_success(self):
        for patch in ({"decision_authorized": False}, {"source_verified": False},
                      {"source_complete": False}, {"evidence_refs": []},
                      {"status": "UNKNOWN"}, {"task_ref": "kinoko34077/devflow#799"}):
            with self.subTest(patch=patch):
                result = self.check(proof(**patch))
                self.assertFalse(result["evidence_complete"])
                self.assertFalse(result["acceptance_satisfied"])

    def test_rejected_scope_is_not_positive_acceptance(self):
        result = self.check(proof(status="UNSATISFIED"))
        self.assertTrue(result["evidence_complete"])
        self.assertFalse(result["scope_acceptance_satisfied"])
        self.assertFalse(result["acceptance_satisfied"])

    def test_scoped_satisfied_never_closes_whole_task(self):
        result = self.check(proof())
        self.assertTrue(result["evidence_complete"])
        self.assertFalse(result["acceptance_satisfied"])

    def test_rejects_old_freshness_and_unanchored_or_duplicate_refs(self):
        for p in ({"issue_read_at": "2026-10-26T23:00:00Z"},
                  {"issue_read_at": "invalid"},
                  {"evidence_refs": ["https://github.com/kinoko34077/devflow/issues/531"]},
                  {"evidence_refs": ["https://github.com/kinoko34077/other/issues/531?x=1"]},
                  {"evidence_refs": ["https://github.com/kinoko34077/devflow/issues/531#issuecomment-1"] * 2}):
            with self.subTest(p=p):
                self.assertFalse(self.check(proof(**p))["evidence_complete"])

    def test_untrusted_or_incomplete_proof_cannot_trigger_existing_reconciler(self):
        result = self.check(proof())
        pr = {
            "task_ref": TASK, "task_kind": "FINITE", "task_open": True,
            "acceptance_satisfied": result["acceptance_satisfied"],
            "pr_number": 799, "pr_state": "MERGED", "pr_head_sha": "a"*40,
            "expected_head_sha": "a"*40, "checks": "PASS", "formal_review": "PASS",
            "different_reviewer_required": False, "different_reviewer": "PASS",
            "request_changes": False, "blocking_finding": False, "owning_blocker": False,
            "human_gate": False, "external_wait": False, "mergeable": True,
            "revertible": True, "current_state_changed": True,
            "control_changed": True, "evidence_complete": result["evidence_complete"],
        }
        decision = evaluate_pr(pr)
        self.assertEqual(decision.disposition, "NO_ACTION")
        self.assertIsNone(decision.transition)


class OutcomeObservationPreflightTests(unittest.TestCase):
    TASK = "kinoko34077/devflow#839"
    CURRENT_SHA = "b" * 64
    COMMENT = "https://github.com/kinoko34077/japanese-orthography/issues/310#issuecomment-6106750343"

    def packet(self, **overrides):
        value = {
            "task_ref": self.TASK,
            "issue_body_sha256": self.CURRENT_SHA,
            "required_surface": "PUBLIC_BROWSER",
            "required_target": "git:f38d562edfda0bbaefaa3e1b6d71ccb078c26364",
            "observed_surface": "PUBLIC_BROWSER",
            "observed_target": "git:f38d562edfda0bbaefaa3e1b6d71ccb078c26364",
            "observed_result": "SUCCESS",
            "evidence_refs": [self.COMMENT],
        }
        value.update(overrides)
        return value

    def assess(self, packet):
        return outcome_observation_preflight(
            packet,
            task_ref=self.TASK,
            observed_issue_body_sha256=self.CURRENT_SHA,
        )

    def test_aligned_public_browser_artifact_is_only_declared_consistent(self):
        result = self.assess(self.packet())
        self.assertEqual(result["status"], "DECLARED_ALIGNED")
        self.assertTrue(result["packet_complete"])
        self.assertEqual(result["observed_result"], "SUCCESS")
        self.assertEqual(result["source_verification"], "NOT_PERFORMED")
        self.assertFalse(result["acceptance_satisfied"])
        self.assertFalse(result["can_authorize_execution"])

    def test_fixture_observation_cannot_substitute_for_public_browser_surface(self):
        result = self.assess(self.packet(observed_surface="FIXTURE_PARITY"))
        self.assertEqual(result["status"], "DECLARED_MISMATCH")
        self.assertEqual(result["reason"], "SURFACE_MISMATCH")
        self.assertEqual(result["observed_result"], "SUCCESS")
        self.assertFalse(result["acceptance_satisfied"])

    def test_artifact_revision_mismatch_is_reported_separately(self):
        result = self.assess(self.packet(observed_target="git:ccb788aeeda0c5dee1e37b57aa1e8a26f7bb4769"))
        self.assertEqual(result["status"], "DECLARED_MISMATCH")
        self.assertEqual(result["reason"], "TARGET_MISMATCH")

    def test_failure_and_valid_negative_are_preserved_without_becoming_acceptance(self):
        for observed_result in ("FAILURE", "VALID_NEGATIVE"):
            with self.subTest(observed_result=observed_result):
                result = self.assess(self.packet(observed_result=observed_result))
                self.assertEqual(result["status"], "DECLARED_ALIGNED")
                self.assertEqual(result["observed_result"], observed_result)
                self.assertFalse(result["acceptance_satisfied"])

    def test_unknown_target_preserves_reported_failure_but_stays_unknown(self):
        result = self.assess(self.packet(observed_target=None, observed_result="FAILURE"))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "TARGET_IDENTITY_UNKNOWN")
        self.assertEqual(result["observed_result"], "FAILURE")
        self.assertFalse(result["packet_complete"])

    def test_live_gesture_ime_report_remains_physical_failure_with_unknown_ipa(self):
        report = {
            "task_ref": "kinoko34077/gesture-ime#203",
            "issue_body_sha256": "c" * 64,
            "required_surface": "PHYSICAL_RUNTIME",
            "required_target": "installed-ipa:identified-build",
            "observed_surface": "PHYSICAL_RUNTIME",
            "observed_target": None,
            "observed_result": "FAILURE",
            "evidence_refs": [
                "https://github.com/kinoko34077/gesture-ime/issues/203#issuecomment-6116020441",
            ],
        }
        result = outcome_observation_preflight(
            report, task_ref="kinoko34077/gesture-ime#203",
            observed_issue_body_sha256="c" * 64,
        )
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "TARGET_IDENTITY_UNKNOWN")
        self.assertEqual(result["observed_result"], "FAILURE")
        self.assertFalse(result["acceptance_satisfied"])

    def test_missing_evidence_stays_needs_evidence(self):
        result = self.assess(self.packet(evidence_refs=[]))
        self.assertEqual(result["status"], "NEEDS_EVIDENCE")
        self.assertEqual(result["reason"], "EVIDENCE_REFERENCE_MISSING")

    def test_stale_issue_body_and_wrong_task_cannot_be_reconciled(self):
        for patch, reason in (
            ({"issue_body_sha256": "c" * 64}, "STALE_OWNING_ISSUE_REVISION"),
            ({"task_ref": "kinoko34077/devflow#840"}, "TASK_REF_MISMATCH"),
        ):
            with self.subTest(patch=patch):
                result = self.assess(self.packet(**patch))
                self.assertEqual(result["status"], "NEEDS_EVIDENCE")
                self.assertEqual(result["reason"], reason)
                self.assertFalse(result["acceptance_satisfied"])

    def test_unknown_and_not_run_are_distinct_from_failure(self):
        for result_value, expected_status in (("UNKNOWN", "UNKNOWN"), ("NOT_RUN", "NOT_RUN")):
            with self.subTest(result_value=result_value):
                result = self.assess(self.packet(observed_result=result_value, evidence_refs=[]))
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["observed_result"], result_value)
                self.assertFalse(result["acceptance_satisfied"])

    def test_invalid_or_unanchored_reference_is_not_evidence(self):
        for ref in ("https://github.com/kinoko34077/japanese-orthography/issues/310",
                    "https://example.com/evidence"):
            with self.subTest(ref=ref):
                result = self.assess(self.packet(evidence_refs=[ref]))
                self.assertEqual(result["status"], "NEEDS_EVIDENCE")
                self.assertEqual(result["reason"], "EVIDENCE_REFERENCE_INVALID")

    def test_untrusted_json_types_return_needs_evidence_without_crashing(self):
        for patch in (
            {"observed_result": []},
            {"evidence_refs": [{}]},
            {"required_surface": ["PUBLIC_BROWSER"]},
            {"observed_target": {"sha": "f38d562"}},
        ):
            with self.subTest(patch=patch):
                result = self.assess(self.packet(**patch))
                self.assertEqual(result["status"], "NEEDS_EVIDENCE")
                self.assertFalse(result["acceptance_satisfied"])


if __name__ == "__main__":
    unittest.main()
