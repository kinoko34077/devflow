from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


ALLOWLISTED_KIND = "WITHDRAW_STALE_CONTROL_CANDIDATE"
START_MARKER = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->"
END_MARKER = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->"
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


@dataclass(frozen=True)
class SyncCheckResult:
    applied: bool
    already_applied: bool
    disposition: str
    detail: str | None = None


def canonical_body_sha256(body: str | None) -> str:
    text = "" if body is None else body
    if not isinstance(text, str):
        raise SyncCheckContractError("body must be a string or null")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _marker_payload(body: str) -> tuple[str, str, str]:
    if not isinstance(body, str):
        raise SyncCheckContractError("Control body must be a string")
    if body.count(START_MARKER) != 1 or body.count(END_MARKER) != 1:
        raise SyncCheckContractError(
            "Control body must contain exactly one candidate projection block"
        )
    start = body.index(START_MARKER) + len(START_MARKER)
    end = body.index(END_MARKER)
    if end <= start:
        raise SyncCheckContractError("candidate projection markers are out of order")
    return body[:start], body[start:end], body[end:]


def _projection_object(payload: str, repository: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.strip())
    except (TypeError, json.JSONDecodeError) as exc:
        raise SyncCheckContractError(
            "candidate projection must contain one valid JSON object"
        ) from exc
    if not isinstance(value, dict):
        raise SyncCheckContractError("candidate projection must be an object")
    if value.get("schema_version") != 1:
        raise SyncCheckContractError("unsupported candidate projection schema")
    if value.get("repository") != repository:
        raise SyncCheckContractError("candidate projection repository mismatch")
    if not isinstance(value.get("source_ref"), str) or not value["source_ref"]:
        raise SyncCheckContractError("candidate projection source_ref is missing")
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        raise SyncCheckContractError("candidate projection candidates must be an array")
    tasks: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise SyncCheckContractError("candidate projection entry must be an object")
        task = candidate.get("task")
        if not isinstance(task, str) or not task:
            raise SyncCheckContractError("candidate projection task is malformed")
        tasks.append(task)
    if len(set(tasks)) != len(tasks):
        raise SyncCheckContractError("candidate projection has duplicate task refs")
    return value


def _array_element_spans(payload: str, array_start: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = array_start + 1
    length = len(payload)
    while index < length:
        while index < length and payload[index].isspace():
            index += 1
        if index < length and payload[index] == "]":
            return spans
        start = index
        depth = 0
        in_string = False
        escaped = False
        while index < length:
            char = payload[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char in "{[":
                    depth += 1
                elif char in "}]":
                    if depth == 0:
                        if char == "]":
                            spans.append((start, index))
                            return spans
                        raise SyncCheckContractError(
                            "malformed candidate projection array"
                        )
                    depth -= 1
                elif char == "," and depth == 0:
                    spans.append((start, index))
                    index += 1
                    break
            index += 1
        else:
            raise SyncCheckContractError("unterminated candidate projection array")
    raise SyncCheckContractError("unterminated candidate projection array")


def _candidate_array_start(payload: str) -> int:
    match = re.search(r'"candidates"\s*:\s*\[', payload)
    if match is None:
        raise SyncCheckContractError("candidate projection candidates array missing")
    return payload.find("[", match.start())


def withdraw_candidate_projection(
    body: str,
    *,
    repository: str,
    task_ref: str,
) -> str:
    prefix, payload, suffix = _marker_payload(body)
    projection = _projection_object(payload, repository)
    candidates = projection["candidates"]
    matches = [
        index
        for index, candidate in enumerate(candidates)
        if candidate.get("task") == task_ref
    ]
    if len(matches) > 1:
        raise SyncCheckContractError("target candidate is duplicated")
    if not matches:
        return body

    array_start = _candidate_array_start(payload)
    spans = _array_element_spans(payload, array_start)
    if len(spans) != len(candidates):
        raise SyncCheckContractError(
            "candidate projection text does not match parsed candidate count"
        )
    target_index = matches[0]
    start, end = spans[target_index]

    if len(spans) == 1:
        edited_payload = payload[:start] + payload[end:]
    elif target_index < len(spans) - 1:
        next_start = spans[target_index + 1][0]
        edited_payload = payload[:start] + payload[next_start:]
    else:
        previous_end = spans[target_index - 1][1]
        comma = payload.find(",", previous_end, start)
        if comma < 0:
            raise SyncCheckContractError("candidate separator is missing")
        edited_payload = payload[:comma] + payload[end:]

    edited = prefix + edited_payload + suffix
    _projection_object(_marker_payload(edited)[1], repository)
    return edited


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


def _result(
    disposition: str,
    *,
    applied: bool = False,
    already_applied: bool = False,
    detail: str | None = None,
) -> SyncCheckResult:
    return SyncCheckResult(
        applied=applied,
        already_applied=already_applied,
        disposition=disposition,
        detail=detail,
    )


def _live_gate_disposition(
    control: Mapping[str, Any],
    owner: Mapping[str, Any],
) -> str | None:
    if bool(control.get("human_gate")) or bool(owner.get("human_gate")):
        return "NEEDS_HUMAN"
    if bool(control.get("security_gate")) or bool(owner.get("security_gate")):
        return "NEEDS_HUMAN"
    if bool(control.get("reviewer_gate")) or bool(owner.get("reviewer_gate")):
        return "NEEDS_REVIEWER"
    if bool(control.get("external_wait")) or bool(owner.get("external_wait")):
        return "WAIT_EXTERNAL"
    if bool(control.get("producer_active")) or bool(owner.get("producer_active")):
        return "NO_ACTION"
    return None


def execute_sync_check(plan: SyncCheckPlan, transport: Any) -> SyncCheckResult:
    if not isinstance(plan, SyncCheckPlan):
        raise SyncCheckContractError("plan must be a SyncCheckPlan")
    if plan.kind != ALLOWLISTED_KIND:
        raise SyncCheckContractError("sync-check kind is not allowlisted")

    control = _mapping(
        transport.get_control(plan.repository, plan.control_ref),
        "live control",
    )
    owner = _mapping(
        transport.get_owner(plan.repository, plan.owner_ref),
        "live owner",
    )

    if (
        control.get("repository") != plan.repository
        or control.get("control_ref") != plan.control_ref
        or owner.get("repository") != plan.repository
        or owner.get("owner_ref") != plan.owner_ref
    ):
        return _result("NEEDS_EVIDENCE", detail="live identity changed")

    live_candidates = _candidate_tasks(control)
    if plan.candidate_task_ref not in live_candidates:
        return _result(
            "NO_ACTION",
            already_applied=True,
            detail="candidate already absent",
        )

    if (
        control.get("body_sha256") != plan.expected_control_body_sha256
        or owner.get("body_sha256") != plan.expected_owner_body_sha256
    ):
        return _result("NEEDS_EVIDENCE", detail="freshness identity changed")

    gate_disposition = _live_gate_disposition(control, owner)
    if gate_disposition is not None:
        return _result(gate_disposition, detail="stronger live gate appeared")

    if (
        owner.get("terminal") is not True
        or owner.get("runnable") is not False
        or str(owner.get("state") or "").upper() != "CLOSED"
    ):
        return _result("NEEDS_EVIDENCE", detail="owner terminal state changed")

    body = control.get("body")
    if not isinstance(body, str):
        return _result("NEEDS_EVIDENCE", detail="Control body unavailable")

    try:
        edited = withdraw_candidate_projection(
            body,
            repository=plan.repository,
            task_ref=plan.candidate_task_ref,
        )
    except SyncCheckContractError as exc:
        return _result("NEEDS_EVIDENCE", detail=str(exc))

    if edited == body:
        return _result(
            "NO_ACTION",
            already_applied=True,
            detail="candidate already absent from projection",
        )

    updated = transport.update_control_body(
        plan.repository,
        plan.control_ref,
        plan.expected_control_body_sha256,
        edited,
    )
    if updated is not True:
        return _result("NEEDS_EVIDENCE", detail="Control update was not accepted")

    observed = _mapping(
        transport.get_control(plan.repository, plan.control_ref),
        "post-write control",
    )
    if (
        observed.get("repository") != plan.repository
        or observed.get("control_ref") != plan.control_ref
    ):
        return _result("NEEDS_EVIDENCE", detail="post-write identity changed")

    try:
        observed_candidates = _candidate_tasks(observed)
    except SyncCheckContractError as exc:
        return _result("NEEDS_EVIDENCE", detail=str(exc))
    if plan.candidate_task_ref in observed_candidates:
        return _result(
            "NEEDS_EVIDENCE",
            detail="post-write candidate withdrawal was not observed",
        )
    if observed.get("body") != edited:
        return _result(
            "NEEDS_EVIDENCE",
            detail="post-write Control body differs from intended write",
        )

    return _result(
        "AUTO_ADVANCE",
        applied=True,
        detail="stale candidate projection withdrawn and confirmed",
    )
