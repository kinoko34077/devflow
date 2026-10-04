from __future__ import annotations

from dataclasses import dataclass
import re
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


_LEADING_TOKEN_RE = re.compile(r"^\[([^\]]+)\]")
_LEGACY_PRIORITY_TOKENS = frozenset(_CONTRACT.priorities)


@dataclass(frozen=True)
class IssueRecord:
    number: int
    title: str
    state: str
    created_at: str
    updated_at: str
    html_url: str
    source_kind: str
    record_role: str | None = None
    type: str | None = None
    work_status: str | None = None
    scope_ready: bool | None = None
    requires_user_confirmation: bool | None = None
    external_wait: bool | None = None
    priority: str | None = None
    risk: str | None = None
    metadata_error: str | None = None

    @property
    def is_task(self) -> bool:
        return self.source_kind == "MACHINE" and self.record_role == "TASK"


def _issue_native_fields(issue: Mapping[str, Any]) -> dict[str, Any]:
    number = issue.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ProjectionContractError("Issue number must be a positive integer")
    title = issue.get("title")
    if not isinstance(title, str):
        raise ProjectionContractError("Issue title must be a string")
    state = issue.get("state")
    if not isinstance(state, str) or not state:
        raise ProjectionContractError("Issue state must be a non-empty string")
    created_at = issue.get("created_at")
    updated_at = issue.get("updated_at")
    if not isinstance(created_at, str) or not created_at:
        raise ProjectionContractError("Issue created_at must be a non-empty string")
    if not isinstance(updated_at, str) or not updated_at:
        raise ProjectionContractError("Issue updated_at must be a non-empty string")
    html_url = issue.get("html_url")
    if html_url is None:
        html_url = ""
    if not isinstance(html_url, str):
        raise ProjectionContractError("Issue html_url must be a string when present")
    return {
        "number": number,
        "title": title,
        "state": state,
        "created_at": created_at,
        "updated_at": updated_at,
        "html_url": html_url,
    }


def _legacy_hints(title: str) -> tuple[str | None, str | None]:
    remaining = title
    found_type: str | None = None
    found_priority: str | None = None
    while True:
        match = _LEADING_TOKEN_RE.match(remaining)
        if match is None:
            break
        token = match.group(1).strip()
        if token in _CONTRACT.types and found_type is None:
            found_type = token
        if token in _LEGACY_PRIORITY_TOKENS and found_priority is None:
            found_priority = token
        remaining = remaining[match.end():]
    return found_type, found_priority


def classify_issue(issue: Mapping[str, Any]) -> IssueRecord:
    native = _issue_native_fields(issue)
    body = issue.get("body")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise ProjectionContractError("Issue body must be a string when present")

    try:
        metadata = parse_issue_metadata(body)
    except ProjectionContractError as exc:
        return IssueRecord(
            **native,
            source_kind="INVALID_METADATA",
            metadata_error=str(exc),
        )

    if metadata is not None:
        return IssueRecord(
            **native,
            source_kind="MACHINE",
            record_role=metadata.record_role,
            type=metadata.type,
            work_status=metadata.work_status,
            scope_ready=metadata.scope_ready,
            requires_user_confirmation=metadata.requires_user_confirmation,
            external_wait=metadata.external_wait,
            priority=metadata.priority,
            risk=metadata.risk,
        )

    legacy_type, legacy_priority = _legacy_hints(native["title"])
    if legacy_type is not None or legacy_priority is not None:
        return IssueRecord(
            **native,
            source_kind="LEGACY_HINT",
            type=legacy_type,
            priority=legacy_priority,
        )
    return IssueRecord(**native, source_kind="UNCLASSIFIED")


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


@dataclass(frozen=True)
class IssueRecord:
    number: int
    title: str
    state: str
    created_at: str
    updated_at: str
    html_url: str | None
    source_kind: str
    record_role: str | None
    type: str | None
    work_status: str | None
    metadata: IssueMetadata | None
    metadata_error: str | None = None

    @property
    def is_task(self) -> bool:
        return self.metadata is not None and self.metadata.is_task


_LEADING_TAGS = re.compile(r"^((?:\[[^\]\r\n]+\])+)")


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


def _issue_number(issue: dict[str, Any]) -> int:
    value = issue.get("number")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProjectionContractError("Issue number must be a positive integer")
    return value


def _issue_text(issue: dict[str, Any], field: str) -> str:
    value = issue.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProjectionContractError(f"Issue {field} must be a non-empty string")
    return value.strip()


def _legacy_type_hint(title: str) -> str | None:
    match = _LEADING_TAGS.match(title.strip())
    if match is None:
        return None
    for tag in re.findall(r"\[([^\]]+)\]", match.group(1)):
        if tag in _CONTRACT.types:
            return tag
    return None


def classify_issue(issue: dict[str, Any]) -> IssueRecord:
    number = _issue_number(issue)
    title = _issue_text(issue, "title")
    state = _issue_text(issue, "state").lower()
    created_at = _issue_text(issue, "created_at")
    updated_at = _issue_text(issue, "updated_at")
    html_url_value = issue.get("html_url")
    if html_url_value is not None and (
        not isinstance(html_url_value, str) or not html_url_value.strip()
    ):
        raise ProjectionContractError("Issue html_url must be a non-empty string or null")
    html_url = html_url_value.strip() if isinstance(html_url_value, str) else None

    try:
        metadata = parse_issue_metadata(str(issue.get("body") or ""))
    except ProjectionContractError as exc:
        return IssueRecord(
            number=number,
            title=title,
            state=state,
            created_at=created_at,
            updated_at=updated_at,
            html_url=html_url,
            source_kind="INVALID_METADATA",
            record_role=None,
            type=None,
            work_status=None,
            metadata=None,
            metadata_error=str(exc),
        )

    if metadata is not None:
        return IssueRecord(
            number=number,
            title=title,
            state=state,
            created_at=created_at,
            updated_at=updated_at,
            html_url=html_url,
            source_kind="MACHINE",
            record_role=metadata.record_role,
            type=metadata.type,
            work_status=metadata.work_status,
            metadata=metadata,
        )

    legacy_type = _legacy_type_hint(title)
    if legacy_type is not None:
        return IssueRecord(
            number=number,
            title=title,
            state=state,
            created_at=created_at,
            updated_at=updated_at,
            html_url=html_url,
            source_kind="LEGACY_HINT",
            record_role=None,
            type=legacy_type,
            work_status=None,
            metadata=None,
        )

    return IssueRecord(
        number=number,
        title=title,
        state=state,
        created_at=created_at,
        updated_at=updated_at,
        html_url=html_url,
        source_kind="UNCLASSIFIED",
        record_role=None,
        type=None,
        work_status=None,
        metadata=None,
    )
