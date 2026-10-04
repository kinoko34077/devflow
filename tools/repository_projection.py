from __future__ import annotations

import json
from typing import Any

try:
    from .workflow_contract import WORKFLOW_CONTRACT
except ImportError:  # direct script execution
    from workflow_contract import WORKFLOW_CONTRACT


ISSUE_METADATA_BEGIN = "<!-- DEVFLOW_ISSUE_METADATA_V1_BEGIN -->"
ISSUE_METADATA_END = "<!-- DEVFLOW_ISSUE_METADATA_V1_END -->"

RECORD_ROLES = frozenset({"TASK", "TRACKER", "REFERENCE", "SYSTEM"})
ACTIONABLE_WORK_STATES = frozenset({
    "WORK_ORDER_READY",
    "READY_FOR_IMPLEMENTATION",
    "IMPLEMENTING",
})

_ALLOWED_KEYS = frozenset({
    "schema_version",
    "record_role",
    "type",
    "work_status",
    "scope_ready",
    "requires_user_confirmation",
    "external_wait",
    "priority",
    "risk",
    "blocked_by",
    "work_order_ref",
    "implementation_ref",
    "next_action_tag",
})
_TASK_REQUIRED = frozenset({
    "record_role",
    "type",
    "work_status",
    "scope_ready",
    "requires_user_confirmation",
    "external_wait",
})

_LEGACY_ROLE_HINTS = (
    ("[WORK ORDER]", "TASK"),
    ("[BUG]", "TASK"),
    ("[FEATURE]", "TASK"),
    ("[REFACTOR]", "TASK"),
    ("[MAINTENANCE]", "TASK"),
    ("[INFRA]", "TASK"),
    ("[DOCS]", "TASK"),
    ("[PROGRESS]", "TRACKER"),
    ("[TRACKER]", "TRACKER"),
    ("[SPEC]", "REFERENCE"),
    ("[RESEARCH]", "REFERENCE"),
    ("[AUDIT]", "REFERENCE"),
    ("[DECISION]", "REFERENCE"),
    ("[PROPOSAL]", "REFERENCE"),
    ("[REPO CREATE]", "SYSTEM"),
    ("[REPO]", "SYSTEM"),
    ("[SYSTEM]", "SYSTEM"),
)


class RepositoryProjectionError(ValueError):
    """Malformed or unsupported Repository Projection input."""


def _extract_payload(body: str) -> str | None:
    text = body or ""
    begin_count = text.count(ISSUE_METADATA_BEGIN)
    end_count = text.count(ISSUE_METADATA_END)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise RepositoryProjectionError("Issue metadata markers are missing or duplicated")
    start = text.index(ISSUE_METADATA_BEGIN) + len(ISSUE_METADATA_BEGIN)
    end = text.index(ISSUE_METADATA_END)
    if end <= start:
        raise RepositoryProjectionError("Issue metadata markers are out of order")
    payload = text[start:end].strip()
    if payload.startswith("```json"):
        payload = payload[len("```json"):].lstrip("\r\n")
        if not payload.endswith("```"):
            raise RepositoryProjectionError("Issue metadata JSON fence is not closed")
        payload = payload[:-3].rstrip()
    elif payload.startswith("```"):
        raise RepositoryProjectionError("Issue metadata fence must be ```json")
    if not payload:
        raise RepositoryProjectionError("Issue metadata payload is empty")
    return payload


def _require_enum(value: Any, field: str, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or not value:
        raise RepositoryProjectionError(
            f"Issue metadata {field} must be a non-empty string"
        )
    if value not in allowed:
        raise RepositoryProjectionError(
            f"Issue metadata {field} has unsupported value {value!r}"
        )
    return value


def _validate_optional_ref(value: Any, field: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise RepositoryProjectionError(
            f"Issue metadata {field} must be null or a non-empty string"
        )


def _validate_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RepositoryProjectionError("Issue metadata JSON must be an object")
    unknown = sorted(set(value) - _ALLOWED_KEYS)
    if unknown:
        raise RepositoryProjectionError(
            "Issue metadata contains unsupported fields: " + ", ".join(unknown)
        )
    if value.get("schema_version") != 1:
        raise RepositoryProjectionError("Issue metadata schema_version must be 1")

    role = _require_enum(value.get("record_role"), "record_role", RECORD_ROLES)
    if role == "TASK":
        missing = sorted(_TASK_REQUIRED - set(value))
        if missing:
            raise RepositoryProjectionError(
                "Issue metadata TASK is missing required fields: "
                + ", ".join(missing)
            )

    if "type" in value:
        _require_enum(value["type"], "type", WORKFLOW_CONTRACT.types)
    if "work_status" in value:
        _require_enum(
            value["work_status"],
            "work_status",
            WORKFLOW_CONTRACT.work_states,
        )
    if "priority" in value:
        _require_enum(
            value["priority"],
            "priority",
            WORKFLOW_CONTRACT.priorities,
        )
    if "risk" in value:
        _require_enum(value["risk"], "risk", WORKFLOW_CONTRACT.risks)

    for field in (
        "scope_ready",
        "requires_user_confirmation",
        "external_wait",
    ):
        if field in value and not isinstance(value[field], bool):
            raise RepositoryProjectionError(
                f"Issue metadata {field} must be boolean"
            )

    if "blocked_by" in value:
        blocked = value["blocked_by"]
        if not isinstance(blocked, list):
            raise RepositoryProjectionError(
                "Issue metadata blocked_by must be a list"
            )
        if any(
            not isinstance(item, str) or not item.strip()
            for item in blocked
        ):
            raise RepositoryProjectionError(
                "Issue metadata blocked_by entries must be non-empty strings"
            )
        if len(blocked) != len(set(blocked)):
            raise RepositoryProjectionError(
                "Issue metadata blocked_by contains duplicates"
            )

    for field in (
        "work_order_ref",
        "implementation_ref",
        "next_action_tag",
    ):
        if field in value:
            _validate_optional_ref(value[field], field)

    return dict(value)


def parse_issue_metadata(body: str) -> dict[str, Any] | None:
    """Parse one optional repository-local machine metadata block."""
    payload = _extract_payload(body)
    if payload is None:
        return None
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RepositoryProjectionError(
            "Issue metadata contains invalid JSON"
        ) from exc
    return _validate_metadata(value)


def _legacy_role_hint(title: str) -> str | None:
    upper = (title or "").strip().upper()
    for prefix, role in _LEGACY_ROLE_HINTS:
        if upper.startswith(prefix):
            return role
    return None


def _machine_task_actionable(
    metadata: dict[str, Any],
    state: str,
) -> bool:
    return (
        metadata.get("record_role") == "TASK"
        and state == "open"
        and metadata.get("scope_ready") is True
        and metadata.get("requires_user_confirmation") is False
        and metadata.get("external_wait") is False
        and metadata.get("work_status") in ACTIONABLE_WORK_STATES
    )


def classify_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Classify one GitHub Issue without treating open state as task authority."""
    title = str(issue.get("title") or "")
    state = str(issue.get("state") or "")
    base = {
        "issue_number": int(issue.get("number") or 0),
        "title": title,
        "state": state,
        "url": str(issue.get("html_url") or issue.get("url") or ""),
        "created_at": str(issue.get("created_at") or ""),
        "updated_at": str(issue.get("updated_at") or ""),
    }
    try:
        metadata = parse_issue_metadata(str(issue.get("body") or ""))
    except RepositoryProjectionError as exc:
        return {
            **base,
            "classification_source": "INVALID_MACHINE",
            "record_role": None,
            "record_role_hint": _legacy_role_hint(title),
            "actionable": False,
            "metadata": None,
            "diagnostics": [str(exc)],
        }

    if metadata is not None:
        return {
            **base,
            "classification_source": "MACHINE",
            "record_role": metadata["record_role"],
            "record_role_hint": None,
            "actionable": _machine_task_actionable(metadata, state),
            "metadata": metadata,
            "diagnostics": [],
        }

    hint = _legacy_role_hint(title)
    return {
        **base,
        "classification_source": (
            "LEGACY_HINT" if hint else "UNCLASSIFIED"
        ),
        "record_role": None,
        "record_role_hint": hint,
        "actionable": False,
        "metadata": None,
        "diagnostics": [],
    }
