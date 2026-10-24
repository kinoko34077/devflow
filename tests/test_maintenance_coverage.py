"""Regression contracts for conservative Standing Maintenance coverage projection."""
import unittest

from tools.maintenance_catalog import ResolvedSlot, Scope
from tools.maintenance_coverage import LedgerEvidence, derive_coverage
from tools.maintenance_ledger import RunRecord

REPO = "kinoko34077/example"
CURRENT = "sha256:" + "a" * 64
OLDER = "sha256:" + "b" * 64
SOURCE = "https://github.com/kinoko34077/example/issues/50#issuecomment-123"


def slot(**changes):
    data = dict(
        repository=REPO,
        slot_id="common.correctness",
        title="Correctness",
        lifecycle="ACTIVE",
        scope=Scope(kind="repository", selector="."),
        lens="correctness",
        coverage_key="common.correctness",
        risk="MEDIUM",
        cadence_class="GENERAL",
        minimum_depth="STANDARD",
        external_freshness_class="NORMAL",
        description="A scoped audit",
        source="common",
    )
    data.update(changes)
    return ResolvedSlot(**data)


def record(**changes):
    data = dict(
        repository=REPO,
        run_id="audit:" + REPO + ":common.correctness:1",
        slot_id="common.correctness",
        generation=1,
        lens="correctness",
        depth="STANDARD",
        fingerprint=CURRENT,
        result="CLEAN",
        findings_summary="none",
        completed_at="2026-10-07T00:00:00Z",
        next_eligibility_reason=None,
        evidence_refs=(SOURCE,),
    )
    data.update(changes)
    return RunRecord(**data)


def evidence(author="OWNER", source=SOURCE, **changes):
    user = (
        {"id": 79015263, "login": "kinoko34077"}
        if author in {"OWNER", "MEMBER", "COLLABORATOR"}
        else {"id": 123456789, "login": "untrusted"}
    )
    return LedgerEvidence(record(**changes), source, author, user)


def status(items=(), fp=CURRENT, s=None, depths=("STANDARD",)):
    obj = slot() if s is None else s
    return derive_coverage((obj,), items, {REPO + "::" + obj.slot_id: fp}, depths)


class ConservativeCoverageTests(unittest.TestCase):
    def test_unexecuted_slot_is_not_run(self):
        rows = status()
        self.assertEqual("NOT_RUN", rows[0].status)
        self.assertIsNone(rows[0].run_id)

    def test_accepted_legacy_run_is_not_false_current_scope_proof(self):
        row = status((evidence(),))[0]
        self.assertEqual("LEGACY_SCOPE_UNBOUND", row.status)
        self.assertEqual("repository", row.scope_kind)
        self.assertEqual(".", row.scope_selector)
        self.assertEqual(SOURCE, row.evidence_url)
        self.assertIn("scope", row.reason)

    def test_findings_count_as_legacy_audit_not_clean(self):
        row = status((evidence(result="FINDINGS"),))[0]
        self.assertEqual("LEGACY_SCOPE_UNBOUND", row.status)

    def test_failed_provider_has_zero_audit_coverage(self):
        for result in ("BLOCKED", "SUPERSEDED", "NEEDS_REAUDIT"):
            with self.subTest(result=result):
                row = status((evidence(result=result),))[0]
                self.assertEqual("NO_COVERAGE", row.status)

    def test_revised_source_fingerprint_is_drift(self):
        row = status((evidence(fingerprint=OLDER),))[0]
        self.assertEqual("SOURCE_DRIFT", row.status)

    def test_missing_or_invalid_current_source_is_unknown(self):
        for fp in (None, "sha256:bogus", ""):
            with self.subTest(fp=fp):
                row = status((evidence(),), fp=fp)[0]
                self.assertEqual("UNKNOWN_FINGERPRINT", row.status)

    def test_unknown_author_and_forged_repository_origin_are_rejected(self):
        for item in (
            evidence(author="CONTRIBUTOR"),
            evidence(source="https://github.com/kinoko34077/other/issues/1#issuecomment-2"),
            evidence(source="https://github.com/kinoko34077/example/issues/50"),
        ):
            with self.subTest(item=item):
                self.assertEqual("UNTRUSTED", status((item,))[0].status)

    def test_missing_evidence_ref_is_not_accepted(self):
        row = status((evidence(evidence_refs=()),))[0]
        self.assertEqual("INSUFFICIENT_EVIDENCE", row.status)

    def test_changed_lens_cannot_inherit_prior_coverage(self):
        row = status((evidence(),), s=slot(lens="security"))[0]
        self.assertEqual("LENS_DRIFT", row.status)

    def test_conflicting_duplicate_run_is_fail_closed(self):
        first = evidence()
        second = evidence(result="FINDINGS")
        self.assertEqual("AMBIGUOUS_HISTORY", status((first, second))[0].status)

    def test_deep_must_not_inherit_standard(self):
        rows = status((evidence(),), depths=("STANDARD", "DEEP"))
        self.assertEqual(("LEGACY_SCOPE_UNBOUND", "NOT_RUN"), tuple(r.status for r in rows))

    def test_retired_and_merged_slots_are_not_runnable(self):
        for lc in ("RETIRED", "SUPERSEDED", "MERGED"):
            with self.subTest(lc=lc):
                self.assertEqual((), status((evidence(),), s=slot(lifecycle=lc)))

    def test_duplicate_slots_and_depths_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            derive_coverage((slot(), slot()), (), {})
        with self.assertRaisesRegex(ValueError, "depths"):
            status(depths=("STANDARD", "STANDARD"))

    def test_multiple_repos_do_not_cross_credit(self):
        other = "kinoko34077/other"
        s = slot(repository=other)
        rows = derive_coverage((s,), (evidence(),), {other + "::common.correctness": CURRENT})
        self.assertTrue(all(r.status == "NOT_RUN" for r in rows))

    def test_later_blocked_record_supersedes_apparent_current_success(self):
        later = evidence(
            run_id="audit:" + REPO + ":common.correctness:2",
            generation=2,
            result="BLOCKED",
            completed_at="2026-10-10T00:00:00Z",
        )
        row = status((evidence(), later))[0]
        self.assertEqual("NO_COVERAGE", row.status)


    def test_generation_ten_blocked_overrides_generation_nine_clean_at_equal_timestamp(self):
        clean = evidence(
            run_id="audit:" + REPO + ":common.correctness:9",
            generation=9,
            result="CLEAN",
            completed_at="2026-10-17T00:00:00Z",
        )
        blocked = evidence(
            run_id="audit:" + REPO + ":common.correctness:10",
            generation=10,
            result="BLOCKED",
            completed_at="2026-10-17T00:00:00Z",
        )
        # A lexical run_id sort would incorrectly select ':9' over ':10'.
        self.assertEqual("NO_COVERAGE", status((clean, blocked))[0].status)

    def test_clock_reversal_never_promotes_stale_clean_as_current(self):
        prior = evidence(
            run_id="audit:" + REPO + ":common.correctness:9",
            generation=9,
            result="BLOCKED",
            completed_at="2026-10-17T12:00:00Z",
        )
        later_generation = evidence(
            run_id="audit:" + REPO + ":common.correctness:10",
            generation=10,
            result="CLEAN",
            completed_at="2026-10-17T11:00:00Z",
        )
        self.assertEqual(
            "AMBIGUOUS_HISTORY",
            status((prior, later_generation))[0].status,
        )

if __name__ == "__main__":
    unittest.main()
