from __future__ import annotations

import hashlib
import json
from typing import Any

from tools.development_reconciler import DISPOSITIONS

REPORT_SCHEMA = "maintenance-audit-report.v1"


class AuditContractError(ValueError):
    pass


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditContractError(f"{name} must be an object")
    return dict(value)


def _required_text(value: dict[str, Any], key: str, owner: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise AuditContractError(f"{owner}.{key} must be non-empty text")
    return item


def normalize_observation(value: object) -> dict[str, object]:
    root = _mapping(value, "observation")
    repository = _required_text(root, "repository", "observation")
    control_ref = _required_text(root, "control_ref", "observation")
    observed_at = _required_text(root, "observed_at", "observation")

    if "controls" in root:
        controls = root["controls"]
        if not isinstance(controls, list) or len(controls) != 1:
            raise AuditContractError("exactly one control is required")
        control = _mapping(controls[0], "control")
    else:
        control = _mapping(root.get("control"), "control")

    owner = _mapping(root.get("owner"), "owner")
    producer = _mapping(root.get("producer"), "producer")
    gates = _mapping(root.get("gates"), "gates")

    if control.get("trusted") is not True:
        raise AuditContractError("control must be trusted")
    if _required_text(control, "repository", "control") != repository:
        raise AuditContractError("control repository identity mismatch")
    if _required_text(control, "ref", "control") != control_ref:
        raise AuditContractError("control ref identity mismatch")
    _required_text(control, "revision", "control")

    if _required_text(owner, "repository", "owner") != repository:
        raise AuditContractError("owner repository identity mismatch")
    _required_text(owner, "ref", "owner")
    _required_text(owner, "revision", "owner")

    normalized = {
        "repository": repository,
        "control_ref": control_ref,
        "observed_at": observed_at,
        "control": control,
        "owner": owner,
        "producer": producer,
        "gates": gates,
        "search": _mapping(root.get("search", {}), "search"),
    }
    return normalized


def _logical_identity(value: dict[str, object]) -> str:
    control = value["control"]
    owner = value["owner"]
    assert isinstance(control, dict)
    assert isinstance(owner, dict)
    logical = {
        "repository": value["repository"],
        "control_ref": value["control_ref"],
        "control_revision": control["revision"],
        "owner_ref": owner["ref"],
        "owner_revision": owner["revision"],
        "owner_state": owner.get("state"),
        "owner_work_status": owner.get("work_status"),
    }
    encoded = json.dumps(logical, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def classify_repository(value: object) -> dict[str, object]:
    normalized = normalize_observation(value)
    owner = normalized["owner"]
    assert isinstance(owner, dict)
    return {
        "schema_version": REPORT_SCHEMA,
        "report_id": _logical_identity(normalized),
        "repository": normalized["repository"],
        "control_ref": normalized["control_ref"],
        "observed_at": normalized["observed_at"],
        "disposition": "NO_ACTION",
        "reason_codes": [],
        "finding_classes": [],
        "owner_class": owner.get("work_status", "UNKNOWN"),
        "evidence_refs": [normalized["control_ref"], owner["ref"]],
        "recheck_trigger": "AUTHORITATIVE_EVIDENCE_CHANGE",
    }


def classify_portfolio(values: list[object]) -> list[dict[str, object]]:
    reports = [classify_repository(value) for value in values]
    return sorted(reports, key=lambda report: str(report["repository"]))
