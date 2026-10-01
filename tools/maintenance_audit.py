from __future__ import annotations

import hashlib
import json
from typing import Any

from tools.development_reconciler import DISPOSITIONS


REPORT_SCHEMA = "maintenance-audit-report.v1"


class AuditContractError(ValueError):
    pass


_REQUIRED_TOP = {
    "repository", "observed_at", "control_count", "control", "owner",
    "source_status", "producer_active", "reviewer_gate", "human_gate",
    "external_wait", "semantic_projection_suspected", "evidence_refs",
}
_REQUIRED_CONTROL = {"ref", "repository", "trusted", "revision", "active_owner_ref", "candidate_present"}
_REQUIRED_OWNER = {"ref", "repository", "revision", "state", "runnable", "terminal"}


def _require_dict(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditContractError(f"{name} must be an object")
    return dict(value)


def normalize_observation(value: object) -> dict[str, object]:
    data = _require_dict(value, "observation")
    repository = data.get("repository")
    if not isinstance(repository, str) or "/" not in repository:
        raise AuditContractError("repository identity is invalid")
    source_status = data.get("source_status")
    if not isinstance(source_status, str) or not source_status:
        raise AuditContractError("source_status is required")
    if not isinstance(data.get("observed_at"), str):
        raise AuditContractError("observed_at is required")
    if not isinstance(data.get("evidence_refs"), list) or not all(
        isinstance(item, str) for item in data["evidence_refs"]
    ):
        raise AuditContractError("evidence_refs must be a list of strings")

    # A required-source failure is itself valid audit evidence. Normalize the
    # incomplete transport/discovery envelope into an explicit unavailable
    # projection so classification can preserve NEEDS_EVIDENCE in the
    # portfolio instead of aborting or silently reporting clean.
    if source_status != "OK":
        control_ref = data.get("control_ref")
        if not isinstance(control_ref, str) or not control_ref:
            control_ref = "UNAVAILABLE"
        unavailable_owner = f"{repository}#UNAVAILABLE"
        data.setdefault("control_count", 0)
        data.setdefault(
            "control",
            {
                "ref": control_ref,
                "repository": repository,
                "trusted": False,
                "revision": "0" * 40,
                "active_owner_ref": unavailable_owner,
                "candidate_present": False,
            },
        )
        data.setdefault(
            "owner",
            {
                "ref": unavailable_owner,
                "repository": repository,
                "revision": "0" * 40,
                "state": "UNKNOWN",
                "runnable": False,
                "terminal": False,
            },
        )
        for field in (
            "producer_active",
            "reviewer_gate",
            "human_gate",
            "external_wait",
            "semantic_projection_suspected",
        ):
            data.setdefault(field, False)
        data.setdefault("search_state", None)
        return data

    missing = sorted(_REQUIRED_TOP - data.keys())
    if missing:
        raise AuditContractError(f"missing required source fields: {', '.join(missing)}")
    if data["control_count"] != 1:
        raise AuditContractError("exactly one trusted Repository Control is required")

    control = _require_dict(data["control"], "control")
    owner = _require_dict(data["owner"], "owner")
    if _REQUIRED_CONTROL - control.keys():
        raise AuditContractError("control evidence is incomplete")
    if _REQUIRED_OWNER - owner.keys():
        raise AuditContractError("owner evidence is incomplete")
    if control["trusted"] is not True:
        raise AuditContractError("Repository Control is untrusted")
    if control["repository"] != repository or owner["repository"] != repository:
        raise AuditContractError("repository identity mismatch")
    if control["active_owner_ref"] != owner["ref"]:
        raise AuditContractError("owner identity mismatch")
    for name, revision in (("control", control["revision"]), ("owner", owner["revision"])):
        if not isinstance(revision, str) or len(revision) != 40:
            raise AuditContractError(f"{name} revision must be an exact 40-character identity")
    if not isinstance(data["evidence_refs"], list) or not all(
        isinstance(item, str) for item in data["evidence_refs"]
    ):
        raise AuditContractError("evidence_refs must be a list of strings")

    data["control"] = control
    data["owner"] = owner
    return data


def _classification(data: dict[str, object]) -> tuple[str, list[str], list[str], str, str | None, str]:
    owner = data["owner"]
    control = data["control"]
    assert isinstance(owner, dict)
    assert isinstance(control, dict)
    reasons: list[str] = []
    findings: list[str] = []
    transition: str | None = None

    if data["source_status"] != "OK":
        return ("NEEDS_EVIDENCE", ["REQUIRED_SOURCE_UNAVAILABLE"], ["SOURCE_UNAVAILABLE_OR_AMBIGUOUS"],
                "UNKNOWN", None, "SOURCE_RECOVERED")
    if data["human_gate"]:
        return ("NEEDS_HUMAN", ["HUMAN_GATE"], ["HUMAN_GATE_YIELD"],
                "GATED", None, "GATE_CHANGED")
    if data["reviewer_gate"]:
        return ("NEEDS_REVIEWER", ["DIFFERENT_REVIEWER_REQUIRED"], ["REVIEW_GATE_YIELD"],
                "GATED", None, "REVIEW_CHANGED")
    if data["external_wait"]:
        return ("WAIT_EXTERNAL", ["EXTERNAL_DEPENDENCY"], ["EXTERNAL_WAIT_YIELD"],
                "GATED", None, "EXTERNAL_STATE_CHANGED")
    if data["producer_active"]:
        return ("NO_ACTION", ["TRUSTED_PRODUCER_ACTIVE"], ["ACTIVE_PRODUCER_YIELD"],
                "ACTIVE_PRODUCER", None, "PRODUCER_EXITED")
    if data["semantic_projection_suspected"]:
        return ("NEEDS_EVIDENCE", ["DESIRED_TEXT_NOT_MACHINE_PROVABLE"], ["SEMANTIC_PROJECTION_SUSPECTED"],
                "TRIAGE_ONLY", None, "AUTHORITATIVE_EVIDENCE_CHANGED")
    if owner["terminal"] is True and control["active_owner_ref"] == owner["ref"]:
        reasons.append("EXACT_OWNER_TERMINAL")
        if data.get("search_state") not in (None, owner["state"]):
            reasons.append("SEARCH_STATE_STALE")
        if control.get("candidate_present") is not True:
            reasons.append("DESIRED_TEXT_NOT_MACHINE_PROVABLE")
            findings.append("SEMANTIC_PROJECTION_SUSPECTED")
            return ("NEEDS_EVIDENCE", reasons, findings, "TRIAGE_ONLY", None,
                    "AUTHORITATIVE_EVIDENCE_CHANGED")
        findings.append("CONTROL_ACTIVE_WORK_TERMINAL")
        transition = "WITHDRAW_STALE_CONTROL_CANDIDATE"
        return ("AUTO_ADVANCE", reasons, findings, "TERMINAL", transition,
                "CONTROL_OR_OWNER_CHANGED")

    if data.get("search_state") not in (None, owner["state"]):
        reasons.append("SEARCH_STATE_STALE")
    return ("NO_ACTION", reasons or ["AUTHORITATIVE_SOURCES_CONSISTENT"], findings,
            "RUNNABLE" if owner["runnable"] else "INACTIVE", None,
            "AUTHORITATIVE_EVIDENCE_CHANGED")


def _logical_identity(data: dict[str, object], findings: list[str], transition: str | None) -> str:
    control = data["control"]
    owner = data["owner"]
    assert isinstance(control, dict) and isinstance(owner, dict)
    payload = {
        "repository": data["repository"],
        "control_ref": control["ref"],
        "control_revision": control["revision"],
        "owner_ref": owner["ref"],
        "owner_revision": owner["revision"],
        "owner_state": owner["state"],
        "owner_runnable": owner["runnable"],
        "owner_terminal": owner["terminal"],
        "source_status": data["source_status"],
        "producer_active": data["producer_active"],
        "reviewer_gate": data["reviewer_gate"],
        "human_gate": data["human_gate"],
        "external_wait": data["external_wait"],
        "semantic_projection_suspected": data["semantic_projection_suspected"],
        "search_state": data.get("search_state"),
        "finding_classes": findings,
        "next_transition": transition,
        "evidence_refs": data["evidence_refs"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_repository(value: object) -> dict[str, object]:
    data = normalize_observation(value)
    disposition, reasons, findings, owner_class, transition, trigger = _classification(data)
    control = data["control"]
    owner = data["owner"]
    assert isinstance(control, dict)
    assert isinstance(owner, dict)
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "report_id": _logical_identity(data, findings, transition),
        "repository": data["repository"],
        "control_ref": control["ref"],
        "observed_at": data["observed_at"],
        "disposition": disposition,
        "reason_codes": reasons,
        "finding_classes": findings,
        "owner_class": owner_class,
        "owner_ref": owner["ref"],
        "evidence_refs": list(data["evidence_refs"]),
        "recheck_trigger": trigger,
    }
    if transition is not None:
        report["next_transition"] = transition
    return report


def classify_portfolio(values: list[object]) -> list[dict[str, object]]:
    reports = [classify_repository(value) for value in values]
    return sorted(reports, key=lambda report: str(report["repository"]))
