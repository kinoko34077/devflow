"""Read-only, source-bound acceptance preflight for the existing reconciler (#761).

An authenticated collector supplies facts. This module never authenticates a
GitHub actor, extracts acceptance from prose, or grants mutation authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Mapping

_REF = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+#[1-9][0-9]*\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ACCEPTED = frozenset({"SATISFIED", "UNSATISFIED", "UNKNOWN"})


def acceptance_preflight(
    evidence: Mapping[str, Any], *, task_ref: str, observed_issue_body_sha256: str, now: datetime
) -> dict[str, Any]:
    """Return bounded evidence disposition; never infer user acceptance.

    The calling collector must validate GitHub GET identity, author/provenance,
    complete applicable current Issue body, and evidence links separately.
    A historical PR note alone cannot attest current Issue acceptance.
    """
    missing = {"status": "NEEDS_EVIDENCE", "reason": "ACCEPTANCE_PROVENANCE_UNVERIFIED",
               "acceptance_satisfied": False, "evidence_complete": False}
    if (not isinstance(evidence, Mapping) or not isinstance(task_ref, str)
            or not _REF.fullmatch(task_ref)
            or not isinstance(observed_issue_body_sha256, str)
            or not _SHA.fullmatch(observed_issue_body_sha256)
            or not isinstance(now, datetime) or now.tzinfo is None):
        return missing
    fields = {
        "task_ref", "issue_body_sha256", "issue_read_at", "acceptance_scope",
        "status", "source_verified", "source_complete", "decision_authorized",
        "evidence_refs", "excluded_scopes",
    }
    if set(evidence) != fields or evidence.get("task_ref") != task_ref:
        return missing
    if evidence.get("issue_body_sha256") != observed_issue_body_sha256:
        return {**missing, "reason": "STALE_OWNING_ISSUE_REVISION"}
    try:
        when = datetime.fromisoformat(evidence["issue_read_at"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return missing
    if when.tzinfo is None or not (timedelta(0) <= now - when <= timedelta(minutes=15)):
        return missing
    if (evidence.get("source_verified") is not True
            or evidence.get("source_complete") is not True
            or evidence.get("decision_authorized") is not True
            or evidence.get("status") not in _ACCEPTED
            or not isinstance(evidence.get("acceptance_scope"), str)
            or not evidence["acceptance_scope"].strip()
            or not isinstance(evidence.get("evidence_refs"), list)
            or not evidence["evidence_refs"]
            or len(evidence["evidence_refs"]) > 8
            or not all(isinstance(v, str) and _COMMENT.fullmatch(v)
                       for v in evidence["evidence_refs"])
            or len(evidence["evidence_refs"]) != len(set(evidence["evidence_refs"]))
            or not isinstance(evidence.get("excluded_scopes"), list)
            or len(evidence["excluded_scopes"]) > 16
            or not all(isinstance(v, str) and v.strip() for v in evidence["excluded_scopes"])):
        return missing
    if evidence["status"] == "UNKNOWN":
        return {**missing, "reason": "ACCEPTANCE_NOT_ESTABLISHED"}
    return {
        "status": "VERIFIED_SCOPE_DECISION",
        "reason": "SOURCE_BOUND_SCOPE_ONLY",
        "scope_acceptance_satisfied": evidence["status"] == "SATISFIED",
        "acceptance_satisfied": False,
        "evidence_complete": True,
        "acceptance_scope": evidence["acceptance_scope"],
        "excluded_scopes": tuple(evidence["excluded_scopes"]),
    }
