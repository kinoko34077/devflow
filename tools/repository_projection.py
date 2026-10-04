from __future__ import annotations

import json
import re
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
SOURCE_STATUSES = frozenset({"OK", "ERROR", "UNKNOWN"})
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

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


def _issue_ref(repository: str, issue_number: int) -> str | None:
    return f"{repository}#{issue_number}" if issue_number > 0 else None


def _latest_ref(
    repository: str,
    classified: list[dict[str, Any]],
    field: str,
) -> str | None:
    candidates = [
        item
        for item in classified
        if item.get("state") == "open"
        and item.get(field)
        and int(item.get("issue_number") or 0) > 0
    ]
    if not candidates:
        return None
    latest = max(
        candidates,
        key=lambda item: (
            str(item.get(field) or ""),
            int(item.get("issue_number") or 0),
        ),
    )
    return _issue_ref(repository, int(latest["issue_number"]))


def _empty_counts() -> dict[str, Any]:
    return {
        "open_issues": 0,
        "machine_tasks": 0,
        "legacy_or_unclassified": 0,
        "invalid_machine": 0,
        "by_type": {},
    }


def build_repository_projection(
    repository: str,
    issues: list[dict[str, Any]],
    *,
    observed_at: str,
    source_status: str = "OK",
    source_error: str | None = None,
) -> dict[str, Any]:
    """Build one pure read-only repository projection."""
    if not isinstance(repository, str) or not _REPOSITORY_RE.fullmatch(repository):
        raise RepositoryProjectionError(
            f"Invalid repository identity: {repository!r}"
        )
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise RepositoryProjectionError("observed_at is required")
    if source_status not in SOURCE_STATUSES:
        raise RepositoryProjectionError(
            f"Unsupported source_status: {source_status!r}"
        )
    if source_status == "OK" and source_error:
        raise RepositoryProjectionError(
            "source_error must be empty when source_status is OK"
        )
    if source_status != "OK" and not source_error:
        raise RepositoryProjectionError(
            "source_error is required when source_status is not OK"
        )

    base = {
        "schema_version": 1,
        "authority": "SHADOW_READ_ONLY",
        "repository": repository,
        "observed_at": observed_at,
        "source_status": source_status,
        "source_error": source_error,
    }
    if source_status != "OK":
        return {
            **base,
            "issues": [],
            "counts": _empty_counts(),
            "newest_open_issue_ref": None,
            "most_recently_active_issue_ref": None,
            "actionable_refs": [],
            "blocked_refs": [],
            "waiting_refs": [],
            "needs_human_refs": [],
        }

    classified = [classify_issue(issue) for issue in issues]
    counts_by_type: dict[str, int] = {}
    machine_tasks = 0
    legacy_or_unclassified = 0
    invalid_machine = 0
    actionable_refs: list[str] = []
    blocked_refs: list[str] = []
    waiting_refs: list[str] = []
    needs_human_refs: list[str] = []

    for item in classified:
        source = item["classification_source"]
        metadata = item.get("metadata")
        role = item.get("record_role")
        issue_ref = _issue_ref(
            repository,
            int(item.get("issue_number") or 0),
        )
        if source == "MACHINE" and role == "TASK":
            machine_tasks += 1
            if isinstance(metadata, dict):
                issue_type = metadata.get("type")
                if isinstance(issue_type, str):
                    counts_by_type[issue_type] = (
                        counts_by_type.get(issue_type, 0) + 1
                    )
                if issue_ref and item.get("actionable"):
                    actionable_refs.append(issue_ref)
                if issue_ref and (
                    metadata.get("work_status") == "BLOCKED"
                    or bool(metadata.get("blocked_by"))
                ):
                    blocked_refs.append(issue_ref)
                if issue_ref and metadata.get("external_wait") is True:
                    waiting_refs.append(issue_ref)
                if (
                    issue_ref
                    and metadata.get("requires_user_confirmation") is True
                ):
                    needs_human_refs.append(issue_ref)
        elif source in {"LEGACY_HINT", "UNCLASSIFIED"}:
            legacy_or_unclassified += 1
        elif source == "INVALID_MACHINE":
            invalid_machine += 1

    return {
        **base,
        "issues": classified,
        "counts": {
            "open_issues": sum(
                1 for item in classified if item.get("state") == "open"
            ),
            "machine_tasks": machine_tasks,
            "legacy_or_unclassified": legacy_or_unclassified,
            "invalid_machine": invalid_machine,
            "by_type": {
                key: counts_by_type[key]
                for key in sorted(counts_by_type)
            },
        },
        "newest_open_issue_ref": _latest_ref(
            repository,
            classified,
            "created_at",
        ),
        "most_recently_active_issue_ref": _latest_ref(
            repository,
            classified,
            "updated_at",
        ),
        "actionable_refs": sorted(actionable_refs),
        "blocked_refs": sorted(blocked_refs),
        "waiting_refs": sorted(waiting_refs),
        "needs_human_refs": sorted(needs_human_refs),
    }
