"""Versioned immutable run-scope attestation contract for future SMC completion.

This module is deliberately PURE/OFFLINE. Neither the accepted v1 publisher
nor runtime Claim/lease/supply writers are changed or activated by this module.
An attestation is NOT trusted merely because a comment contains this payload:
the caller must verify the original Ledger Issue, commenter association,
catalog revision and source fingerprint through trusted independent sources.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from tools.maintenance_catalog import ResolvedSlot, Scope, SCOPE_KINDS
from tools.maintenance_ledger import (
    ActiveRun, RunRecord, parse_run_comment, render_run_comment,
)

ATTESTATION_SCHEMA = "maintenance-run.v2"
ATTESTATION_SENTINEL = "<!-- devflow-maintenance-run:v2 -->"
_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_FIELDS = frozenset({
    "repository", "run_id", "slot_id", "generation", "lens", "depth",
    "fingerprint", "result", "findings_summary", "completed_at",
    "next_eligibility_reason", "evidence_refs",
})
_OUTER_FIELDS = frozenset({
    "schema_version", "run", "scope", "coverage_key", "catalog_digest",
})


class RunAttestationError(ValueError):
    """Malformed, ambiguous or mismatched completed-run evidence."""


@dataclass(frozen=True)
class AttestedRun:
    record: RunRecord
    scope: Scope
    coverage_key: str
    catalog_digest: str


def _closed(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise RunAttestationError(f"{name} must contain exactly expected fields")
    return value


def _duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise RunAttestationError(f"duplicate attestation key: {key}")
        value[key] = item
    return value


def _hash(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise RunAttestationError(f"{name} must be sha256 digest")
    return value


def _validate(value: AttestedRun) -> AttestedRun:
    if not isinstance(value, AttestedRun):
        raise RunAttestationError("attestation must be AttestedRun")
    if not isinstance(value.scope, Scope):
        raise RunAttestationError("attestation scope missing")
    if value.scope.kind not in SCOPE_KINDS or not value.scope.selector.strip():
        raise RunAttestationError("attestation scope is invalid")
    if not isinstance(value.coverage_key, str) or not value.coverage_key.strip():
        raise RunAttestationError("attestation coverage_key missing")
    _hash(value.catalog_digest, "catalog_digest")
    # Accepted v1 authoritative parser provides closed result/depth/run-id,
    # evidence-ref and completed-at validation; keep one v1 validator.
    try:
        record = parse_run_comment(render_run_comment(value.record))
    except (TypeError, ValueError) as exc:
        raise RunAttestationError("invalid underlying v1 completion record") from exc
    if record is None or record != value.record:
        raise RunAttestationError("underlying v1 record did not round-trip")
    return value


def _to_payload(value: AttestedRun) -> dict[str, object]:
    run = value.record
    return {
        "schema_version": ATTESTATION_SCHEMA,
        "run": {
            "repository": run.repository,
            "run_id": run.run_id,
            "slot_id": run.slot_id,
            "generation": run.generation,
            "lens": run.lens,
            "depth": run.depth,
            "fingerprint": run.fingerprint,
            "result": run.result,
            "findings_summary": run.findings_summary,
            "completed_at": run.completed_at,
            "next_eligibility_reason": run.next_eligibility_reason,
            "evidence_refs": list(run.evidence_refs),
        },
        "scope": {"kind": value.scope.kind, "selector": value.scope.selector},
        "coverage_key": value.coverage_key,
        "catalog_digest": value.catalog_digest,
    }


def bind_attested_run(
    active: ActiveRun,
    slot: ResolvedSlot,
    record: RunRecord,
    observed_catalog_digest: str,
) -> AttestedRun:
    """Bind a run to the *exact* already-accepted active slot/canon digest.

    This does not authenticate an external worker, assign a claim or publish
    evidence; it merely refuses mismatches at the irreversible record boundary.
    """
    digest = _hash(observed_catalog_digest, "observed_catalog_digest")
    if active.catalog_digest != digest:
        raise RunAttestationError("catalog digest changed since selection")
    if (
        active.repository != slot.repository
        or active.slot_id != slot.slot_id
        or active.coverage_key != slot.coverage_key
        or active.run_id != record.run_id
        or active.generation != record.generation
        or active.repository != record.repository
        or active.slot_id != record.slot_id
        or active.depth != record.depth
        or active.fingerprint != record.fingerprint
        or record.lens != slot.lens
        or slot.lifecycle != "ACTIVE"
    ):
        raise RunAttestationError("active run, resolved slot and completion mismatch")
    return _validate(
        AttestedRun(record=record, scope=slot.scope,
                    coverage_key=slot.coverage_key, catalog_digest=digest)
    )


def render_attested_run_comment(value: AttestedRun) -> str:
    canonical = _validate(value)
    payload = json.dumps(_to_payload(canonical), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False)
    return (
        ATTESTATION_SENTINEL + "\n\n# Maintenance Audit Run v2\n\n"
        + "```json\n" + payload + "\n```"
    )


def parse_attested_run_comment(body: str) -> AttestedRun | None:
    if not isinstance(body, str):
        raise RunAttestationError("run comment must be text")
    count = body.count(ATTESTATION_SENTINEL)
    if count == 0:
        return None
    if count != 1:
        raise RunAttestationError("ambiguous v2 run sentinel")
    pattern = re.compile(
        re.escape(ATTESTATION_SENTINEL)
        + r"\s*# Maintenance Audit Run v2\s*```json\s*(\{.*\})\s*```\s*\Z",
        re.DOTALL,
    )
    match = pattern.fullmatch(body.strip())
    if match is None:
        raise RunAttestationError("malformed v2 run comment")
    try:
        raw = json.loads(match.group(1), object_pairs_hook=_duplicate_keys)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RunAttestationError("invalid v2 JSON") from exc
    outer = _closed(raw, _OUTER_FIELDS, "v2 payload")
    if outer["schema_version"] != ATTESTATION_SCHEMA:
        raise RunAttestationError("unsupported attestation version")
    scope = _closed(outer["scope"], frozenset({"kind", "selector"}), "v2 scope")
    run = _closed(outer["run"], _RUN_FIELDS, "v2 run")
    if not isinstance(run["evidence_refs"], list):
        raise RunAttestationError("evidence_refs must be array")
    clean_run = dict(run)
    clean_run["evidence_refs"] = tuple(clean_run["evidence_refs"])
    try:
        parsed = RunRecord(**clean_run)
    except (TypeError, ValueError) as exc:
        raise RunAttestationError("invalid v2 run fields") from exc
    result = AttestedRun(
        record=parsed,
        scope=Scope(kind=scope["kind"], selector=scope["selector"]),
        coverage_key=outer["coverage_key"],
        catalog_digest=outer["catalog_digest"],
    )
    return _validate(result)
