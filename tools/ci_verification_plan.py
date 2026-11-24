"""CI verification planning (#1121), independent of MCP and Actions.

Requirements must be constructed from the applicable trusted policy; observations
must come from an authenticated collector of current evidence. This comparator
neither authenticates evidence nor authorizes a check, skip, merge or write.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Requirement:
    repository: str
    guarantee: str
    identity: Mapping[str, str]


@dataclass(frozen=True)
class Observation:
    requirement: Requirement
    outcome: str
    source_ref: str
    # None only for a guarantee whose evidence does not expire with time.
    valid_until: datetime | None


@dataclass(frozen=True)
class Decision:
    action: str  # RUN | WAIT | REUSE_CANDIDATE | HOLD
    reason: str
    evidence_refs: tuple[str, ...] = ()


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _identified(requirement: Requirement) -> bool:
    identity = requirement.identity
    return (
        _nonblank(requirement.repository)
        and _nonblank(requirement.guarantee)
        and isinstance(identity, Mapping)
        and bool(identity)
        and all(_nonblank(k) and _nonblank(v) for k, v in identity.items())
    )


def assess_verification(
    required: Requirement,
    observations: Iterable[Observation],
    *,
    now: datetime,
) -> Decision:
    """Compare a single required guarantee with current trusted observations.

    Identity contains all and only the relevant inputs under the owning policy.
    A collector must resolve current attempts, freshness and provenance before
    calling this function. Historical attempts must not be passed as current.
    WAIT is coalescing advice, not evidence. REUSE_CANDIDATE requires a separate
    authorized consumer to validate the applicable native gate.
    """
    if not _identified(required) or not _aware(now):
        return Decision("HOLD", "REQUIREMENT_IDENTITY_UNKNOWN")
    matching = []
    for observed in observations:
        if observed.requirement != required:
            continue
        expiry = observed.valid_until
        if expiry is not None and (not _aware(expiry) or expiry <= now):
            continue
        matching.append(observed)

    if not matching:
        return Decision("RUN", "NO_CURRENT_EQUIVALENT_EVIDENCE")
    if any(not _nonblank(item.source_ref) for item in matching):
        return Decision("RUN", "EVIDENCE_REFERENCE_MISSING")

    active = tuple(sorted({item.source_ref for item in matching
                           if item.outcome in ("queued", "in_progress")}))
    if active:
        return Decision("WAIT", "EQUIVALENT_VERIFICATION_ACTIVE", active)
    if any(item.outcome != "success" for item in matching):
        return Decision("RUN", "CURRENT_EVIDENCE_NOT_SUCCESSFUL")
    return Decision(
        "REUSE_CANDIDATE", "EQUIVALENT_SUCCESS",
        tuple(sorted({item.source_ref for item in matching})),
    )
