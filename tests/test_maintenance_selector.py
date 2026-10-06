import unittest
from datetime import datetime, timedelta, timezone

from tools.maintenance_catalog import ResolvedSlot, Scope
from tools import maintenance_selector as ms


UTC = timezone.utc
NOW = datetime(2026, 10, 7, 0, 0, tzinfo=UTC)


def slot(
    slot_id="common.correctness",
    repository="kinoko34077/a",
    *,
    risk="MEDIUM",
    lens="correctness",
    coverage_key=None,
    cadence_class="GENERAL",
    minimum_depth="STANDARD",
    scope=None,
):
    return ResolvedSlot(
        repository=repository,
        slot_id=slot_id,
        title=slot_id,
        lifecycle="ACTIVE",
        scope=scope or Scope("repository", "."),
        lens=lens,
        coverage_key=coverage_key or slot_id,
        risk=risk,
        cadence_class=cadence_class,
        minimum_depth=minimum_depth,
        external_freshness_class="NORMAL",
        description="test",
        source="common",
    )


def key(value):
    return f"{value.repository}::{value.slot_id}"


def history(
    value,
    *,
    days_ago=1,
    depth="STANDARD",
    fingerprint="sha256:" + "a" * 64,
    evidence_complete=True,
):
    return ms.RunEvidence(
        repository=value.repository,
        slot_id=value.slot_id,
        lens=value.lens,
        coverage_key=value.coverage_key,
        scope_kind=value.scope.kind,
        scope_selector=value.scope.selector,
        depth=depth,
        fingerprint=fingerprint,
        completed_at=NOW - timedelta(days=days_ago),
        evidence_complete=evidence_complete,
    )


def context(slots, **overrides):
    fingerprints = {
        key(value): ms.canonical_fingerprint(
            {"repository": value.repository, "slot": value.slot_id, "state": "current"}
        )
        for value in slots
    }
    value = ms.SelectionContext(
        observed_at=NOW,
        target_repository=None,
        previous_repository=None,
        eligible_repositories=frozenset(value.repository for value in slots),
        current_fingerprints=fingerprints,
        relevant_changes=frozenset(),
        security_events=frozenset(),
        finding_reaudits=frozenset(),
        external_stale=frozenset(),
        incomplete_evidence=frozenset(),
        recovery_needed=frozenset(),
        explicit_user_requests=frozenset(),
        justified_deep=frozenset(),
        blocked_slots=frozenset(),
        risk_policy={
            "LOW": {
                "general_standard_days": 90,
                "security_standard_days": 90,
                "deep_target_days": 180,
                "cooldown_hours": 168,
            },
            "MEDIUM": {
                "general_standard_days": 60,
                "security_standard_days": 45,
                "deep_target_days": 120,
                "cooldown_hours": 72,
            },
            "HIGH": {
                "general_standard_days": 30,
                "security_standard_days": 21,
                "deep_target_days": 60,
                "cooldown_hours": 24,
            },
            "CRITICAL": {
                "general_standard_days": 14,
                "security_standard_days": 7,
                "deep_target_days": 30,
                "cooldown_hours": 6,
            },
        },
        selector_weights={
            "never_run": 40,
            "overdue": 20,
            "overdue_2x_bonus": 10,
            "unexecuted_lens": 15,
            "deeper_coverage": 15,
            "source_change": 25,
            "high_risk": 15,
            "critical_risk": 25,
            "finding_reaudit": 20,
            "security_event": 30,
            "external_stale": 20,
            "same_repository_penalty": -10,
            "recent_similar_penalty": -20,
        },
    )
    return ms.replace_context(value, **overrides)


class SelectorScoreTests(unittest.TestCase):
    def test_never_run_score_is_explainable(self):
        value = slot()
        result = ms.select_maintenance((value,), context((value,)), ())
        self.assertEqual(55, result.score)
        self.assertEqual(
            (("never_run", 40), ("unexecuted_lens", 15)),
            result.score_breakdown.components,
        )

    def test_overdue_and_double_overdue_scores(self):
        value = slot()
        current = context((value,))
        fp = current.current_fingerprints[key(value)]

        one = ms.score_slot(value, current, (history(value, days_ago=61, fingerprint=fp),))
        self.assertEqual(20, one.total)
        self.assertIn(("overdue", 20), one.components)

        two = ms.score_slot(value, current, (history(value, days_ago=121, fingerprint=fp),))
        self.assertEqual(30, two.total)
        self.assertIn(("overdue_2x_bonus", 10), two.components)

    def test_risk_source_finding_security_and_external_weights(self):
        value = slot(risk="CRITICAL")
        current = context(
            (value,),
            relevant_changes=frozenset({key(value)}),
            finding_reaudits=frozenset({key(value)}),
            security_events=frozenset({key(value)}),
            external_stale=frozenset({key(value)}),
        )
        run = history(value, days_ago=1, fingerprint="sha256:" + "b" * 64)
        breakdown = ms.score_slot(value, current, (run,))
        components = dict(breakdown.components)
        self.assertEqual(25, components["critical_risk"])
        self.assertEqual(25, components["source_change"])
        self.assertEqual(20, components["finding_reaudit"])
        self.assertEqual(30, components["security_event"])
        self.assertEqual(20, components["external_stale"])

    def test_high_risk_weight_is_fifteen(self):
        value = slot(risk="HIGH")
        breakdown = ms.score_slot(value, context((value,)), ())
        self.assertEqual(15, dict(breakdown.components)["high_risk"])

    def test_same_repository_penalty(self):
        value = slot()
        current = context((value,), previous_repository=value.repository)
        breakdown = ms.score_slot(value, current, ())
        self.assertEqual(-10, dict(breakdown.components)["same_repository_penalty"])

    def test_recent_similar_coverage_penalty(self):
        value = slot(coverage_key="family")
        current = context((value,))
        run = history(
            value,
            days_ago=1,
            depth="CONTROL",
            fingerprint="sha256:" + "b" * 64,
        )
        breakdown = ms.score_slot(value, current, (run,))
        self.assertEqual(-20, dict(breakdown.components)["recent_similar_penalty"])

    def test_justified_unexecuted_deep_coverage_adds_fifteen(self):
        value = slot()
        current = context((value,), justified_deep=frozenset({key(value)}))
        run = history(value, days_ago=10, depth="STANDARD", fingerprint="sha256:" + "b" * 64)
        result = ms.select_maintenance((value,), current, (run,))
        self.assertEqual("DEEP", result.depth)
        self.assertEqual(15, dict(result.score_breakdown.components)["deeper_coverage"])


class SelectorEligibilityTests(unittest.TestCase):
    def test_exact_equivalent_inside_cooldown_is_ineligible(self):
        value = slot(risk="HIGH")
        current = context((value,))
        fp = current.current_fingerprints[key(value)]
        run = history(value, days_ago=0.5, fingerprint=fp)
        self.assertIsNone(ms.score_slot(value, current, (run,)))
        self.assertIsNone(ms.select_maintenance((value,), current, (run,)))

    def test_cooldown_bypass_triggers_allow_reaudit(self):
        value = slot(risk="HIGH")
        base = context((value,))
        fp = base.current_fingerprints[key(value)]
        run = history(value, days_ago=0.5, fingerprint=fp)
        fields = (
            "relevant_changes",
            "security_events",
            "finding_reaudits",
            "incomplete_evidence",
            "recovery_needed",
            "explicit_user_requests",
        )
        for field in fields:
            with self.subTest(field=field):
                current = ms.replace_context(base, **{field: frozenset({key(value)})})
                self.assertIsNotNone(ms.score_slot(value, current, (run,)))

    def test_blocked_or_rollout_ineligible_slot_is_filtered(self):
        a = slot(repository="kinoko34077/a")
        b = slot(slot_id="common.security", repository="kinoko34077/b", lens="security")
        current = context(
            (a, b),
            eligible_repositories=frozenset({"kinoko34077/a"}),
            blocked_slots=frozenset({key(a)}),
        )
        self.assertIsNone(ms.select_maintenance((a, b), current, ()))

    def test_repository_scope_never_returns_another_repository(self):
        a = slot(repository="kinoko34077/a", risk="LOW")
        b = slot(slot_id="common.security", repository="kinoko34077/b", risk="CRITICAL", lens="security")
        current = context((a, b), target_repository="kinoko34077/a")
        self.assertEqual("kinoko34077/a", ms.select_maintenance((a, b), current, ()).slot.repository)

    def test_portfolio_scope_can_select_other_repository(self):
        a = slot(repository="kinoko34077/a", risk="LOW")
        b = slot(slot_id="common.security", repository="kinoko34077/b", risk="CRITICAL", lens="security")
        result = ms.select_maintenance((a, b), context((a, b)), ())
        self.assertEqual("kinoko34077/b", result.slot.repository)

    def test_all_filtered_returns_none(self):
        value = slot()
        current = context((value,), eligible_repositories=frozenset())
        self.assertIsNone(ms.select_maintenance((value,), current, ()))


class SelectorDeterminismTests(unittest.TestCase):
    def test_input_order_does_not_change_selection(self):
        a = slot(repository="kinoko34077/a")
        b = slot(slot_id="common.security", repository="kinoko34077/b", lens="security")
        current = context((a, b))
        first = ms.select_maintenance((a, b), current, ())
        second = ms.select_maintenance((b, a), current, ())
        self.assertEqual(first.slot.repository, second.slot.repository)
        self.assertEqual(first.slot.slot_id, second.slot.slot_id)

    def test_equal_score_tie_break_prefers_higher_risk(self):
        low = slot(repository="kinoko34077/a", risk="LOW")
        high = slot(slot_id="common.edge-cases", repository="kinoko34077/b", risk="MEDIUM", lens="edge-cases")
        current = context((low, high))
        # Remove risk score difference to exercise tie-break specifically.
        current = ms.replace_context(
            current,
            selector_weights=dict(current.selector_weights, high_risk=0, critical_risk=0),
        )
        result = ms.select_maintenance((low, high), current, ())
        self.assertEqual("kinoko34077/b", result.slot.repository)

    def test_equal_score_tie_break_prefers_longer_since_equivalent_run(self):
        a = slot(repository="kinoko34077/a")
        b = slot(slot_id="common.edge-cases", repository="kinoko34077/b", lens="edge-cases")
        current = context((a, b))
        afp = "sha256:" + "a" * 64
        bfp = "sha256:" + "b" * 64
        current = ms.replace_context(
            current,
            current_fingerprints={key(a): afp, key(b): bfp},
        )
        runs = (
            history(a, days_ago=70, fingerprint=afp),
            history(b, days_ago=80, fingerprint=bfp),
        )
        result = ms.select_maintenance((a, b), current, runs)
        self.assertEqual("kinoko34077/b", result.slot.repository)

    def test_final_tie_break_is_lexical_repository_and_slot(self):
        a = slot(repository="kinoko34077/b")
        b = slot(repository="kinoko34077/a")
        result = ms.select_maintenance((a, b), context((a, b)), ())
        self.assertEqual("kinoko34077/a", result.slot.repository)


class FingerprintTests(unittest.TestCase):
    def test_canonical_fingerprint_ignores_mapping_key_order(self):
        a = ms.canonical_fingerprint({"b": 2, "a": 1})
        b = ms.canonical_fingerprint({"a": 1, "b": 2})
        self.assertEqual(a, b)
        self.assertRegex(a, r"^sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
