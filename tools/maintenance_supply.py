from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Mapping


ADMISSION_SCHEMA_VERSION = 1
PORTFOLIO_SCHEMA_VERSION = "execution-portfolio-metadata.v1"
SUPPLY_SCHEMA_VERSION = "maintenance-existing-owner-supply.v1"
CANDIDATE_BEGIN = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->"
CANDIDATE_END = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->"
PORTFOLIO_BEGIN = "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN -->"
PORTFOLIO_END = "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_END -->"
_ALLOWED_WORK_CLASSES = frozenset(
    {"audit", "triage", "sync-check", "quickfix", "implementation"}
)
_SHA_PREFIX = "sha256:"


class MaintenanceSupplyError(ValueError):
    pass


def _mapping(value: object, field: str) -> dict[str, Any]:
    if is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        raise MaintenanceSupplyError(f"{field} must be an object")
    return dict(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MaintenanceSupplyError(f"{field} must be a non-empty string")
    return value


def _sha(value: object, field: str) -> str:
    text = _string(value, field)
    if (
        not text.startswith(_SHA_PREFIX)
        or len(text) != len(_SHA_PREFIX) + 64
        or any(ch not in "0123456789abcdef" for ch in text[len(_SHA_PREFIX):])
    ):
        raise MaintenanceSupplyError(f"{field} must be canonical sha256")
    return text


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise MaintenanceSupplyError(f"{field} must be boolean")
    return value


def _timestamp(value: object, field: str) -> datetime:
    text = _string(value, field)
    if not text.endswith("Z"):
        raise MaintenanceSupplyError(f"{field} must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise MaintenanceSupplyError(
            f"{field} must be RFC3339 UTC"
        ) from exc


def _canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _SHA_PREFIX + hashlib.sha256(raw).hexdigest()


def _gated(*sources: Mapping[str, Any]) -> bool:
    for source in sources:
        for field in (
            "human_gate",
            "reviewer_gate",
            "external_wait",
            "security_gate",
        ):
            if field in source and _bool(source[field], field):
                return True
    return False


def _candidate_fingerprint(admission: Mapping[str, Any]) -> str:
    material = {
        "task": admission["task"],
        "task_body_sha256": admission["task_body_sha256"],
        "task_work_status": admission["task_work_status"],
        "entry_ref": admission["entry_ref"],
        "scope_ready": admission["scope_ready"],
        "blocked": admission["blocked"],
        "requires_user_confirmation": admission[
            "requires_user_confirmation"
        ],
        "conflict_keys": admission["conflict_keys"],
        "work_order_ref": admission.get("work_order_ref"),
        "roles": admission["roles"],
    }
    return _canonical_hash(material)


def build_existing_owner_candidate(
    decision: object,
    owner_snapshot: object,
    control_snapshot: object,
) -> dict[str, object] | None:
    decision_map = _mapping(decision, "decision")
    owner = _mapping(owner_snapshot, "owner_snapshot")
    control = _mapping(control_snapshot, "control_snapshot")

    action = decision_map.get("action")
    if action not in {"PUBLISH_EXISTING_OWNER", "PLAN_SYNC_CHECK"}:
        return None
    owner_ref = decision_map.get("owner_ref")
    if owner_ref is None:
        return None
    owner_ref = _string(owner_ref, "decision.owner_ref")
    work_class = _string(
        decision_map.get("work_class"),
        "decision.work_class",
    )
    if work_class not in _ALLOWED_WORK_CLASSES:
        return None

    repository = _string(
        control.get("repository"),
        "control_snapshot.repository",
    )
    control_ref = _string(
        control.get("control_ref"),
        "control_snapshot.control_ref",
    )
    if owner.get("repository") != repository:
        return None
    if owner.get("task_ref") != owner_ref:
        return None
    if not owner_ref.startswith(repository + "#"):
        return None

    if control.get("trusted") is not True:
        return None
    if control.get("repository_state") != "ACTIVE":
        return None
    if owner.get("trusted") is not True:
        return None
    if owner.get("is_pull_request") is not False:
        return None
    if str(owner.get("state") or "").upper() != "OPEN":
        return None
    if owner.get("work_status") != "READY_FOR_IMPLEMENTATION":
        return None
    if owner.get("scope_ready") is not True:
        return None
    if owner.get("blocked") is not False:
        return None
    if owner.get("requires_user_confirmation") is not False:
        return None
    if _gated(control, owner):
        return None

    body_sha = _sha(
        owner.get("body_sha256"),
        "owner_snapshot.body_sha256",
    )
    expected_body_sha = control.get("expected_owner_body_sha256")
    if expected_body_sha is not None:
        if _sha(
            expected_body_sha,
            "control_snapshot.expected_owner_body_sha256",
        ) != body_sha:
            return None

    observed_at = _string(
        control.get("observed_at"),
        "control_snapshot.observed_at",
    )
    fresh_until = _string(
        control.get("fresh_until"),
        "control_snapshot.fresh_until",
    )
    if _timestamp(fresh_until, "control_snapshot.fresh_until") <= _timestamp(
        observed_at,
        "control_snapshot.observed_at",
    ):
        return None
    publisher_attempt = _string(
        control.get("publisher_execution_attempt_id"),
        "control_snapshot.publisher_execution_attempt_id",
    )

    entry_ref = _string(owner.get("entry_ref"), "owner_snapshot.entry_ref")
    expected_entry = (
        "https://github.com/"
        + owner_ref.rsplit("#", 1)[0]
        + "/issues/"
        + owner_ref.rsplit("#", 1)[1]
    )
    if entry_ref != expected_entry:
        return None

    conflict_keys_value = owner.get("conflict_keys", ())
    if not isinstance(conflict_keys_value, (list, tuple)) or not all(
        isinstance(item, str) and item
        for item in conflict_keys_value
    ):
        raise MaintenanceSupplyError(
            "owner_snapshot.conflict_keys must be an array of strings"
        )
    conflict_keys = sorted(set(conflict_keys_value))
    if len(conflict_keys) != len(conflict_keys_value):
        return None

    admission: dict[str, object] = {
        "task": owner_ref,
        "task_body_sha256": body_sha,
        "task_work_status": "READY_FOR_IMPLEMENTATION",
        "entry_ref": entry_ref,
        "scope_ready": True,
        "blocked": False,
        "requires_user_confirmation": False,
        "conflict_keys": conflict_keys,
        "roles": [
            {
                "role": "implementer",
                "next_action_tag": "IMPLEMENT",
            }
        ],
    }
    work_order_ref = owner.get("work_order_ref")
    if work_order_ref is not None:
        admission["work_order_ref"] = _string(
            work_order_ref,
            "owner_snapshot.work_order_ref",
        )

    fingerprint = _candidate_fingerprint(admission)
    required_capabilities = owner.get("required_capabilities", ())
    required_environment = owner.get("required_environment", ())
    for value, field in (
        (required_capabilities, "required_capabilities"),
        (required_environment, "required_environment"),
    ):
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise MaintenanceSupplyError(
                f"owner_snapshot.{field} must be an array of strings"
            )

    portfolio: dict[str, object] = {
        "task": owner_ref,
        "role": "implementer",
        "work_class": work_class,
        "task_body_sha256": body_sha,
        "candidate_fingerprint": fingerprint,
        "controller_urgency": None,
        "dependency_ready": True,
        "dependency_order": 0,
        "readiness_class": "IMPLEMENT",
        "ready_at": None,
        "required_capabilities": sorted(set(required_capabilities)),
        "required_environment": sorted(set(required_environment)),
        "observed_at": observed_at,
        "fresh_until": fresh_until,
    }

    logical = {
        "repository": repository,
        "control_ref": control_ref,
        "admission": admission,
        "work_class": work_class,
        "required_capabilities": portfolio["required_capabilities"],
        "required_environment": portfolio["required_environment"],
    }
    publication_id = _canonical_hash(logical)

    return {
        "schema_version": SUPPLY_SCHEMA_VERSION,
        "publication_id": publication_id,
        "repository": repository,
        "control_ref": control_ref,
        "candidate_fingerprint": fingerprint,
        "admission": admission,
        "portfolio": portfolio,
        "publisher_execution_attempt_id": publisher_attempt,
    }


def _supply_task(value: Mapping[str, Any]) -> str | None:
    admission = value.get("admission")
    if not isinstance(admission, dict):
        return None
    task = admission.get("task")
    return task if isinstance(task, str) else None


def reconcile_existing_owner_supply(
    existing_projection: object,
    desired_candidate: object,
    *,
    task_ref: str | None = None,
) -> dict[str, object]:
    if not isinstance(existing_projection, list):
        raise MaintenanceSupplyError(
            "existing_projection must be an array"
        )
    existing: list[dict[str, Any]] = []
    for item in existing_projection:
        existing.append(_mapping(item, "existing supply"))

    desired: dict[str, Any] | None
    if desired_candidate is None:
        desired = None
    else:
        desired = _mapping(desired_candidate, "desired_candidate")

    target = task_ref
    if desired is not None:
        target = _supply_task(desired)
    if target is None:
        raise MaintenanceSupplyError(
            "task_ref is required when desired_candidate is null"
        )

    active: list[dict[str, Any]] = []
    superseded: list[str] = []
    matched_same = False
    desired_id = (
        _sha(desired.get("publication_id"), "desired publication_id")
        if desired is not None
        else None
    )

    for item in existing:
        if _supply_task(item) != target:
            active.append(item)
            continue
        item_id = _sha(
            item.get("publication_id"),
            "existing publication_id",
        )
        if desired_id is not None and item_id == desired_id:
            if not matched_same:
                active.append(item)
                matched_same = True
            continue
        superseded.append(item_id)

    if desired is not None and not matched_same:
        active.append(desired)

    active.sort(
        key=lambda item: (
            str(item.get("repository") or ""),
            str(_supply_task(item) or ""),
            str(item.get("publication_id") or ""),
        )
    )
    return {
        "active": active,
        "superseded_ids": sorted(set(superseded)),
    }


def published_by_attempt(
    supply: object,
    execution_attempt_id: str,
) -> bool:
    value = _mapping(supply, "supply")
    return (
        value.get("publisher_execution_attempt_id")
        == execution_attempt_id
    )


def _parse_projection_block(
    body: str,
    *,
    start_marker: str,
    end_marker: str,
    repository: str,
    control_ref: str,
    schema_version: object,
    array_key: str,
) -> tuple[dict[str, Any], int, int]:
    if body.count(start_marker) != 1 or body.count(end_marker) != 1:
        raise MaintenanceSupplyError(
            "Control projection block is missing or ambiguous"
        )
    start = body.index(start_marker) + len(start_marker)
    end = body.index(end_marker)
    if end <= start:
        raise MaintenanceSupplyError(
            "Control projection markers are out of order"
        )
    payload = body[start:end].strip()
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MaintenanceSupplyError(
            "Control projection contains invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise MaintenanceSupplyError(
            "Control projection must be an object"
        )
    if set(value) != {
        "schema_version",
        "source_ref",
        "repository",
        array_key,
    }:
        raise MaintenanceSupplyError(
            "Control projection contains unsupported outer fields"
        )
    if value.get("schema_version") != schema_version:
        raise MaintenanceSupplyError(
            "Control projection schema version mismatch"
        )
    if value.get("source_ref") != control_ref:
        raise MaintenanceSupplyError(
            "Control projection source_ref mismatch"
        )
    if value.get("repository") != repository:
        raise MaintenanceSupplyError(
            "Control projection repository mismatch"
        )
    if not isinstance(value.get(array_key), list):
        raise MaintenanceSupplyError(
            f"Control projection {array_key} must be an array"
        )
    return value, start, end


def _replace_projection_payload(
    body: str,
    *,
    start: int,
    end: int,
    value: dict[str, Any],
) -> str:
    payload = (
        "\n"
        + json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return body[:start] + payload + body[end:]


def reconcile_control_projection_body(
    body: str,
    desired_supply: object,
    *,
    task_ref: str,
) -> tuple[str, bool]:
    if not isinstance(body, str):
        raise MaintenanceSupplyError("Control body must be a string")
    task_ref = _string(task_ref, "task_ref")

    supply: dict[str, Any] | None
    if desired_supply is None:
        supply = None
        repository = task_ref.rsplit("#", 1)[0]
        control_ref = None
    else:
        supply = _mapping(desired_supply, "desired_supply")
        repository = _string(
            supply.get("repository"),
            "desired_supply.repository",
        )
        control_ref = _string(
            supply.get("control_ref"),
            "desired_supply.control_ref",
        )
        if _supply_task(supply) != task_ref:
            raise MaintenanceSupplyError(
                "desired supply task does not match task_ref"
            )

    if control_ref is None:
        # Withdrawal still validates the existing block identities and derives
        # the exact Control reference from the admission block.
        if body.count(CANDIDATE_BEGIN) != 1:
            raise MaintenanceSupplyError(
                "candidate projection block is missing or ambiguous"
            )
        start = body.index(CANDIDATE_BEGIN) + len(CANDIDATE_BEGIN)
        end = body.index(CANDIDATE_END)
        try:
            existing_outer = json.loads(body[start:end].strip())
        except json.JSONDecodeError as exc:
            raise MaintenanceSupplyError(
                "candidate projection contains invalid JSON"
            ) from exc
        if not isinstance(existing_outer, dict):
            raise MaintenanceSupplyError(
                "candidate projection must be an object"
            )
        control_ref = _string(
            existing_outer.get("source_ref"),
            "candidate projection source_ref",
        )
        if existing_outer.get("repository") != repository:
            raise MaintenanceSupplyError(
                "candidate projection repository mismatch"
            )

    candidate, cstart, cend = _parse_projection_block(
        body,
        start_marker=CANDIDATE_BEGIN,
        end_marker=CANDIDATE_END,
        repository=repository,
        control_ref=control_ref,
        schema_version=ADMISSION_SCHEMA_VERSION,
        array_key="candidates",
    )
    candidates = candidate["candidates"]
    if not all(isinstance(item, dict) for item in candidates):
        raise MaintenanceSupplyError(
            "candidate projection entries must be objects"
        )
    candidate_tasks = [
        item.get("task") for item in candidates
    ]
    if not all(isinstance(item, str) and item for item in candidate_tasks):
        raise MaintenanceSupplyError(
            "candidate projection task is malformed"
        )
    if len(set(candidate_tasks)) != len(candidate_tasks):
        raise MaintenanceSupplyError(
            "candidate projection contains duplicate task envelopes"
        )
    next_candidates = [
        dict(item)
        for item in candidates
        if item.get("task") != task_ref
    ]
    if supply is not None:
        admission = supply.get("admission")
        if not isinstance(admission, dict):
            raise MaintenanceSupplyError(
                "desired supply admission is missing"
            )
        next_candidates.append(dict(admission))
    next_candidates.sort(key=lambda item: str(item.get("task") or ""))
    candidate["candidates"] = next_candidates
    edited = _replace_projection_payload(
        body,
        start=cstart,
        end=cend,
        value=candidate,
    )

    portfolio, pstart, pend = _parse_projection_block(
        edited,
        start_marker=PORTFOLIO_BEGIN,
        end_marker=PORTFOLIO_END,
        repository=repository,
        control_ref=control_ref,
        schema_version=PORTFOLIO_SCHEMA_VERSION,
        array_key="entries",
    )
    entries = portfolio["entries"]
    if not all(isinstance(item, dict) for item in entries):
        raise MaintenanceSupplyError(
            "portfolio projection entries must be objects"
        )
    keys = [
        (item.get("task"), item.get("role"))
        for item in entries
    ]
    if not all(
        isinstance(task, str)
        and task
        and isinstance(role, str)
        and role
        for task, role in keys
    ):
        raise MaintenanceSupplyError(
            "portfolio projection identity is malformed"
        )
    if len(set(keys)) != len(keys):
        raise MaintenanceSupplyError(
            "portfolio projection contains duplicate task/role entries"
        )
    next_entries = [
        dict(item)
        for item in entries
        if item.get("task") != task_ref
    ]
    if supply is not None:
        metadata = supply.get("portfolio")
        if not isinstance(metadata, dict):
            raise MaintenanceSupplyError(
                "desired supply portfolio metadata is missing"
            )
        next_entries.append(dict(metadata))
    next_entries.sort(
        key=lambda item: (
            str(item.get("task") or ""),
            str(item.get("role") or ""),
        )
    )
    portfolio["entries"] = next_entries
    final = _replace_projection_payload(
        edited,
        start=pstart,
        end=pend,
        value=portfolio,
    )
    return final, final != body
