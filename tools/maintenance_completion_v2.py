"""Opt-in v2 maintenance completion provenance preflight.

This cannot assign work, authenticate a worker, or make audit claims. It only
constructs a strict source-bound identity envelope from the live native
GitHub GET transport for an already-active run. Version 2 must be explicit,
and existing workflow dispatch stays v1 until separately accepted.
"""
from __future__ import annotations

from tools.maintenance_catalog import canonical_catalog_digest
from tools.maintenance_github import (
    _catalog_bundle, _default_head, build_maintenance_fingerprint,
)
from tools.maintenance_ledger import ActiveRun, RunRecord
from tools.maintenance_run_attestation import (
    RunAttestationError, bind_attested_run, render_attested_run_comment,
)


def prepare_v2_completion(
    transport: object,
    active: ActiveRun,
    record: RunRecord,
    *,
    completion_attempt_id: str,
) -> str:
    """Fail before posting if active generation/catalog/code source is stale.

    The v2 source fingerprint check assumes no unverified external evidence.
    Any external/volatile fingerprint which cannot be reproduced from exact
    source HEAD and canonical catalog digest will be rejected, not guessed.
    """
    if not isinstance(completion_attempt_id, str) or not completion_attempt_id.strip():
        raise RunAttestationError("v2 completion requires an execution attempt")
    if completion_attempt_id == active.publisher_attempt_id:
        raise RunAttestationError("v2 completion cannot run in publisher attempt")

    baseline, catalog, slots, digest, code_sha, *_ = _catalog_bundle(
        transport, active.repository
    )
    if catalog.rollout not in ("PILOT", "ENABLED"):
        raise RunAttestationError("repository catalog rollout is not enabled")
    if digest != active.catalog_digest:
        raise RunAttestationError("catalog drift from active selection")
    if digest != canonical_catalog_digest(baseline, catalog):
        raise RunAttestationError("catalog digest is not internally consistent")
    expected_fingerprint = build_maintenance_fingerprint(code_sha, digest)
    if active.fingerprint != expected_fingerprint:
        raise RunAttestationError(
            "current source/external freshness cannot be proved from current HEAD"
        )
    if _default_head(transport, active.repository) != code_sha:
        raise RunAttestationError("repository HEAD changed during v2 preparation")
    matches = [slot for slot in slots if slot.slot_id == active.slot_id]
    if len(matches) != 1:
        raise RunAttestationError("exact active slot missing or ambiguous")
    proof = bind_attested_run(active, matches[0], record, digest)
    return render_attested_run_comment(proof)
