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
_COMMENT = re.compile(r"https://github\.com/kinoko34077/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*#issuecomment-[1-9][0-9]*\Z")
_ACCEPTED = frozenset({"SATISFIED", "UNSATISFIED", "UNKNOWN"})
_OBSERVATION_RESULTS = frozenset({"SUCCESS", "FAILURE", "VALID_NEGATIVE", "UNKNOWN", "NOT_RUN"})
_SURFACE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


def outcome_observation_preflight(
    evidence: Mapping[str, Any] | None, *, task_ref: str,
    observed_issue_body_sha256: str,
) -> dict[str, Any]:
    """Compare caller-declared required and observed outcome identities.

    This is deliberately weaker than an evidence collector: it does not read or
    authenticate the referenced comments, prove that the declared requirement
    appears in the Issue, or establish that an end user saw the result.  The
    owning Issue revision is bound to prevent stale packets from being reused.
    Every disposition is advisory and can never satisfy task acceptance.
    """
    observed_result_value = evidence.get("observed_result") if isinstance(evidence, Mapping) else None
    observed_result = (
        observed_result_value
        if isinstance(observed_result_value, str) and observed_result_value in _OBSERVATION_RESULTS
        else None
    )

    def outcome(status: str, reason: str, *, complete: bool = False, **fields: Any) -> dict[str, Any]:
        return {
            "status": status,
            "reason": reason,
            "observed_result": observed_result,
            "packet_complete": complete,
            "source_verification": "NOT_PERFORMED",
            "acceptance_satisfied": False,
            "can_authorize_execution": False,
            "authority": "ADVISORY_ONLY",
            **fields,
        }

    def needs_evidence(reason: str = "OBSERVATION_PACKET_INVALID") -> dict[str, Any]:
        return outcome("NEEDS_EVIDENCE", reason)

    if not isinstance(evidence, Mapping):
        return needs_evidence()
    fields = {
        "task_ref", "issue_body_sha256", "required_surface", "required_target",
        "observed_surface", "observed_target", "observed_result", "evidence_refs",
    }
    if set(evidence) != fields or evidence.get("task_ref") != task_ref:
        return needs_evidence(
            "TASK_REF_MISMATCH" if evidence.get("task_ref") != task_ref else "OBSERVATION_PACKET_INVALID"
        )
    if (not isinstance(task_ref, str) or not _REF.fullmatch(task_ref)
            or not isinstance(observed_issue_body_sha256, str)
            or not _SHA.fullmatch(observed_issue_body_sha256)
            or not isinstance(evidence.get("issue_body_sha256"), str)
            or not _SHA.fullmatch(evidence["issue_body_sha256"])):
        return needs_evidence()
    if evidence["issue_body_sha256"] != observed_issue_body_sha256:
        return needs_evidence("STALE_OWNING_ISSUE_REVISION")
    if not isinstance(observed_result_value, str) or observed_result_value not in _OBSERVATION_RESULTS:
        return needs_evidence()

    required_surface = evidence.get("required_surface")
    observed_surface = evidence.get("observed_surface")
    required_target = evidence.get("required_target")
    observed_target = evidence.get("observed_target")
    if (not isinstance(required_surface, str) or not _SURFACE.fullmatch(required_surface)
            or not isinstance(required_target, str) or not required_target.strip()
            or len(required_target) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in required_target)):
        return needs_evidence("REQUIRED_OBSERVATION_INVALID")

    common = {
        "required_surface": required_surface,
        "required_target": required_target,
        "observed_surface": observed_surface if isinstance(observed_surface, str) else None,
        "observed_target": observed_target if isinstance(observed_target, str) else None,
    }
    if evidence["observed_result"] == "UNKNOWN":
        return outcome("UNKNOWN", "OBSERVATION_UNKNOWN", **common)
    if evidence["observed_result"] == "NOT_RUN":
        return outcome("NOT_RUN", "OBSERVATION_NOT_RUN", **common)
    if evidence["observed_surface"] is None:
        return outcome("UNKNOWN", "OBSERVED_SURFACE_UNKNOWN", **common)
    if not isinstance(observed_surface, str) or not _SURFACE.fullmatch(observed_surface):
        return needs_evidence("OBSERVED_SURFACE_INVALID")
    if observed_target is None:
        return outcome("UNKNOWN", "TARGET_IDENTITY_UNKNOWN", **common)
    if (not isinstance(observed_target, str) or not observed_target.strip()
            or len(observed_target) > 256
            or any(ord(c) < 33 or ord(c) > 126 for c in observed_target)):
        return needs_evidence("OBSERVED_TARGET_INVALID")

    evidence_refs = evidence.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        return needs_evidence("EVIDENCE_REFERENCE_MISSING")
    if (len(evidence_refs) > 8
            or not all(isinstance(ref, str) and _COMMENT.fullmatch(ref) for ref in evidence_refs)
            or len(evidence_refs) != len(set(evidence_refs))):
        return needs_evidence("EVIDENCE_REFERENCE_INVALID")
    if observed_surface != required_surface:
        return outcome("DECLARED_MISMATCH", "SURFACE_MISMATCH", complete=True, **common)
    if observed_target != required_target:
        return outcome("DECLARED_MISMATCH", "TARGET_MISMATCH", complete=True, **common)
    return outcome("DECLARED_ALIGNED", "DECLARED_IDENTITIES_MATCH", complete=True, **common)


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
