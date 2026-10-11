"""Pure negative/positive routing tests: no GitHub network or credentials."""
from dataclasses import replace
import unittest

from tools.safe_dispatch_contract import Admission
from tools.safe_dispatch_fallback import EvidenceSnapshot, plan_fallback


def admitted(backend="github_api"):
    return Admission(
        status="ADMITTED",
        reason="POLICY_ADMITTED_NOT_EXECUTED",
        request_id="req_448_00000001",
        repository="kinoko34077/kinotch-default-canary",
        action="repo.status" if backend == "github_api" else "ci.verify",
        backend=backend,
        executor=("github.repository_metadata" if backend == "github_api"
                  else ".github/workflows/required.yml"),
        ref="main",
        head_sha="a" * 40,
        reviewed_workflow_sha="b" * 40 if backend == "github_actions" else None,
    )


def report(backend="github_api", **facts):
    return plan_fallback(admitted(backend), EvidenceSnapshot(
        visibility="public", **facts
    ))


class NativeConnectorTests(unittest.TestCase):
    def test_supported_public_api_uses_existing_connection_only(self):
        r = report(connector_operation="verified")
        self.assertEqual((r.status, r.route), (
            "PLAN_ONLY", "GITHUB_CONNECTOR_INTERACTIVE"
        ))
        self.assertIn("NOT_MACHINE_ENFORCED", r.reason)

    def test_supported_private_api_does_not_require_new_app(self):
        r = plan_fallback(admitted(), EvidenceSnapshot(
            visibility="private", connector_operation="verified"
        ))
        self.assertEqual(r.route, "GITHUB_CONNECTOR_INTERACTIVE")

    def test_unsupported_api_never_auto_grants_credentials(self):
        r = report(connector_operation="unsupported")
        self.assertEqual((r.status, r.reason), (
            "HOLD", "NEEDS_SEPARATELY_AUTHORIZED_API_TRANSPORT"
        ))

    def test_existing_owner_gh_cli_is_non_executable_alternative(self):
        r = report(
            connector_operation="unsupported",
            local_gh_cli="authenticated_owner_observed",
        )
        self.assertEqual((r.status, r.route), (
            "PLAN_ONLY", "OWNER_LOCAL_GH_CLI_API"
        ))
        self.assertIn("RECHECKED_NOT_EXECUTED", r.reason)

    def test_unavailable_local_gh_does_not_trigger_new_auth(self):
        r = report(
            connector_operation="unsupported", local_gh_cli="unavailable",
        )
        self.assertEqual(r.reason, "NEEDS_SEPARATELY_AUTHORIZED_API_TRANSPORT")

    def test_connector_remains_first_even_when_gh_observed(self):
        r = report(
            connector_operation="verified",
            local_gh_cli="authenticated_owner_observed",
        )
        self.assertEqual(r.route, "GITHUB_CONNECTOR_INTERACTIVE")

    def test_local_gh_observation_cannot_override_g1_human_gate(self):
        r = plan_fallback(
            replace(admitted(), status="NEEDS_HUMAN"),
            EvidenceSnapshot(
                "private", connector_operation="unsupported",
                local_gh_cli="authenticated_owner_observed",
            ),
        )
        self.assertEqual(r.reason, "G1_POLICY_NOT_ADMITTED")

    def test_unknown_connector_is_not_inferred_available(self):
        self.assertEqual(report().reason, "CONNECTOR_OPERATION_CAPABILITY_UNKNOWN")

    def test_api_must_not_sneak_a_workflow_identity_in(self):
        r = plan_fallback(
            replace(admitted(), reviewed_workflow_sha="c"*40),
            EvidenceSnapshot("public", connector_operation="verified")
        )
        self.assertEqual(r.reason, "BACKEND_PIN_MISMATCH")


class FixedActionsTests(unittest.TestCase):
    def test_public_hosted_when_trigger_and_capacity_proven(self):
        r = report(
            "github_actions", fixed_workflow_trigger="verified",
            hosted_runner="available",
        )
        self.assertEqual(r.route, "GITHUB_HOSTED_FIXED_WORKFLOW")
        self.assertEqual(r.status, "PLAN_ONLY")

    def test_private_hosted_when_capacity_proven(self):
        r = plan_fallback(admitted("github_actions"), EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="available",
        ))
        self.assertEqual(r.route, "GITHUB_HOSTED_FIXED_WORKFLOW")

    def test_missing_generic_workflow_trigger_never_invented(self):
        r = report("github_actions", hosted_runner="available")
        self.assertEqual(r.reason, "FIXED_OPERATION_TRIGGER_NOT_VERIFIED")

    def test_quota_unknown_not_treated_as_zero(self):
        r = report("github_actions", fixed_workflow_trigger="verified")
        self.assertEqual(r.reason, "HOSTED_CAPACITY_CAUSE_UNVERIFIED")

    def test_historic_private_billing_block_is_not_free_quota_exhausted(self):
        r = plan_fallback(admitted("github_actions"), EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="private_billing_blocked",
        ))
        self.assertEqual((r.status, r.route), ("HOLD", None))
        self.assertEqual(r.reason, "PRIVATE_BILLING_BLOCK_NEEDS_FRESH_RUNNER_ELIGIBILITY")

    def test_billing_block_does_not_auto_admit_selfhosted_runner(self):
        r = plan_fallback(admitted("github_actions"), EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="private_billing_blocked",
            self_hosted_runner="ready", self_hosted_isolation="verified",
            self_hosted_approved=True,
        ))
        self.assertEqual(r.reason, "PRIVATE_BILLING_BLOCK_NEEDS_FRESH_RUNNER_ELIGIBILITY")
        self.assertIsNone(r.route)

    def test_public_billing_block_is_not_a_private_status(self):
        r = report("github_actions",
                   fixed_workflow_trigger="verified",
                   hosted_runner="private_billing_blocked")
        self.assertEqual(r.reason, "PRIVATE_QUOTA_STATE_ON_PUBLIC_REPO")

    def test_private_exhausted_without_alternative_holds(self):
        r = plan_fallback(admitted("github_actions"), EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="private_quota_exhausted",
        ))
        self.assertEqual(r.reason, "INDEPENDENT_COMPUTE_BACKEND_REQUIRED")

    def test_private_exhausted_ready_isolated_approved_plan_only(self):
        r = plan_fallback(admitted("github_actions"), EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="private_quota_exhausted", self_hosted_runner="ready",
            self_hosted_isolation="verified", self_hosted_approved=True,
        ))
        self.assertEqual(r.route, "PRIVATE_SELF_HOSTED_FIXED_WORKFLOW")
        self.assertEqual(r.status, "PLAN_ONLY")
        self.assertIn("NOT_SCHEDULED", r.reason)

    def test_runner_ready_but_unisolated_is_denied(self):
        r = plan_fallback(admitted("github_actions"), EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="private_quota_exhausted", self_hosted_runner="ready",
            self_hosted_isolation="unsafe", self_hosted_approved=True,
        ))
        self.assertEqual(r.reason, "SELF_HOSTED_UNTRUSTED_OR_UNISOLATED")

    def test_runner_ready_but_not_approved_is_denied(self):
        r = plan_fallback(admitted("github_actions"), EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="private_quota_exhausted", self_hosted_runner="ready",
            self_hosted_isolation="verified", self_hosted_approved=False,
        ))
        self.assertEqual(r.reason, "SELF_HOSTED_HUMAN_GATE")

    def test_actions_disabled_no_selfhosted_bypass(self):
        r = plan_fallback(admitted("github_actions"), EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="all_actions_disabled", self_hosted_runner="ready",
            self_hosted_isolation="verified", self_hosted_approved=True,
        ))
        self.assertEqual(r.reason, "ALL_ACTIONS_DISABLED_NO_RUNNER_BYPASS")
        self.assertIsNone(r.route)

    def test_public_cannot_claim_private_free_minutes_exhausted(self):
        r = report(
            "github_actions", fixed_workflow_trigger="verified",
            hosted_runner="private_quota_exhausted",
        )
        self.assertEqual(r.reason, "PRIVATE_QUOTA_STATE_ON_PUBLIC_REPO")

    def test_wrong_workflow_blob_or_backend_blocks(self):
        f = EvidenceSnapshot(
            "private", fixed_workflow_trigger="verified",
            hosted_runner="available",
        )
        self.assertEqual(plan_fallback(
            replace(admitted("github_actions"), reviewed_workflow_sha=""),
            f,
        ).reason, "REVIEWED_WORKFLOW_NOT_PINNED")
        self.assertEqual(plan_fallback(
            replace(admitted(), backend="other"), f,
        ).reason, "UNSUPPORTED_CATALOG_BACKEND")


class DeniedEvidenceTests(unittest.TestCase):
    def test_g1_human_gate_not_overridden(self):
        r = plan_fallback(
            replace(admitted("github_actions"), status="NEEDS_HUMAN"),
            EvidenceSnapshot(
                "public", fixed_workflow_trigger="verified",
                hosted_runner="available",
            ),
        )
        self.assertEqual(r.reason, "G1_POLICY_NOT_ADMITTED")

    def test_forged_g1_denial_not_overridden(self):
        r = plan_fallback(
            replace(admitted(), status="DENIED"),
            EvidenceSnapshot("public", connector_operation="verified"),
        )
        self.assertEqual(r.reason, "G1_POLICY_NOT_ADMITTED")

    def test_partial_admission_denied(self):
        r = plan_fallback(
            replace(admitted(), head_sha=None),
            EvidenceSnapshot("public", connector_operation="verified"),
        )
        self.assertEqual(r.reason, "INCOMPLETE_ADMISSION")

    def test_invalid_evidence_shape_denied(self):
        self.assertEqual(plan_fallback(admitted(), {}).reason,
                         "INVALID_OR_UNVERIFIED_FACT_SHAPE")
        self.assertEqual(plan_fallback(
            admitted(), EvidenceSnapshot("unknown", connector_operation="verified")
        ).reason, "INVALID_OR_UNVERIFIED_FACT_SHAPE")
        self.assertEqual(plan_fallback(
            admitted(), EvidenceSnapshot("private", self_hosted_approved=1)
        ).reason, "INVALID_OR_UNVERIFIED_FACT_SHAPE")
        self.assertEqual(plan_fallback(
            admitted(), EvidenceSnapshot("private", local_gh_cli="self_claimed")
        ).reason, "INVALID_OR_UNVERIFIED_FACT_SHAPE")

    def test_no_executable_success_ever(self):
        candidates = [
            EvidenceSnapshot("private", connector_operation="verified"),
            EvidenceSnapshot("public", connector_operation="unsupported"),
            EvidenceSnapshot("private", connector_operation="unsupported",
                             local_gh_cli="authenticated_owner_observed"),
            EvidenceSnapshot("private", fixed_workflow_trigger="verified",
                             hosted_runner="private_billing_blocked"),
            EvidenceSnapshot("private", fixed_workflow_trigger="verified",
                             hosted_runner="private_quota_exhausted",
                             self_hosted_runner="ready",
                             self_hosted_isolation="verified",
                             self_hosted_approved=True),
        ]
        for e in candidates:
            for b in ("github_api", "github_actions"):
                result = plan_fallback(admitted(b), e)
                self.assertIn(result.status, ("PLAN_ONLY", "HOLD"))
                self.assertNotIn(result.status, ("ADMITTED", "EXECUTED",
                                                "READ_VERIFIED"))


if __name__ == "__main__":
    unittest.main()
