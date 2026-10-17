"""SMC v2 projection compatibility and non-credit boundary regressions."""
import unittest

from tools.maintenance_catalog import Scope
from tools.maintenance_coverage import LedgerEvidence
from tools.maintenance_coverage_v2 import (
    AttestedLedgerEvidence, derive_dual_version_coverage,
)
from tools.maintenance_run_attestation import AttestedRun
from tests.test_maintenance_coverage import (
    REPO, CURRENT, OLDER, SOURCE, evidence, record, slot,
)

DIGEST = "sha256:" + "d" * 64
KEY = REPO + "::common.correctness"


def attested(author="OWNER", **changes):
    att = AttestedRun(
        record=changes.pop("record", record()),
        scope=changes.pop("scope", Scope("repository", ".")),
        coverage_key=changes.pop("coverage_key", "common.correctness"),
        catalog_digest=changes.pop("catalog_digest", DIGEST),
    )
    return AttestedLedgerEvidence(att, SOURCE, author)


def rows(v1=(), v2=(), fp=CURRENT, catalog=DIGEST, s=None):
    a = slot() if s is None else s
    return derive_dual_version_coverage(
        (a,), v1, v2,
        {REPO + "::" + a.slot_id: fp} if fp is not None else {},
        {REPO: catalog} if catalog is not None else {},
        ("STANDARD",),
    )


class ScopeAttestationProjectionTests(unittest.TestCase):
    def test_no_new_attestation_preserves_v1_conservative_status(self):
        self.assertEqual("LEGACY_SCOPE_UNBOUND",
                         rows(v1=(evidence(),))[0].status)

    def test_current_valid_v2_matching_metadata_is_scope_attested_only(self):
        row = rows(v2=(attested(),))[0]
        self.assertEqual("ATTESTED_SCOPE_MATCH", row.status)
        self.assertIn("independent", row.reason)
        self.assertEqual(record().run_id, row.run_id)

    def test_untrusted_v2_cannot_credit_any_coverage(self):
        self.assertEqual("UNTRUSTED", rows(v2=(attested(author="CONTRIBUTOR"),))[0].status)

    def test_catalog_change_prevents_scope_attestation(self):
        self.assertEqual("CATALOG_DRIFT", rows(v2=(attested(),), catalog="sha256:" + "e"*64)[0].status)
        self.assertEqual("UNKNOWN_CATALOG", rows(v2=(attested(),), catalog=None)[0].status)

    def test_scope_and_coverage_key_change_do_not_inherit_result(self):
        for changed in (
            attested(scope=Scope("component", "different")),
            attested(coverage_key="new.scope"),
        ):
            with self.subTest(changed=changed):
                self.assertEqual("SCOPE_DRIFT", rows(v2=(changed,))[0].status)

    def test_real_source_fingerprint_missing_or_drifted(self):
        self.assertEqual("UNKNOWN_FINGERPRINT", rows(v2=(attested(),), fp=None)[0].status)
        self.assertEqual("SOURCE_DRIFT", rows(v2=(attested(),), fp=OLDER)[0].status)

    def test_incomplete_v2_run_has_no_coverage(self):
        for result in ("BLOCKED", "SUPERSEDED", "NEEDS_REAUDIT"):
            with self.subTest(result=result):
                a = attested(record=record(result=result))
                self.assertEqual("NO_COVERAGE", rows(v2=(a,))[0].status)

    def test_no_actual_evidence_refs_is_insufficient(self):
        a = attested(record=record(evidence_refs=()))
        self.assertEqual("INSUFFICIENT_EVIDENCE", rows(v2=(a,))[0].status)

    def test_v2_may_not_reuse_v1_run_id(self):
        self.assertEqual("AMBIGUOUS_HISTORY",
                         rows(v1=(evidence(),), v2=(attested(),))[0].status)

    def test_conflicting_v2_same_run_id_is_ambiguous(self):
        a = attested()
        b = attested(catalog_digest="sha256:"+"f"*64)
        self.assertEqual("AMBIGUOUS_HISTORY", rows(v2=(a, b))[0].status)

    def test_newer_failed_v2_overrides_prior_v1_success(self):
        failure = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:2",
            generation=2,
            completed_at="2026-10-10T00:00:00Z", result="BLOCKED",
        ))
        self.assertEqual("NO_COVERAGE",
                         rows(v1=(evidence(),), v2=(failure,))[0].status)

    def test_newer_legacy_v1_is_not_upgraded_with_old_v2_scope(self):
        prev = attested()
        later = evidence(
            run_id=f"audit:{REPO}:common.correctness:3",
            generation=3,
            completed_at="2026-10-11T00:00:00Z",
        )
        self.assertEqual("LEGACY_SCOPE_UNBOUND",
                         rows(v1=(later,), v2=(prev,))[0].status)

    def test_v2_changed_lens_is_not_valid_current_lens(self):
        self.assertEqual("LENS_DRIFT",
                         rows(v2=(attested(),), s=slot(lens="security"))[0].status)


    def test_v2_generation_ten_blocked_overrides_nine_clean_same_timestamp(self):
        old = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:9",
            generation=9, result="CLEAN",
            completed_at="2026-10-17T00:00:00Z",
        ))
        new = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:10",
            generation=10, result="BLOCKED",
            completed_at="2026-10-17T00:00:00Z",
        ))
        self.assertEqual("NO_COVERAGE", rows(v2=(old, new))[0].status)

    def test_same_timestamp_later_v1_generation_never_borrows_v2_scope(self):
        old_v2 = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:9",
            generation=9,
            completed_at="2026-10-17T00:00:00Z",
        ))
        new_v1 = evidence(
            run_id=f"audit:{REPO}:common.correctness:10",
            generation=10, result="BLOCKED",
            completed_at="2026-10-17T00:00:00Z",
        )
        self.assertEqual("NO_COVERAGE", rows(v1=(new_v1,), v2=(old_v2,))[0].status)

    def test_same_timestamp_later_v2_generation_takes_precedence_over_v1(self):
        old_v1 = evidence(
            run_id=f"audit:{REPO}:common.correctness:9",
            generation=9, result="BLOCKED",
            completed_at="2026-10-17T00:00:00Z",
        )
        new_v2 = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:10",
            generation=10, result="CLEAN",
            completed_at="2026-10-17T00:00:00Z",
        ))
        self.assertEqual(
            "ATTESTED_SCOPE_MATCH",
            rows(v1=(old_v1,), v2=(new_v2,))[0].status,
        )

    def test_mixed_clock_reversal_is_ambiguous(self):
        earlier = evidence(
            run_id=f"audit:{REPO}:common.correctness:9",
            generation=9, result="BLOCKED",
            completed_at="2026-10-17T12:00:00Z",
        )
        later = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:10",
            generation=10, result="CLEAN",
            completed_at="2026-10-17T11:00:00Z",
        ))
        self.assertEqual(
            "AMBIGUOUS_HISTORY",
            rows(v1=(earlier,), v2=(later,))[0].status,
        )

    def test_ambiguous_legacy_history_cannot_be_overridden_by_v2(self):
        old_a = evidence(
            run_id=f"audit:{REPO}:common.correctness:1",
            generation=1, result="CLEAN",
            completed_at="2026-10-16T00:00:00Z",
        )
        old_b = evidence(
            run_id=f"audit:{REPO}:common.correctness:1",
            generation=1, result="FINDINGS",
            completed_at="2026-10-16T00:00:00Z",
        )
        later = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:2",
            generation=2, result="CLEAN",
            completed_at="2026-10-17T00:00:00Z",
        ))
        self.assertEqual(
            "AMBIGUOUS_HISTORY",
            rows(v1=(old_a, old_b), v2=(later,))[0].status,
        )

    def test_v2_generation_timestamp_reversal_is_ambiguous(self):
        prior = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:9",
            generation=9, result="BLOCKED",
            completed_at="2026-10-17T12:00:00Z",
        ))
        later = attested(record=record(
            run_id=f"audit:{REPO}:common.correctness:10",
            generation=10, result="CLEAN",
            completed_at="2026-10-17T11:00:00Z",
        ))
        self.assertEqual(
            "AMBIGUOUS_HISTORY",
            rows(v2=(prior, later))[0].status,
        )

if __name__ == "__main__":
    unittest.main()
