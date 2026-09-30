from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


ALLOWLISTED_KIND = "WITHDRAW_STALE_CONTROL_CANDIDATE"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GATES = (
    "producer_active",
    "human_gate",
    "reviewer_gate",
    "external_wait",
    "security_gate",
)


class SyncCheckContractError(ValueError):
    pass


@dataclass(frozen=True)
class SyncCheckPlan:
    kind: str
    repository: str
    control_ref: str
    owner_ref: str
    expected_control_body_sha256: str
    expected_owner_body_sha256: str
    candidate_task_ref: str
    report_id: str


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SyncCheckContractError(f"{name} must be an object")
    return value


def _string(
    value: object,
    field: str,
    *,
    allow_none: bool = False,
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        raise SyncCheckContractError(f"{field} must be a non-empty string")
    return value


def _sha256(value: object, field: str) -> str:
    text = _string(value, field)
    assert isinstance(text, str)
    if _SHA256.fullmatch(text) is None:
        raise SyncCheckContractError(
            f"{field} must be a canonical sha256 identity"
        )
    return text


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise SyncCheckContractError(f"{field} must be boolean")
    return value


def _gate_active(*sources: Mapping[str, Any]) -> bool:
    for source in sources:
        for field in _GATES:
            if field in source and _bool(source[field], field):
                return True
    return False


def _candidate_tasks(control: Mapping[str, Any]) -> tuple[str, ...]:
    value = control.get("candidate_tasks")
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item
        for item in value
    ):
        raise SyncCheckContractError(
            "control candidate_tasks must be an array of task refs"
        )
    if len(set(value)) != len(value):
        raise SyncCheckContractError(
            "control candidate_tasks contains duplicate task refs"
        )
    return tuple(value)


def build_sync_check_plan(
    report: dict[str, object],
    control_snapshot: dict[str, object],
    owner_snapshot: dict[str, object],
) -> SyncCheckPlan | None:
    report_map = _mapping(report, "report")
    control = _mapping(control_snapshot, "control_snapshot")
    owner = _mapping(owner_snapshot, "owner_snapshot")

    repository = _string(report_map.get("repository"), "report.repository")
    control_ref = _string(
        report_map.get("control_ref"),
        "report.control_ref",
    )
    owner_ref = _string(
        report_map.get("owner_ref"),
        "report.owner_ref",
        allow_none=True,
    )
    report_id = _sha256(
        report_map.get("report_id"),
        "report.report_id",
    )

    control_repository = _string(
        control.get("repository"),
        "control_snapshot.repository",
    )
    control_snapshot_ref = _string(
        control.get("control_ref"),
        "control_snapshot.control_ref",
    )
    owner_repository = _string(
        owner.get("repository"),
        "owner_snapshot.repository",
    )
    owner_snapshot_ref = _string(
        owner.get("owner_ref"),
        "owner_snapshot.owner_ref",
    )

    if (
        repository != control_repository
        or repository != owner_repository
        or control_ref != control_snapshot_ref
    ):
        raise SyncCheckContractError(
            "repository or Control identity mismatch"
        )
    if owner_ref is not None and owner_ref != owner_snapshot_ref:
        raise SyncCheckContractError("owner identity mismatch")

    control_body_sha256 = _sha256(
        control.get("body_sha256"),
        "control_snapshot.body_sha256",
    )
    owner_body_sha256 = _sha256(
        owner.get("body_sha256"),
        "owner_snapshot.body_sha256",
    )
    candidates = _candidate_tasks(control)

    disposition = _string(
        report_map.get("disposition"),
        "report.disposition",
    )
    transition = _string(
        report_map.get("next_transition"),
        "report.next_transition",
        allow_none=True,
    )
    findings = report_map.get("finding_classes")
    if not isinstance(findings, list) or not all(
        isinstance(item, str) for item in findings
    ):
        raise SyncCheckContractError(
            "report.finding_classes must be an array of strings"
        )

    if (
        disposition != "AUTO_ADVANCE"
        or transition != ALLOWLISTED_KIND
        or owner_ref is None
        or owner_ref != owner_snapshot_ref
        or "CONTROL_ACTIVE_WORK_TERMINAL" not in findings
    ):
        return None

    if (
        _bool(owner.get("terminal"), "owner_snapshot.terminal") is not True
        or _bool(owner.get("runnable"), "owner_snapshot.runnable") is not False
        or str(owner.get("state") or "").upper() != "CLOSED"
    ):
        return None

    if _gate_active(report_map, control, owner):
        return None

    if owner_ref not in candidates:
        return None

    return SyncCheckPlan(
        kind=ALLOWLISTED_KIND,
        repository=repository,
        control_ref=control_ref,
        owner_ref=owner_ref,
        expected_control_body_sha256=control_body_sha256,
        expected_owner_body_sha256=owner_body_sha256,
        candidate_task_ref=owner_ref,
        report_id=report_id,
    )
