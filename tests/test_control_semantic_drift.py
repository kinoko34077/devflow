import unittest

from tools.control_semantic_drift import compare_claim


def fixtures(dimension="PR_GATE", claim="AWAIT_REVIEW", actual="MERGED", **changes):
    control = {
        "repository": "kinoko34077/kinotch-repo-monitor",
        "subject": "kinoko34077/kinotch-repo-monitor#85",
        "dimension": dimension,
        "value": claim,
        "section": "Next Action",
        "is_current": True,
        "source_verified": True,
        "source_url": "https://github.com/kinoko34077/devflow/issues/59",
        "read_at": "2026-10-19T18:16:00+09:00",
    }
    observed = {
        "repository": control["repository"],
        "subject": control["subject"],
        "dimension": dimension,
        "value": actual,
        "source_verified": True,
        "source_complete": True,
        "source_url": "https://github.com/kinoko34077/kinotch-repo-monitor/"
                      + ("pull" if dimension == "PR_GATE" else "issues") + "/85",
        "read_at": "2026-10-19T18:16:01+09:00",
    }
    for key, value in changes.items():
        obj, field = key.split("__", 1)
        (control if obj == "c" else observed)[field] = value
    return control, observed


class SemanticDriftTests(unittest.TestCase):
    def check(self, want, *args, **kwargs):
        result = compare_claim(*fixtures(*args, **kwargs))
        self.assertEqual(result["status"], want)
        self.assertEqual(set(result), {"status", "reason"})

    def test_merged_code_not_live_billing_router(self):
        # Tests/main may pass while on-demand worker and Private dispatch are absent.
        self.check("POTENTIAL_MISMATCH", "BILLING_PREFLIGHT_DEPLOYMENT",
                   "ROUTING_LIVE", "CODE_ONLY")

    def test_readonly_billing_is_not_active_dispatch(self):
        self.check("POTENTIAL_MISMATCH", "BILLING_PREFLIGHT_DEPLOYMENT",
                   "ROUTING_LIVE", "READ_ONLY_LIVE")

    def test_code_only_state_is_not_stale_when_proven(self):
        self.check("ALIGNED", "BILLING_PREFLIGHT_DEPLOYMENT",
                   "CODE_ONLY", "CODE_ONLY")

    def test_no_private_worker_approval_not_confused_with_public_oneshot(self):
        self.check("POTENTIAL_MISMATCH", "PRIVATE_EXECUTOR_ADMISSION",
                   "ADMITTED", "NOT_ADMITTED")

    def test_private_admission_requires_same_scope_trusted_source(self):
        self.check("UNKNOWN", "PRIVATE_EXECUTOR_ADMISSION",
                   "ADMITTED", "NOT_ADMITTED", o__source_verified=False)

    def test_runtime_proof_missing_is_not_negation(self):
        self.check("UNKNOWN", "BILLING_PREFLIGHT_DEPLOYMENT",
                   "ROUTING_LIVE", "UNKNOWN")

    def test_runtime_and_admission_dimensions_never_cross_compare(self):
        self.check("NOT_COMPARABLE", "BILLING_PREFLIGHT_DEPLOYMENT",
                   "CODE_ONLY", "CODE_ONLY",
                   o__dimension="PRIVATE_EXECUTOR_ADMISSION")

    def test_open_state_and_review_stage_have_different_semantics(self):
        for pending in ("AWAIT_REVIEW", "AWAIT_MERGE"):
            for cv, ov in (("OPEN", pending), (pending, "OPEN")):
                with self.subTest(cv=cv, ov=ov):
                    control, observed = fixtures(
                        "PR_GATE", cv, ov
                    )
                    self.assertEqual(
                        compare_claim(control, observed),
                        {"status": "UNKNOWN",
                         "reason": "OPEN_DOES_NOT_PROVE_REVIEW_STAGE"},
                    )

    def test_pr_open_not_review_readiness_but_merge_transition_drift(self):
        self.check("ALIGNED", "PR_GATE", "OPEN", "OPEN")
        self.check("POTENTIAL_MISMATCH", "PR_GATE", "OPEN", "MERGED")
        self.check("POTENTIAL_MISMATCH", "PR_GATE", "MERGED", "OPEN")

    def test_current_review_gate_has_merged_pr(self):
        self.check("POTENTIAL_MISMATCH")

    def test_same_stage(self):
        self.check("ALIGNED", "PR_GATE", "MERGED", "MERGED")

    def test_publication_unverified_not_promoted(self):
        self.check("UNKNOWN", "PUBLIC_ENTRY", "UNVERIFIED", "UNVERIFIED")

    def test_build_failure_not_public_accepted(self):
        self.check("POTENTIAL_MISMATCH", "PUBLIC_ENTRY", "VERIFIED", "FAILED")

    def test_physical_not_inferred_from_source_merges(self):
        self.check("UNKNOWN", "FIELD_ACCEPTANCE", "ACCEPTED", "UNKNOWN")

    def test_different_pr_not_comparable(self):
        self.check("NOT_COMPARABLE", o__subject="kinoko34077/kinotch-repo-monitor#88")

    def test_different_axis_not_comparable(self):
        self.check("NOT_COMPARABLE", o__dimension="PUBLIC_ENTRY")

    def test_legacy_history_not_current(self):
        self.check("UNKNOWN", c__section="Historical progress")

    def test_old_note_not_assertion(self):
        self.check("UNKNOWN", c__section="Control Notes")

    def test_ambiguous_control_is_not_a_claim(self):
        self.check("UNKNOWN", c__is_current=False)

    def test_incomplete_pagination(self):
        self.check("UNKNOWN", o__source_complete=False)

    def test_untrusted_claim(self):
        self.check("UNKNOWN", c__source_verified=False)

    def test_untrusted_live_evidence(self):
        self.check("UNKNOWN", o__source_verified=False)

    def test_invalid_url_disallowed(self):
        self.check("UNKNOWN", o__source_url="http://github.com/example")

    def test_control_url_disallowed(self):
        self.check("UNKNOWN", c__source_url="https://example.org/fake")

    def test_naive_timestamp_fail_closed(self):
        self.check("UNKNOWN", o__read_at="2026-10-19T07:00:00")

    def test_unknown_state_fail_closed(self):
        self.check("UNKNOWN", o__value="PASS")

    def test_not_tested_is_not_pass(self):
        self.check("UNKNOWN", "FIELD_ACCEPTANCE", "ACCEPTED", "UNVERIFIED")

    def test_audited_vs_open_pr_does_not_compare(self):
        self.check("UNKNOWN", c__dimension="WORK_STATUS", c__value="AUDITED")

    def test_owner_remains_open_after_partial_merge(self):
        self.check("ALIGNED", "PR_GATE", "MERGED", "MERGED", c__section="Active Work")

    def test_password_only_github_userinfo_rejected(self):
        self.check("UNKNOWN", o__source_url="https://:pw@github.com/kinoko34077/kinotch-repo-monitor/pull/85")

    def test_noncanonical_github_port_rejected(self):
        self.check("UNKNOWN", o__source_url="https://github.com:8443/kinoko34077/kinotch-repo-monitor/pull/85")

    def test_other_repo_source_does_not_attest_subject(self):
        self.check("UNKNOWN", o__source_url="https://github.com/other/repository/pull/85")

    def test_other_pr_number_does_not_attest_subject(self):
        self.check("UNKNOWN", o__source_url="https://github.com/kinoko34077/kinotch-repo-monitor/pull/86")

    def test_control_must_be_devflow_issue(self):
        self.check("UNKNOWN", c__source_url="https://github.com/kinoko34077/devflow/pull/59")

    def test_observation_cannot_predate_control_read(self):
        self.check("UNKNOWN", o__read_at="2026-10-19T18:15:59+09:00")

    def test_hour_old_read_not_sufficient_for_current_state(self):
        self.check("UNKNOWN", o__read_at="2026-10-19T19:16:01+09:00")

    def test_non_mapping_input_is_unknown(self):
        self.assertEqual(compare_claim(None, {})["status"], "UNKNOWN")

    def test_unhashable_section_fails_closed(self):
        self.check("UNKNOWN", c__section=["Next Action"])
        self.check("UNKNOWN", c__section={})

    def test_explicit_failed_field_observation_contradicts_accepted(self):
        self.check("POTENTIAL_MISMATCH", "FIELD_ACCEPTANCE", "ACCEPTED", "REJECTED")

    def test_control_claims_verified_but_no_public_evidence(self):
        self.check("UNKNOWN", "PUBLIC_ENTRY", "VERIFIED", "UNVERIFIED")

    def test_same_observed_field_acceptance_is_aligned(self):
        self.check("ALIGNED", "FIELD_ACCEPTANCE", "ACCEPTED", "ACCEPTED")


if __name__ == "__main__":
    unittest.main()
