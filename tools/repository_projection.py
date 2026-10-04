from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools import marker_json, workflow_contract


ISSUE_METADATA_MARKER_BEGIN = "<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V1_BEGIN -->"
ISSUE_METADATA_MARKER_END = "<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V1_END -->"

_SCHEMA_VERSION = 1
_RECORD_ROLES = frozenset({"TASK", "TRACKER", "REFERENCE", "SYSTEM"})
_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "record_role",
        "type",
        "work_status",
        "scope_ready",
        "requires_user_confirmation",
        "external_wait",
    }
)
_OPTIONAL_FIELDS = frozenset(
    {
        "priority",
        "risk",
        "blocked_by",
        "work_order_ref",
        "implementation_ref",
        "next_action_tag",
    }
)
_ALLOWED_FIELDS = _REQUIRED_FIELDS | _OPTIONAL_FIELDS
_CONTRACT = workflow_contract.WORKFLOW_CONTRACT


class ProjectionContractError(ValueError):
    pass


@dataclass(frozen=True)
class IssueMetadata:
    schema_version: int
    record_role: str
    type: str
    work_status: str
    scope_ready: bool
    requires_user_confirmation: bool
    external_wait: bool
    priority: str | None = None
    risk: str | None = None
    blocked_by: tuple[str, ...] = ()
    work_order_ref: str | None = None
    implementation_ref: str | None = None
    next_action_tag: str | None = None

    @property
    def is_task(self) -> bool:
        return self.record_role == "TASK"


def _require_bool(payload: dict[str, Any], field: str) -> bool:
    value = payload[field]
    if not isinstance(value, bool):
        raise ProjectionContractError(f"{field} must be boolean")
    return value


def _optional_enum(
    payload: dict[str, Any],
    field: str,
    allowed: frozenset[str],
) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise ProjectionContractError(f"invalid {field}: {value!r}")
    return value


def _optional_ref(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProjectionContractError(f"{field} must be a non-empty string or null")
    return value.strip()


def _blocked_by(payload: dict[str, Any]) -> tuple[str, ...]:
    value = payload.get("blocked_by")
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProjectionContractError("blocked_by must be an array")
    refs: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ProjectionContractError("blocked_by entries must be non-empty strings")
        ref = item.strip()
        if ref in refs:
            raise ProjectionContractError("blocked_by entries must be unique")
        refs.append(ref)
    return tuple(refs)


def _validate_payload(payload: dict[str, Any]) -> IssueMetadata:
    keys = set(payload)
    missing = sorted(_REQUIRED_FIELDS - keys)
    if missing:
        raise ProjectionContractError(
            "repository Issue metadata missing required fields: " + ", ".join(missing)
        )
    unknown = sorted(keys - _ALLOWED_FIELDS)
    if unknown:
        raise ProjectionContractError(
            "repository Issue metadata has unknown fields: " + ", ".join(unknown)
        )

    schema_version = payload["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != _SCHEMA_VERSION
    ):
        raise ProjectionContractError(
            f"unsupported schema_version: {schema_version!r}"
        )

    record_role = payload["record_role"]
    if not isinstance(record_role, str) or record_role not in _RECORD_ROLES:
        raise ProjectionContractError(f"invalid record_role: {record_role!r}")

    type_value = payload["type"]
    if not isinstance(type_value, str) or type_value not in _CONTRACT.types:
        raise ProjectionContractError(f"invalid type: {type_value!r}")

    work_status = payload["work_status"]
    if (
        not isinstance(work_status, str)
        or work_status not in _CONTRACT.work_states
    ):
        raise ProjectionContractError(f"invalid work_status: {work_status!r}")

    priority = _optional_enum(payload, "priority", _CONTRACT.priorities)
    risk = _optional_enum(payload, "risk", _CONTRACT.risks)

    next_action_tag = _optional_ref(payload, "next_action_tag")
    if next_action_tag is not None and any(ch.isspace() for ch in next_action_tag):
        raise ProjectionContractError("next_action_tag must not contain whitespace")

    return IssueMetadata(
        schema_version=schema_version,
        record_role=record_role,
        type=type_value,
        work_status=work_status,
        scope_ready=_require_bool(payload, "scope_ready"),
        requires_user_confirmation=_require_bool(
            payload,
            "requires_user_confirmation",
        ),
        external_wait=_require_bool(payload, "external_wait"),
        priority=priority,
        risk=risk,
        blocked_by=_blocked_by(payload),
        work_order_ref=_optional_ref(payload, "work_order_ref"),
        implementation_ref=_optional_ref(payload, "implementation_ref"),
        next_action_tag=next_action_tag,
    )


def parse_issue_metadata(body: str) -> IssueMetadata | None:
    try:
        payload = marker_json.parse_json_object_block(
            body,
            ISSUE_METADATA_MARKER_BEGIN,
            ISSUE_METADATA_MARKER_END,
            label="repository Issue metadata",
        )
    except marker_json.MarkerJSONError as exc:
        raise ProjectionContractError(str(exc)) from exc
    if payload is None:
        return None
    return _validate_payload(payload)
