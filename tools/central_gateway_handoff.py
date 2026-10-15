"""F2C *read-only* central Claim handoff preflight; never a cutover tool.

All evidence is caller-supplied data, not an authenticated GitHub observation,
credential, fencing authority, or permission grant. Even REVIEW_ONLY is merely
a checklist projection for independent live verification and Human approval.
This module has no network, storage writes, Actions control or Claim mutation.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

_LEGACY = "kinoko34077/execution-coordinator#3"
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SCOPE = re.compile(r"[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*\Z")
_MAX_AGE_SECONDS = 120


@dataclass(frozen=True)
class LegacyEvidence:
    authority_issue: str
    snapshot_sha256: str
    observed_at: int
    source_authenticated: bool
    fence_epoch: int
    active_claims: int
    queued_mutations: int
    actions_writer_enabled: bool
    actions_writer_fenced: bool
    stale_actions_reentry_rejected: bool


@dataclass(frozen=True)
class CentralEvidence:
    source_snapshot_sha256: str
    observed_at: int
    source_authenticated: bool
    epoch: int
    writer_enabled: bool
    ledger_atomic_cas: bool
    stale_epoch_rejected: bool
    queue_quiescent: bool
    store_available: bool
    github_api_available: bool
    policy_and_identity_authenticated: bool


@dataclass(frozen=True)
class HandoffIntent:
    expected_legacy_sha256: str
    next_epoch: int
    repositories: tuple[str, ...]
    boundary: str = "SHADOW_ONLY"


@dataclass(frozen=True)
class HandoffAssessment:
    status: str
    reason: str
    evidence_sha256: str | None
    non_authorizing: bool = True


def _valid_scalar(value: object) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


def _valid_positive(value: object) -> bool:
    return _valid_scalar(value) and value > 0


def _valid_sha(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _valid_repositories(repositories: object) -> bool:
    return (
        type(repositories) is tuple and 0 < len(repositories) <= 32
        and all(type(r) is str and _SCOPE.fullmatch(r) is not None
                and all(not part.startswith((".", "-")) and
                        not part.endswith(".git") for part in r.split("/"))
                for r in repositories)
        and len(set(repositories)) == len(repositories)
    )


def _assessment(reason: str, *, checksum: str | None = None) -> HandoffAssessment:
    return HandoffAssessment(
        "REVIEW_ONLY" if reason == "FENCING_PREFLIGHT_PASSED" else "HOLD",
        reason, checksum,
    )


def evaluate_handoff(
    legacy: LegacyEvidence,
    central: CentralEvidence,
    intent: HandoffIntent,
    *,
    now: int,
) -> HandoffAssessment:
    """Non-effectful proof checklist, not authentication or a permission grant.

    Must be fed by a future separately accepted, authenticated, fresh observer.
    Its result must NEVER be read by a mutation, runner or token minting path.
    """
    if (type(legacy) is not LegacyEvidence or
            type(central) is not CentralEvidence or
            type(intent) is not HandoffIntent or not _valid_scalar(now)):
        return _assessment("MALFORMED_EVIDENCE")
    if (legacy.authority_issue != _LEGACY or
            not _valid_sha(legacy.snapshot_sha256) or
            not _valid_sha(central.source_snapshot_sha256) or
            not _valid_sha(intent.expected_legacy_sha256) or
            not _valid_positive(legacy.fence_epoch) or
            not _valid_positive(central.epoch) or
            not _valid_positive(intent.next_epoch) or
            not _valid_scalar(legacy.active_claims) or
            not _valid_scalar(legacy.queued_mutations) or
            not _valid_repositories(intent.repositories) or
            intent.boundary != "SHADOW_ONLY"):
        return _assessment("INVALID_SCOPE_OR_SNAPSHOT")
    fields = (
        legacy.source_authenticated, legacy.actions_writer_enabled,
        legacy.actions_writer_fenced, legacy.stale_actions_reentry_rejected,
        central.source_authenticated, central.writer_enabled,
        central.ledger_atomic_cas, central.stale_epoch_rejected,
        central.queue_quiescent, central.store_available,
        central.github_api_available, central.policy_and_identity_authenticated,
    )
    if any(type(x) is not bool for x in fields):
        return _assessment("INVALID_EVIDENCE_TYPES")
    if (not _valid_scalar(legacy.observed_at) or
            not _valid_scalar(central.observed_at) or
            not 0 <= now - legacy.observed_at <= _MAX_AGE_SECONDS or
            not 0 <= now - central.observed_at <= _MAX_AGE_SECONDS):
        return _assessment("STALE_OR_FUTURE_SNAPSHOT")
    if not legacy.source_authenticated or not central.source_authenticated:
        return _assessment("UNAUTHENTICATED_SNAPSHOT")
    if (legacy.snapshot_sha256 != central.source_snapshot_sha256 or
            legacy.snapshot_sha256 != intent.expected_legacy_sha256):
        return _assessment("SOURCE_SNAPSHOT_MISMATCH")
    if (legacy.actions_writer_enabled or not legacy.actions_writer_fenced or
            not legacy.stale_actions_reentry_rejected):
        return _assessment("LEGACY_WRITER_NOT_FENCED")
    if legacy.active_claims or legacy.queued_mutations:
        return _assessment("LEGACY_WORK_NOT_QUIESCENT")
    if central.writer_enabled or not central.queue_quiescent:
        return _assessment("CENTRAL_LANE_ALREADY_ACTIVE")
    if (not central.store_available or not central.github_api_available or
            not central.policy_and_identity_authenticated):
        return _assessment("CENTRAL_TRUST_OR_AVAILABILITY_MISSING")
    if not central.ledger_atomic_cas or not central.stale_epoch_rejected:
        return _assessment("NO_SINGLE_WRITER_FENCE_PROOF")
    if (intent.next_epoch <= legacy.fence_epoch or
            intent.next_epoch != central.epoch or
            intent.next_epoch != legacy.fence_epoch + 1):
        return _assessment("NONMONOTONIC_OR_MISMATCHED_EPOCH")
    # Digest is a checksum for comparison, NOT a signature, capability, or
    # permission token; includes no secret, code or private job payload.
    data = json.dumps(
        {"domain": "devflow-f2c-shadow-v1",
         "legacy_issue": _LEGACY,
         "source": legacy.snapshot_sha256,
         "old_epoch": legacy.fence_epoch,
         "next_epoch": intent.next_epoch,
         "repositories": sorted(intent.repositories)},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    return _assessment(
        "FENCING_PREFLIGHT_PASSED",
        checksum=hashlib.sha256(data).hexdigest(),
    )


def project_writer_observation(
    *,
    old_writer_active: bool,
    central_writer_active: bool,
    old_epoch: int,
    central_epoch: int,
) -> HandoffAssessment:
    """Observe possible split brain. NEVER select/grant a live writer."""
    if (type(old_writer_active) is not bool or
            type(central_writer_active) is not bool or
            not _valid_positive(old_epoch) or
            not _valid_positive(central_epoch)):
        return _assessment("MALFORMED_EVIDENCE")
    if old_writer_active and central_writer_active:
        return _assessment("SPLIT_BRAIN_OBSERVED")
    if central_writer_active and central_epoch <= old_epoch:
        return _assessment("CENTRAL_STALE_EPOCH")
    if old_writer_active:
        return _assessment("LEGACY_OBSERVED_ONLY")
    if central_writer_active:
        return _assessment("CENTRAL_OBSERVED_ONLY_NOT_AUTHORIZED")
    return _assessment("NO_ACTIVE_WRITER")


def rollback_review(*, previous_epoch: int, current_epoch: int,
                    old_actions_still_fenced: bool) -> HandoffAssessment:
    """No rollback action; historic epochs can never become authoritative."""
    if (not _valid_positive(previous_epoch) or
            not _valid_positive(current_epoch) or
            type(old_actions_still_fenced) is not bool):
        return _assessment("MALFORMED_EVIDENCE")
    if not old_actions_still_fenced:
        return _assessment("OLD_PATH_REACTIVATION_UNSAFE")
    if previous_epoch >= current_epoch:
        return _assessment("NONMONOTONIC_ROLLBACK")
    return _assessment("ROLLBACK_REQUIRES_NEW_EPOCH_AND_HUMAN_REVIEW")
