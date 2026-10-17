"""Read-only dual-v1/v2 SMC coverage view; no effectful completion publisher.

A v2 immutable scope match confirms only the stated evidence provenance
boundary, not independent execution of an audit or truth of remote data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from tools.maintenance_catalog import ResolvedSlot
from tools.maintenance_coverage import (
    CoverageRow, LedgerEvidence, derive_coverage, _trusted,
)
from tools.maintenance_run_attestation import AttestedRun

_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SUBSTANTIVE = frozenset({"CLEAN", "FINDINGS", "RECONCILED"})


@dataclass(frozen=True)
class AttestedLedgerEvidence:
    attestation: AttestedRun
    source_url: str
    author_association: str


def _trusted_attestation(item: AttestedLedgerEvidence, repo: str) -> bool:
    return _trusted(
        LedgerEvidence(item.attestation.record, item.source_url, item.author_association),
        repo,
    )


def derive_dual_version_coverage(
    slots: Sequence[ResolvedSlot],
    legacy_history: Sequence[LedgerEvidence],
    attested_history: Sequence[AttestedLedgerEvidence],
    current_fingerprints: Mapping[str, str],
    current_catalog_digests: Mapping[str, str],
    depths: Sequence[str] = ("STANDARD", "DEEP"),
) -> tuple[CoverageRow, ...]:
    """Read the latest trusted per-slot result while retaining old v1 semantics.

    All current fingerprints/catalog digests must be independently obtained by
    the caller. If they are unknown or inconsistent, fail closed rather than
    claiming completed present-day source coverage.
    """
    baseline = derive_coverage(slots, legacy_history, current_fingerprints, depths)
    known = {(slot.repository, slot.slot_id): slot for slot in slots}
    output: list[CoverageRow] = []
    for row in baseline:
        slot = known[(row.repository, row.slot_id)]
        raw_v2 = [
            item for item in attested_history
            if item.attestation.record.repository == row.repository
            and item.attestation.record.slot_id == row.slot_id
            and item.attestation.record.depth == row.depth
        ]
        if not raw_v2 or row.status == "AMBIGUOUS_HISTORY":
            # A conflicting trusted v1 history cannot be made credible by
            # adding an unrelated newer v2 comment.
            output.append(row)
            continue
        v2 = [item for item in raw_v2 if _trusted_attestation(item, row.repository)]
        if not v2:
            output.append(replace(row, status="UNTRUSTED",
                                  reason="no trusted v2 Ledger comment")
                          if row.status == "NOT_RUN" else row)
            continue
        v1 = [
            item for item in legacy_history
            if item.record.repository == row.repository
            and item.record.slot_id == row.slot_id
            and item.record.depth == row.depth
            and _trusted(item, row.repository)
        ]
        v1_ids = {item.record.run_id for item in v1}
        v2_ids = [item.attestation.record.run_id for item in v2]
        if len(v2_ids) != len(set(v2_ids)) or v1_ids.intersection(v2_ids):
            output.append(replace(row, status="AMBIGUOUS_HISTORY",
                                  reason="duplicate trusted run ID across v1/v2"))
            continue
        latest_v2 = max(
            v2, key=lambda item: (
                item.attestation.record.generation,
                item.attestation.record.completed_at,
            ),
        )
        most_recent_v1 = max(
            v1, key=lambda item: (
                item.record.generation,
                item.record.completed_at,
            ),
        ) if v1 else None
        # The numeric generation is the authoritative monotone run sequence.
        # A later wall-clock timestamp attached to an earlier generation
        # represents inconsistent evidence and cannot receive coverage credit.
        current_record = latest_v2.attestation.record
        if any(
            item.attestation.record.generation < current_record.generation
            and item.attestation.record.completed_at > current_record.completed_at
            for item in v2
        ) or (
            most_recent_v1 is not None
            and (
                (
                    most_recent_v1.record.generation < current_record.generation
                    and most_recent_v1.record.completed_at > current_record.completed_at
                )
                or (
                    most_recent_v1.record.generation > current_record.generation
                    and most_recent_v1.record.completed_at < current_record.completed_at
                )
            )
        ):
            output.append(replace(
                row, status="AMBIGUOUS_HISTORY",
                reason="completion timestamps contradict run generation order",
            ))
            continue
        if (
            most_recent_v1 is not None
            and most_recent_v1.record.generation > current_record.generation
        ):
            # A later generation in v1 cannot inherit a v2 scope attestation.
            output.append(row)
            continue
        a = latest_v2.attestation
        rec = a.record
        reason = ""
        current_fp = current_fingerprints.get(row.repository + "::" + row.slot_id)
        current_catalog = current_catalog_digests.get(row.repository)
        if rec.result not in _SUBSTANTIVE:
            status, reason = "NO_COVERAGE", "latest attested run did not complete an audit"
        elif rec.lens != slot.lens:
            status, reason = "LENS_DRIFT", "attested Lens differs from current catalog"
        elif a.scope != slot.scope or a.coverage_key != slot.coverage_key:
            status, reason = "SCOPE_DRIFT", "attested scope/key differs from current catalog"
        elif not isinstance(current_fp, str) or _SHA.fullmatch(current_fp) is None:
            status, reason = "UNKNOWN_FINGERPRINT", "source fingerprint not independently observed"
        elif not isinstance(current_catalog, str) or _SHA.fullmatch(current_catalog) is None:
            status, reason = "UNKNOWN_CATALOG", "current canonical catalog digest not observed"
        elif a.catalog_digest != current_catalog:
            status, reason = "CATALOG_DRIFT", "catalog identity differs from audited generation"
        elif rec.fingerprint != current_fp:
            status, reason = "SOURCE_DRIFT", "audited source fingerprint differs from observed current source"
        elif not rec.evidence_refs:
            status, reason = "INSUFFICIENT_EVIDENCE", "run lacks actual verification evidence refs"
        else:
            status, reason = (
                "ATTESTED_SCOPE_MATCH",
                "trusted v2 Ledger comment binds matching scope/catalog/fingerprint; independent actual audit evidence must still be examined",
            )
        output.append(replace(
            row, status=status, reason=reason, run_id=rec.run_id,
            completed_at=rec.completed_at, evidence_url=latest_v2.source_url,
        ))
    return tuple(output)
