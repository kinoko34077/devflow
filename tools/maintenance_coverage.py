"""Read-only, fail-closed SMC coverage projection from trusted legacy Ledger records.

This module does not publish maintenance supply, grant claims, or treat a v1
RunRecord as proof of a current catalog scope. A caller must independently
verify GitHub author association and retrieve comments from the owning Ledger.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from tools.github_issue_trust import is_trusted_principal
from tools.maintenance_catalog import ResolvedSlot
from tools.maintenance_ledger import RunRecord

TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
DEPTHS = frozenset({"CONTROL", "STANDARD", "DEEP"})
POSITIVE_RESULTS = frozenset({"CLEAN", "FINDINGS", "RECONCILED"})
NO_COVERAGE_RESULTS = frozenset({"BLOCKED", "SUPERSEDED", "NEEDS_REAUDIT"})
FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class LedgerEvidence:
    """Provenance envelope with the canonical GitHub principal identity."""

    record: RunRecord
    source_url: str
    author_association: str
    author_user: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CoverageRow:
    repository: str
    slot_id: str
    scope_kind: str
    scope_selector: str
    coverage_key: str
    lens: str
    depth: str
    current_fingerprint: str | None
    status: str
    reason: str
    run_id: str | None
    completed_at: str | None
    evidence_url: str | None


def _trusted(value: LedgerEvidence, repository: str) -> bool:
    prefix = "https://github.com/" + repository + "/issues/"
    if not is_trusted_principal({"user": value.author_user}):
        return False
    if not value.source_url.startswith(prefix):
        return False
    suffix = value.source_url[len(prefix):]
    return re.fullmatch(r"[1-9][0-9]*#issuecomment-[1-9][0-9]*", suffix) is not None


def _row(
    slot: ResolvedSlot,
    depth: str,
    fingerprint: str | None,
    status: str,
    reason: str,
    item: LedgerEvidence | None = None,
) -> CoverageRow:
    record = item.record if item is not None else None
    return CoverageRow(
        repository=slot.repository,
        slot_id=slot.slot_id,
        scope_kind=slot.scope.kind,
        scope_selector=slot.scope.selector,
        coverage_key=slot.coverage_key,
        lens=slot.lens,
        depth=depth,
        current_fingerprint=fingerprint,
        status=status,
        reason=reason,
        run_id=record.run_id if record is not None else None,
        completed_at=record.completed_at if record is not None else None,
        evidence_url=item.source_url if item is not None else None,
    )


def derive_coverage(
    slots: Sequence[ResolvedSlot],
    history: Sequence[LedgerEvidence],
    current_fingerprints: Mapping[str, str],
    depths: Sequence[str] = ("STANDARD", "DEEP"),
) -> tuple[CoverageRow, ...]:
    """Produce conservative per-slot-depth rows, never verified scope coverage.

    v1 completed RunRecord lacks source-scope, coverage_key and catalog digest,
    so even an exact fingerprint/slot/lens match is LEGACY_SCOPE_UNBOUND,
    not a proof of the current scope or a fresh multi-lens audit. External
    freshness must be reflected in the caller-supplied current fingerprint.
    """
    if not depths or len(set(depths)) != len(depths) or set(depths) - DEPTHS:
        raise ValueError("depths must be unique known audit depths")
    identities = [(slot.repository, slot.slot_id) for slot in slots]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate repository/slot_id in projection")

    results: list[CoverageRow] = []
    for slot in sorted(slots, key=lambda item: (item.repository, item.slot_id)):
        if slot.lifecycle != "ACTIVE":
            continue
        key = slot.repository + "::" + slot.slot_id
        fingerprint = current_fingerprints.get(key)
        has_valid_fp = (
            isinstance(fingerprint, str)
            and FINGERPRINT_PATTERN.fullmatch(fingerprint) is not None
        )
        for depth in depths:
            matching = [
                e for e in history
                if e.record.repository == slot.repository
                and e.record.slot_id == slot.slot_id
                and e.record.depth == depth
            ]
            trusted = [e for e in matching if _trusted(e, slot.repository)]
            if not matching:
                results.append(_row(slot, depth, fingerprint, "NOT_RUN", "no run evidence"))
                continue
            if not trusted:
                results.append(_row(slot, depth, fingerprint, "UNTRUSTED", "no trusted Ledger comment"))
                continue
            # Duplicate run IDs with differing record or source are ambiguous,
            # even if the most recent comment would otherwise look successful.
            by_id: dict[str, LedgerEvidence] = {}
            conflicting = False
            for item in trusted:
                previous = by_id.get(item.record.run_id)
                if previous is not None and previous != item:
                    conflicting = True
                    break
                by_id[item.record.run_id] = item
            if conflicting:
                results.append(_row(slot, depth, fingerprint, "AMBIGUOUS_HISTORY", "conflicting trusted run ID"))
                continue
            # Generation is a numeric monotone run sequence. Lexical run_id
            # order would rank ':9' after ':10' at equal timestamps and could
            # hide a later BLOCKED run behind an older CLEAN result.
            selected = max(trusted, key=lambda e: (e.record.generation, e.record.completed_at))
            rec = selected.record
            if any(
                e.record.generation < rec.generation
                and e.record.completed_at > rec.completed_at
                for e in trusted
            ):
                results.append(_row(
                    slot, depth, fingerprint, "AMBIGUOUS_HISTORY",
                    "completion timestamps contradict run generation order",
                ))
                continue
            if rec.lens != slot.lens:
                results.append(_row(slot, depth, fingerprint, "LENS_DRIFT", "current slot lens differs from recorded lens", selected))
            elif not has_valid_fp:
                results.append(_row(slot, depth, fingerprint, "UNKNOWN_FINGERPRINT", "no valid current source fingerprint", selected))
            elif rec.result in NO_COVERAGE_RESULTS:
                results.append(_row(slot, depth, fingerprint, "NO_COVERAGE", "latest run did not complete an audit", selected))
            elif rec.fingerprint != fingerprint:
                results.append(_row(slot, depth, fingerprint, "SOURCE_DRIFT", "current source fingerprint differs", selected))
            elif rec.result not in POSITIVE_RESULTS or not rec.evidence_refs:
                results.append(_row(slot, depth, fingerprint, "INSUFFICIENT_EVIDENCE", "result or evidence reference inadequate", selected))
            else:
                results.append(_row(slot, depth, fingerprint, "LEGACY_SCOPE_UNBOUND",
                    "v1 completed record omits immutable scope and catalog digest; do not claim current coverage", selected))
    return tuple(results)
