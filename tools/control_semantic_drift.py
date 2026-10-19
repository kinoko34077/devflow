"""Fail-closed, read-only comparison of explicit Control claims to live evidence.

This is a bounded semantic *signal*, not a replacement for authoritative
Repository Control, M3 task authority, Cursor #576 or SMC #588.
No GitHub network, filesystem, mutations, scheduler, or state inference.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlsplit

DIMENSIONS = {
    "PR_GATE": frozenset({"AWAIT_REVIEW", "AWAIT_MERGE", "MERGED", "CLOSED_UNMERGED", "UNKNOWN"}),
    "PUBLIC_ENTRY": frozenset({"UNVERIFIED", "VERIFIED", "FAILED", "UNKNOWN"}),
    "FIELD_ACCEPTANCE": frozenset({"UNVERIFIED", "ACCEPTED", "REJECTED", "UNKNOWN"}),
}
CURRENT_SECTIONS = frozenset({"Next Action", "Active Work"})
STATUS = frozenset({"ALIGNED", "POTENTIAL_MISMATCH", "UNKNOWN", "NOT_COMPARABLE"})


def _timestamp(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        value = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return value if value.tzinfo is not None else None
    except ValueError:
        return None


def _url(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    parts = urlsplit(s)
    return parts.scheme == "https" and parts.hostname == "github.com" and not parts.username


def compare_claim(
    control: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> dict[str, str]:
    """Compare ONE explicitly scoped current Control statement.

    Observed evidence must already have been read by an authenticated/trusted
    GET consumer with complete source coverage. The caller must NOT derive
    `source_verified=True` from user-supplied prose or this function.
    """
    result = {"status": "UNKNOWN", "reason": "INCOMPLETE_OR_UNTRUSTED_SOURCE"}
    required = ("repository", "subject", "dimension", "value")
    if any(not isinstance(control.get(k), str) or not control[k] for k in required):
        return result
    if any(not isinstance(observed.get(k), str) or not observed[k] for k in required):
        return result
    dimension = control["dimension"]
    if dimension not in DIMENSIONS or observed["dimension"] not in DIMENSIONS:
        return result
    if (control["repository"], control["subject"], dimension) != (
        observed["repository"], observed["subject"], observed["dimension"]
    ):
        return {"status": "NOT_COMPARABLE", "reason": "DIFFERENT_SCOPE"}
    if not (
        control.get("section") in CURRENT_SECTIONS
        and control.get("is_current") is True
        and control.get("source_verified") is True
        and observed.get("source_verified") is True
        and observed.get("source_complete") is True
        and _url(control.get("source_url"))
        and _url(observed.get("source_url"))
    ):
        return result
    if _timestamp(control.get("read_at")) is None or _timestamp(observed.get("read_at")) is None:
        return result
    if observed["value"] not in DIMENSIONS[dimension] or control["value"] not in DIMENSIONS[dimension]:
        return result
    if control["value"] == "UNKNOWN" or observed["value"] == "UNKNOWN":
        return {"status": "UNKNOWN", "reason": "UNKNOWN_STAGE"}
    if control["value"] == observed["value"]:
        return {"status": "ALIGNED", "reason": "SAME_SCOPED_STAGE"}
    # This is a finding candidate, NEVER automated repair or a grant of runtime
    # authority. A reviewer must verify both semantics and source chronology.
    return {"status": "POTENTIAL_MISMATCH", "reason": "SAME_SCOPE_CONTRADICTORY_STAGE"}
