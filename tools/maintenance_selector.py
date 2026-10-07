from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Mapping

from tools.maintenance_catalog import ResolvedSlot


RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


@dataclass(frozen=True)
class AuditFingerprint:
    digest: str


@dataclass(frozen=True)
class RunEvidence:
    repository: str
    slot_id: str
    lens: str
    coverage_key: str
    scope_kind: str
    scope_selector: str
    depth: str
    fingerprint: str
    completed_at: datetime
    evidence_complete: bool = True


@dataclass(frozen=True)
class SelectionContext:
    observed_at: datetime
    target_repository: str | None
    previous_repository: str | None
    eligible_repositories: frozenset[str]
    current_fingerprints: Mapping[str, str]
    relevant_changes: frozenset[str]
    security_events: frozenset[str]
    finding_reaudits: frozenset[str]
    external_stale: frozenset[str]
    incomplete_evidence: frozenset[str]
    recovery_needed: frozenset[str]
    explicit_user_requests: frozenset[str]
    justified_deep: frozenset[str]
    blocked_slots: frozenset[str]
    risk_policy: Mapping[str, Mapping[str, int]]
    selector_weights: Mapping[str, int]


@dataclass(frozen=True)
class ScoreBreakdown:
    total: int
    components: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class SelectionResult:
    slot: ResolvedSlot
    depth: str
    fingerprint: str
    score: int
    score_breakdown: ScoreBreakdown


def replace_context(context: SelectionContext, **changes: object) -> SelectionContext:
    return replace(context, **changes)


def canonical_fingerprint(value: Mapping[str, object]) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _slot_key(slot: ResolvedSlot) -> str:
    return f"{slot.repository}::{slot.slot_id}"


def _target_depth(slot: ResolvedSlot, context: SelectionContext) -> str:
    return "DEEP" if _slot_key(slot) in context.justified_deep else slot.minimum_depth


def _cadence_days(slot: ResolvedSlot, depth: str, context: SelectionContext) -> int:
    policy = context.risk_policy[slot.risk]
    if depth == "DEEP":
        return int(policy["deep_target_days"])
    if slot.cadence_class == "SECURITY":
        return int(policy["security_standard_days"])
    return int(policy["general_standard_days"])


def _cooldown(slot: ResolvedSlot, context: SelectionContext) -> timedelta:
    hours = int(context.risk_policy[slot.risk]["cooldown_hours"])
    return timedelta(hours=hours)


def _slot_history(slot: ResolvedSlot, history: tuple[RunEvidence, ...]) -> list[RunEvidence]:
    return [
        item
        for item in history
        if item.repository == slot.repository and item.slot_id == slot.slot_id
    ]


def _lens_history(slot: ResolvedSlot, history: tuple[RunEvidence, ...]) -> list[RunEvidence]:
    return [
        item
        for item in history
        if item.repository == slot.repository and item.lens == slot.lens
    ]


def _similar_history(slot: ResolvedSlot, history: tuple[RunEvidence, ...]) -> list[RunEvidence]:
    return [
        item
        for item in history
        if item.repository == slot.repository and item.coverage_key == slot.coverage_key
    ]


def _exact_equivalent(
    slot: ResolvedSlot,
    depth: str,
    fingerprint: str,
    item: RunEvidence,
) -> bool:
    return (
        item.repository == slot.repository
        and item.scope_kind == slot.scope.kind
        and item.scope_selector == slot.scope.selector
        and item.lens == slot.lens
        and item.depth == depth
        and item.fingerprint == fingerprint
    )


def _latest(values: list[RunEvidence]) -> RunEvidence | None:
    if not values:
        return None
    return max(values, key=lambda item: item.completed_at)


def _bypass(slot: ResolvedSlot, context: SelectionContext) -> bool:
    item = _slot_key(slot)
    return any(
        item in values
        for values in (
            context.relevant_changes,
            context.security_events,
            context.finding_reaudits,
            context.incomplete_evidence,
            context.recovery_needed,
            context.explicit_user_requests,
        )
    )


def _eligible(slot: ResolvedSlot, context: SelectionContext) -> bool:
    if slot.lifecycle != "ACTIVE":
        return False
    if context.target_repository is not None and slot.repository != context.target_repository:
        return False
    if slot.repository not in context.eligible_repositories:
        return False
    if _slot_key(slot) in context.blocked_slots:
        return False
    if slot.risk not in context.risk_policy:
        return False
    return True


def score_slot(
    slot: ResolvedSlot,
    context: SelectionContext,
    history: tuple[RunEvidence, ...],
) -> ScoreBreakdown | None:
    if not _eligible(slot, context):
        return None

    item_key = _slot_key(slot)
    fingerprint = context.current_fingerprints.get(item_key)
    if not isinstance(fingerprint, str) or not fingerprint.startswith("sha256:"):
        return None

    depth = _target_depth(slot, context)
    now = context.observed_at
    cooldown = _cooldown(slot, context)
    bypass = _bypass(slot, context)

    exact_runs = [
        item
        for item in history
        if _exact_equivalent(slot, depth, fingerprint, item)
    ]
    latest_exact = _latest(exact_runs)
    if latest_exact is not None and not bypass:
        exact_age = now - latest_exact.completed_at
        cadence = timedelta(days=_cadence_days(slot, depth, context))
        if exact_age <= cadence:
            return None

    weights = context.selector_weights
    components: list[tuple[str, int]] = []
    slot_runs = _slot_history(slot, history)
    lens_runs = _lens_history(slot, history)
    similar_runs = _similar_history(slot, history)

    def add(name: str) -> None:
        value = int(weights[name])
        if value:
            components.append((name, value))

    if not slot_runs:
        add("never_run")
    if not lens_runs:
        add("unexecuted_lens")

    latest_slot = _latest(slot_runs)
    if latest_slot is not None:
        age = now - latest_slot.completed_at
        cadence = timedelta(days=_cadence_days(slot, depth, context))
        if age > cadence:
            add("overdue")
        if age > cadence * 2:
            add("overdue_2x_bonus")

    if item_key in context.justified_deep:
        prior_deep = any(item.depth == "DEEP" for item in slot_runs)
        if not prior_deep:
            add("deeper_coverage")

    if item_key in context.relevant_changes:
        add("source_change")
    if slot.risk == "HIGH":
        add("high_risk")
    elif slot.risk == "CRITICAL":
        add("critical_risk")
    if item_key in context.finding_reaudits:
        add("finding_reaudit")
    if item_key in context.security_events:
        add("security_event")
    if item_key in context.external_stale:
        add("external_stale")
    if context.previous_repository == slot.repository:
        add("same_repository_penalty")

    latest_similar = _latest(similar_runs)
    if (
        latest_similar is not None
        and now - latest_similar.completed_at < cooldown
        and not _exact_equivalent(slot, depth, fingerprint, latest_similar)
    ):
        add("recent_similar_penalty")

    return ScoreBreakdown(
        total=sum(value for _, value in components),
        components=tuple(components),
    )


def _equivalent_age_seconds(
    slot: ResolvedSlot,
    depth: str,
    fingerprint: str,
    context: SelectionContext,
    history: tuple[RunEvidence, ...],
) -> float:
    values = [
        item
        for item in history
        if _exact_equivalent(slot, depth, fingerprint, item)
    ]
    latest = _latest(values)
    if latest is None:
        return float("inf")
    return max(0.0, (context.observed_at - latest.completed_at).total_seconds())


def _never_depth(slot: ResolvedSlot, depth: str, history: tuple[RunEvidence, ...]) -> int:
    return int(
        not any(
            item.repository == slot.repository
            and item.slot_id == slot.slot_id
            and item.depth == depth
            for item in history
        )
    )


def _never_lens(slot: ResolvedSlot, history: tuple[RunEvidence, ...]) -> int:
    return int(not _lens_history(slot, history))


def select_maintenance(
    slots: tuple[ResolvedSlot, ...],
    context: SelectionContext,
    history: tuple[RunEvidence, ...],
) -> SelectionResult | None:
    candidates: list[SelectionResult] = []
    for slot in slots:
        breakdown = score_slot(slot, context, history)
        if breakdown is None:
            continue
        fingerprint = context.current_fingerprints[_slot_key(slot)]
        depth = _target_depth(slot, context)
        candidates.append(
            SelectionResult(
                slot=slot,
                depth=depth,
                fingerprint=fingerprint,
                score=breakdown.total,
                score_breakdown=breakdown,
            )
        )

    if not candidates:
        return None

    def rank(result: SelectionResult) -> tuple[object, ...]:
        slot = result.slot
        age = _equivalent_age_seconds(
            slot,
            result.depth,
            result.fingerprint,
            context,
            history,
        )
        never_count = _never_depth(slot, result.depth, history) + _never_lens(slot, history)
        spread = int(context.previous_repository != slot.repository)
        return (
            -result.score,
            -RISK_RANK[slot.risk],
            -age,
            -never_count,
            -spread,
            slot.repository,
            slot.slot_id,
        )

    return min(candidates, key=rank)
