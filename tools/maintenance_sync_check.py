from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


ALLOWLISTED_KIND = "WITHDRAW_STALE_CONTROL_CANDIDATE"
CANDIDATE_BEGIN = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->"
CANDIDATE_END = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->"
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
    reason: str


class SyncCheckTransport(Protocol):
    def get_control(
        self,
        repository: str,
        control_ref: str,
    ) -> dict[str, object]: ...

    def get_owner(
        self,
        repository: str,
        owner_ref: str,
    ) -> dict[str, object]: ...

    def update_control_body(
        self,
        repository: str,
        control_ref: str,
        expected_body_sha256: str,
        body: str,
    ) -> bool: ...


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


def canonical_body_sha256(body: str | None) -> str:
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise SyncCheckContractError("body must be a string or null")
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return (
        "sha256:"
        + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    )


def _gate_active(*sources: Mapping[str, Any]) -> bool:
    for source in sources:
        for field in _GATES:
            if field in source and _bool(source[field], field):
                return True
    return False


def _gate_disposition(*sources: Mapping[str, Any]) -> str | None:
    for source in sources:
        if (
            source.get("human_gate") is True
            or source.get("security_gate") is True
        ):
            return "NEEDS_HUMAN"
    for source in sources:
        if source.get("reviewer_gate") is True:
            return "NEEDS_REVIEWER"
    for source in sources:
        if source.get("external_wait") is True:
            return "WAIT_EXTERNAL"
    for source in sources:
        if source.get("producer_active") is True:
            return "NO_ACTION"
    return None


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


def _candidate_block(
    body: str,
    *,
    repository: str,
) -> tuple[str, dict[str, Any], str]:
    if not isinstance(body, str):
        raise SyncCheckContractError("Control body must be a string")
    if (
        body.count(CANDIDATE_BEGIN) != 1
        or body.count(CANDIDATE_END) != 1
    ):
        raise SyncCheckContractError(
            "Control must contain exactly one candidate block"
        )
    start = body.index(CANDIDATE_BEGIN) + len(CANDIDATE_BEGIN)
    end = body.index(CANDIDATE_END)
    if end <= start:
        raise SyncCheckContractError(
            "candidate block markers are out of order"
        )

    prefix = body[:start]
    suffix = body[end:]
    payload_text = body[start:end]
    payload = payload_text.strip()
    fenced = False
    if payload.startswith("```json"):
        fenced = True
        payload = payload[len("```json"):].lstrip("\r\n")
        if not payload.endswith("```"):
            raise SyncCheckContractError(
                "candidate JSON fence is not closed"
            )
        payload = payload[:-3].rstrip()
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SyncCheckContractError(
            "candidate block contains invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise SyncCheckContractError(
            "candidate block root must be an object"
        )
    if value.get("schema_version") != 1:
        raise SyncCheckContractError(
            "candidate block schema_version must be 1"
        )
    if value.get("repository") != repository:
        raise SyncCheckContractError(
            "candidate block repository identity mismatch"
        )
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        raise SyncCheckContractError(
            "candidate block candidates must be an array"
        )
    task_refs: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise SyncCheckContractError(
                "candidate entry must be an object"
            )
        task = candidate.get("task")
        if not isinstance(task, str) or not task:
            raise SyncCheckContractError(
                "candidate task identity is invalid"
            )
        task_refs.append(task)
    if len(task_refs) != len(set(task_refs)):
        raise SyncCheckContractError(
            "candidate block contains duplicate task identities"
        )
    value["_render_fenced"] = fenced
    return prefix, value, suffix


def withdraw_candidate_projection(
    body: str,
    *,
    repository: str,
    task_ref: str,
) -> str:
    prefix, value, suffix = _candidate_block(
        body,
        repository=repository,
    )
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    matches = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and candidate.get("task") == task_ref
    ]
    if len(matches) > 1:
        raise SyncCheckContractError(
            "target task appears more than once"
        )
    if not matches:
        return body

    value["candidates"] = [
        candidate
        for candidate in candidates
        if not (
            isinstance(candidate, dict)
            and candidate.get("task") == task_ref
        )
    ]
    fenced = bool(value.pop("_render_fenced", False))
    rendered = json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
    )
    if fenced:
        rendered = "```json\n" + rendered + "\n```"
    return prefix + "\n" + rendered + "\n" + suffix


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


def _executor_snapshot(
    value: object,
    *,
    repository: str,
    identity_field: str,
    identity_value: str,
    name: str,
) -> Mapping[str, Any]:
    snapshot = _mapping(value, name)
    if snapshot.get("repository") != repository:
        raise SyncCheckContractError(
            f"{name} repository identity mismatch"
        )
    if snapshot.get(identity_field) != identity_value:
        raise SyncCheckContractError(
            f"{name} object identity mismatch"
        )
    return snapshot


def execute_sync_check(
    plan: SyncCheckPlan,
    transport: SyncCheckTransport,
) -> SyncCheckResult:
    if not isinstance(plan, SyncCheckPlan):
        raise SyncCheckContractError(
            "plan must be a SyncCheckPlan"
        )
    if plan.kind != ALLOWLISTED_KIND:
        raise SyncCheckContractError(
            "unsupported sync-check plan kind"
        )

    try:
        control = _executor_snapshot(
            transport.get_control(
                plan.repository,
                plan.control_ref,
            ),
            repository=plan.repository,
            identity_field="control_ref",
            identity_value=plan.control_ref,
            name="control",
        )
        owner = _executor_snapshot(
            transport.get_owner(
                plan.repository,
                plan.owner_ref,
            ),
            repository=plan.repository,
            identity_field="owner_ref",
            identity_value=plan.owner_ref,
            name="owner",
        )
        control_body = _string(
            control.get("body"),
            "control.body",
        )
        assert isinstance(control_body, str)
        _prefix, parsed, _suffix = _candidate_block(
            control_body,
            repository=plan.repository,
        )
        candidates = parsed.get("candidates")
        assert isinstance(candidates, list)
        current_tasks = {
            candidate.get("task")
            for candidate in candidates
            if isinstance(candidate, dict)
        }
    except SyncCheckContractError as exc:
        return SyncCheckResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            str(exc),
        )

    gate = _gate_disposition(control, owner)
    if gate is not None:
        return SyncCheckResult(
            False,
            False,
            gate,
            "a stronger gate appeared before sync-check apply",
        )

    if plan.candidate_task_ref not in current_tasks:
        return SyncCheckResult(
            False,
            True,
            "NO_ACTION",
            "target candidate is already absent",
        )

    try:
        current_control_sha = _sha256(
            control.get("body_sha256"),
            "control.body_sha256",
        )
        current_owner_sha = _sha256(
            owner.get("body_sha256"),
            "owner.body_sha256",
        )
    except SyncCheckContractError as exc:
        return SyncCheckResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            str(exc),
        )

    if (
        current_control_sha
        != plan.expected_control_body_sha256
        or current_owner_sha
        != plan.expected_owner_body_sha256
    ):
        return SyncCheckResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "Control or owner body identity changed",
        )

    if (
        owner.get("terminal") is not True
        or owner.get("runnable") is not False
        or str(owner.get("state") or "").upper() != "CLOSED"
    ):
        return SyncCheckResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "owner lifecycle changed before sync-check apply",
        )

    try:
        updated_body = withdraw_candidate_projection(
            control_body,
            repository=plan.repository,
            task_ref=plan.candidate_task_ref,
        )
    except SyncCheckContractError as exc:
        return SyncCheckResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            str(exc),
        )
    if updated_body == control_body:
        return SyncCheckResult(
            False,
            True,
            "NO_ACTION",
            "target candidate is already absent",
        )

    confirmed = transport.update_control_body(
        plan.repository,
        plan.control_ref,
        plan.expected_control_body_sha256,
        updated_body,
    )
    if confirmed is not True:
        return SyncCheckResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "bounded Control update was not confirmed",
        )

    try:
        observed = _executor_snapshot(
            transport.get_control(
                plan.repository,
                plan.control_ref,
            ),
            repository=plan.repository,
            identity_field="control_ref",
            identity_value=plan.control_ref,
            name="post_write_control",
        )
        observed_body = _string(
            observed.get("body"),
            "post_write_control.body",
        )
        assert isinstance(observed_body, str)
        _p, observed_block, _s = _candidate_block(
            observed_body,
            repository=plan.repository,
        )
        observed_candidates = observed_block.get("candidates")
        assert isinstance(observed_candidates, list)
        if any(
            isinstance(candidate, dict)
            and candidate.get("task")
            == plan.candidate_task_ref
            for candidate in observed_candidates
        ):
            raise SyncCheckContractError(
                "post-write readback still contains target candidate"
            )
        if observed_body != updated_body:
            raise SyncCheckContractError(
                "post-write Control body differs from bounded update"
            )
    except SyncCheckContractError as exc:
        return SyncCheckResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            str(exc),
        )

    return SyncCheckResult(
        True,
        False,
        "AUTO_ADVANCE",
        "stale Control candidate withdrawal confirmed",
    )
