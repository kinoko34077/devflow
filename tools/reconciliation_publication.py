from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Iterable


SCHEMA_VERSION = "development-reconciliation-work.v1"
SOURCE_CONTRACT_VERSION = "development-reconciliation.v1"

_TASK_REF = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)$")
_ENTRY_REF = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)$"
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_RECOVERY_TRANSITIONS = {
    "RECOVERY_ASSESSMENT",
    "SUCCESSOR_ELIGIBILITY_EVALUATION",
}


def _require_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_task_identity(evidence: dict[str, Any]) -> tuple[str, str, str]:
    task_ref = _require_nonempty_string(evidence.get("task_ref"), "task_ref")
    task_match = _TASK_REF.fullmatch(task_ref)
    if task_match is None:
        raise ValueError("task_ref must be owner/repository#N")

    digest = _require_nonempty_string(
        evidence.get("task_body_sha256"), "task_body_sha256"
    )
    if _DIGEST.fullmatch(digest) is None:
        raise ValueError("task_body_sha256 must be sha256:<64 lowercase hex>")

    entry_ref = _require_nonempty_string(evidence.get("entry_ref"), "entry_ref")
    entry_match = _ENTRY_REF.fullmatch(entry_ref)
    if entry_match is None:
        raise ValueError("entry_ref must be a canonical GitHub Issue URL")
    entry_task_ref = f"{entry_match.group(1)}/{entry_match.group(2)}#{entry_match.group(3)}"
    if entry_task_ref != task_ref:
        raise ValueError("entry_ref must identify the exact owning task")

    return task_ref, digest, entry_ref


def _require_source_contract(evidence: dict[str, Any]) -> str:
    version = _require_nonempty_string(
        evidence.get("contract_version"), "contract_version"
    )
    if version != SOURCE_CONTRACT_VERSION:
        raise ValueError("unsupported reconciliation contract version")
    if evidence.get("evidence_complete") is not True:
        raise ValueError("publication requires complete reconciler evidence")
    observed_at = _require_nonempty_string(evidence.get("observed_at"), "observed_at")
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be an RFC-3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include an RFC-3339 timezone offset")
    return observed_at


def _reason_codes(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("reason_codes must be a non-empty array")
    normalized: list[str] = []
    for item in value:
        code = _require_nonempty_string(item, "reason_codes item")
        if code not in normalized:
            normalized.append(code)
    return sorted(normalized)


def _publication_id(identity: dict[str, Any]) -> str:
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _reviewer_context(evidence: dict[str, Any]) -> dict[str, Any]:
    if evidence.get("different_reviewer_required") is not True:
        raise ValueError("reviewer publication requires an explicit different-reviewer gate")
    pr_number = evidence.get("pr_number")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
        raise ValueError("reviewer publication requires a positive pr_number")
    head = _require_nonempty_string(evidence.get("pr_head_sha"), "pr_head_sha")
    if _SHA.fullmatch(head) is None:
        raise ValueError("pr_head_sha must be a full commit SHA")
    return {"pr_number": pr_number, "pr_head_sha": head.lower()}


def _recovery_context(evidence: dict[str, Any]) -> dict[str, Any]:
    predecessor = _require_nonempty_string(
        evidence.get("predecessor_session_id"), "predecessor_session_id"
    )
    checkpoint = _require_nonempty_string(evidence.get("checkpoint"), "checkpoint")
    next_action = _require_nonempty_string(evidence.get("next_action"), "next_action")
    transition = _require_nonempty_string(
        evidence.get("recovery_transition"), "recovery_transition"
    )
    if transition not in _RECOVERY_TRANSITIONS:
        raise ValueError("unsupported recovery transition")

    raw_refs = evidence.get("artifact_refs")
    if not isinstance(raw_refs, list):
        raise ValueError("artifact_refs must be an array")
    refs: list[str] = []
    for item in raw_refs:
        ref = _require_nonempty_string(item, "artifact_refs item")
        if ref not in refs:
            refs.append(ref)

    return {
        "predecessor_session_id": predecessor,
        "checkpoint": checkpoint,
        "next_action": next_action,
        "recovery_transition": transition,
        "artifact_refs": sorted(refs),
    }


def build_publication(evidence: dict[str, Any]) -> dict[str, Any] | None:
    """Derive one role-demand publication from accepted reconciliation evidence.

    A publication is demand only. It is not a runtime assignment, claim, lease,
    worker identity, or durable completion record.
    """

    if not isinstance(evidence, dict):
        raise TypeError("evidence must be an object")

    disposition = str(evidence.get("disposition") or "")
    if disposition not in {"NEEDS_REVIEWER", "NEEDS_RECOVERY"}:
        return None

    human_gate = evidence.get("human_gate")
    if not isinstance(human_gate, bool):
        raise ValueError("human_gate must be a boolean")
    if human_gate:
        return None

    observed_at = _require_source_contract(evidence)
    task_ref, task_digest, entry_ref = _require_task_identity(evidence)
    reasons = _reason_codes(evidence.get("reason_codes"))
    scope = _require_nonempty_string(evidence.get("scope"), "scope")

    if disposition == "NEEDS_REVIEWER":
        role = "reviewer"
        context = _reviewer_context(evidence)
    else:
        role = "recovery"
        context = _recovery_context(evidence)

    logical_identity = {
        "schema_version": SCHEMA_VERSION,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "task_ref": task_ref,
        "task_body_sha256": task_digest,
        "entry_ref": entry_ref,
        "role": role,
        "disposition": disposition,
        "reason_codes": reasons,
        "scope": scope,
        "context": context,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "publication_id": _publication_id(logical_identity),
        "task_ref": task_ref,
        "task_body_sha256": task_digest,
        "entry_ref": entry_ref,
        "role": role,
        "disposition": disposition,
        "reason_codes": reasons,
        "scope": scope,
        "requires_user_confirmation": False,
        "observed_at": observed_at,
        "freshness": {
            "source_contract_version": SOURCE_CONTRACT_VERSION,
            "task_body_sha256": task_digest,
        },
        "context": context,
    }


def reconcile_publications(
    existing: Iterable[dict[str, Any]],
    *,
    task_ref: str,
    role: str,
    desired: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return active publications plus superseded logical IDs for one task/role.

    This is a pure projection operation. Persistence remains the responsibility
    of the canonical publication surface selected by devflow policy.
    """

    _require_nonempty_string(task_ref, "task_ref")
    if _TASK_REF.fullmatch(task_ref) is None:
        raise ValueError("task_ref must be owner/repository#N")
    if role not in {"reviewer", "recovery"}:
        raise ValueError("unsupported publication role")
    if desired is not None:
        if desired.get("task_ref") != task_ref or desired.get("role") != role:
            raise ValueError("desired publication does not match task_ref/role")
        _require_nonempty_string(desired.get("publication_id"), "publication_id")

    active: list[dict[str, Any]] = []
    superseded: list[str] = []
    desired_id = desired.get("publication_id") if desired is not None else None
    desired_seen = False

    for publication in existing:
        if not isinstance(publication, dict):
            raise ValueError("existing publication must be an object")
        publication_id = _require_nonempty_string(
            publication.get("publication_id"), "publication_id"
        )
        if publication.get("task_ref") != task_ref or publication.get("role") != role:
            active.append(publication)
            continue
        if desired_id is not None and publication_id == desired_id:
            if not desired_seen:
                active.append(publication)
                desired_seen = True
            continue
        if publication_id not in superseded:
            superseded.append(publication_id)

    if desired is not None and not desired_seen:
        active.append(desired)

    return {"active": active, "superseded_ids": superseded}
