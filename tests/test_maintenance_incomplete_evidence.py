"""M4 regression: non-executed maintenance must never suppress real audit supply."""
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from tools import maintenance_github as gh
from tools import maintenance_selector as ms
from tools.maintenance_catalog import ResolvedSlot, Scope
from tools.maintenance_ledger import RunRecord

REPO = "kinoko34077/devflow"
KEY = REPO + "::common.correctness"
SHA = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def slot():
    return ResolvedSlot(
        repository=REPO, slot_id="common.correctness", title="Correctness",
        lifecycle="ACTIVE", scope=Scope("repository", "."), lens="correctness",
        coverage_key="common.correctness", risk="HIGH", cadence_class="GENERAL",
        minimum_depth="STANDARD", external_freshness_class="NORMAL",
        description="real audit", source="common",
    )


def context():
    return ms.SelectionContext(
        observed_at=NOW, target_repository=REPO, previous_repository=None,
        eligible_repositories=frozenset({REPO}), current_fingerprints={KEY: SHA},
        relevant_changes=frozenset(), security_events=frozenset(),
        finding_reaudits=frozenset(), external_stale=frozenset(),
        incomplete_evidence=frozenset(), recovery_needed=frozenset(),
        explicit_user_requests=frozenset(), justified_deep=frozenset(),
        blocked_slots=frozenset(),
        risk_policy={"HIGH": {
            "general_standard_days": 30, "security_standard_days": 21,
            "deep_target_days": 60, "cooldown_hours": 24,
        }},
        selector_weights={
            "never_run": 40, "unexecuted_lens": 15, "overdue": 20,
            "overdue_2x_bonus": 10, "deeper_coverage": 15, "source_change": 25,
            "high_risk": 15, "critical_risk": 25, "finding_reaudit": 20,
            "security_event": 30, "external_stale": 20,
            "same_repository_penalty": -10, "recent_similar_penalty": -20,
        },
    )


def record(result):
    return RunRecord(
        repository=REPO, run_id="audit:" + REPO + ":common.correctness:1",
        slot_id="common.correctness", generation=1, lens="correctness",
        depth="STANDARD", fingerprint=SHA, result=result,
        findings_summary="test", completed_at="2026-10-15T00:00:00Z",
        next_eligibility_reason=None,
        evidence_refs=("https://github.com/kinoko34077/devflow/issues/367",),
    )


def history(result):
    return ms.RunEvidence(
        repository=REPO, slot_id="common.correctness", lens="correctness",
        coverage_key="common.correctness", scope_kind="repository",
        scope_selector=".", depth="STANDARD", fingerprint=SHA,
        completed_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
        evidence_complete=gh._completed_audit_evidence(record(result)),
    )


class RealCompletionOnlyTests(unittest.TestCase):
    def test_converters_disallow_blocked_superseded_and_reaudit(self):
        for result in ("BLOCKED", "SUPERSEDED", "NEEDS_REAUDIT"):
            with self.subTest(result=result):
                self.assertFalse(gh._completed_audit_evidence(record(result)))

    def test_converters_only_accept_substantive_results(self):
        for result in ("CLEAN", "FINDINGS", "RECONCILED"):
            with self.subTest(result=result):
                self.assertTrue(gh._completed_audit_evidence(record(result)))

    def test_incomplete_exact_run_is_eligible_not_falsely_suppressed(self):
        s = slot()
        for result in ("BLOCKED", "SUPERSEDED", "NEEDS_REAUDIT"):
            with self.subTest(result=result):
                prior = (history(result),)
                scoring = ms.score_slot(s, context(), prior)
                self.assertIsNotNone(scoring)
                self.assertIn(("never_run", 40), scoring.components)
                self.assertIn(("unexecuted_lens", 15), scoring.components)
                candidate = ms.select_maintenance((s,), context(), prior)
                self.assertIsNotNone(candidate)
                self.assertEqual(s.slot_id, candidate.slot.slot_id)

    def test_complete_recent_exact_run_still_suppresses_redundant_audit(self):
        for result in ("CLEAN", "FINDINGS", "RECONCILED"):
            with self.subTest(result=result):
                self.assertIsNone(ms.score_slot(slot(), context(), (history(result),)))
                self.assertIsNone(ms.select_maintenance((slot(),), context(), (history(result),)))

    def test_no_penalty_from_incomplete_similar_scope(self):
        s = slot()
        ctx = ms.replace_context(context(), current_fingerprints={KEY: SHA})
        prior = (replace(history("BLOCKED"), scope_selector="another-scope"),)
        score = ms.score_slot(s, ctx, prior)
        self.assertNotIn("recent_similar_penalty", dict(score.components))

    def test_incomplete_does_not_satisfy_deep_or_lens_coverage(self):
        s = slot()
        ctx = ms.replace_context(context(), justified_deep=frozenset({KEY}))
        rec = ms.RunEvidence(
            repository=REPO, slot_id=s.slot_id, lens=s.lens,
            coverage_key=s.coverage_key, scope_kind="repository", scope_selector=".",
            depth="DEEP", fingerprint=SHA,
            completed_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
            evidence_complete=False,
        )
        score = ms.score_slot(s, ctx, (rec,))
        self.assertIn(("deeper_coverage", 15), score.components)


if __name__ == "__main__":
    unittest.main()
