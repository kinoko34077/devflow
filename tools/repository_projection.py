from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

try:
    from . import development_reconciler, github_issue_trust, marker_json, workflow_contract
except ImportError:  # direct script / top-level fallback
    import development_reconciler
    import github_issue_trust
    import marker_json
    import workflow_contract


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
    attention_disposition: str | None = None

    @property
    def is_task(self) -> bool:
        return self.metadata is not None and self.metadata.is_task


_LEADING_TAGS = re.compile(r"^((?:\[[^\]\r\n]+\])+)")


def _issue_only_attention(metadata: IssueMetadata) -> str | None:
    if metadata.requires_user_confirmation:
        disposition = "NEEDS_HUMAN"
    elif metadata.external_wait:
        disposition = "WAIT_EXTERNAL"
    elif not metadata.scope_ready:
        disposition = "NEEDS_EVIDENCE"
    else:
        return None
    if disposition not in development_reconciler.DISPOSITIONS:
        raise ProjectionContractError(
            f"unknown reconciliation disposition: {disposition}"
        )
    return disposition


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

    body = str(issue.get("body") or "")
    has_metadata_marker = (
        ISSUE_METADATA_MARKER_BEGIN in body
        or ISSUE_METADATA_MARKER_END in body
    )
    if has_metadata_marker and not github_issue_trust.is_trusted_issue_author(issue):
        return IssueRecord(
            number=number,
            title=title,
            state=state,
            created_at=created_at,
            updated_at=updated_at,
            html_url=html_url,
            source_kind="UNTRUSTED_METADATA",
            record_role=None,
            type=None,
            work_status=None,
            metadata=None,
            metadata_error="repository Issue metadata author is untrusted",
            attention_disposition="NEEDS_EVIDENCE",
        )

    try:
        metadata = parse_issue_metadata(body)
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
            attention_disposition="NEEDS_EVIDENCE",
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
            attention_disposition=_issue_only_attention(metadata),
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



@dataclass(frozen=True)
class RepositoryProjection:
    repository: str
    observed_at: str
    source_status: str
    source_freshness: str
    source_error: str | None
    open_issue_count: int
    machine_task_count: int
    legacy_hint_count: int
    unclassified_count: int
    invalid_metadata_count: int
    untrusted_metadata_count: int
    machine_type_counts: dict[str, int]
    legacy_hint_type_counts: dict[str, int]
    task_records: tuple[IssueRecord, ...]
    ready_tasks: tuple[IssueRecord, ...]
    implementing_tasks: tuple[IssueRecord, ...]
    newest_open_issue: IssueRecord | None
    recently_active_issue: IssueRecord | None
    records: tuple[IssueRecord, ...]


def _count_types(records: list[IssueRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if record.type is None:
            continue
        counts[record.type] = counts.get(record.type, 0) + 1
    return dict(sorted(counts.items()))


def _latest_record(
    records: list[IssueRecord],
    field: str,
) -> IssueRecord | None:
    if not records:
        return None
    return max(
        records,
        key=lambda item: (getattr(item, field), item.number),
    )


def build_repository_projection(
    repository: str,
    issues: list[dict[str, Any]],
    *,
    observed_at: str,
    source_status: str = "AVAILABLE",
    source_error: str | None = None,
) -> RepositoryProjection:
    if not isinstance(repository, str) or "/" not in repository or not repository.strip():
        raise ProjectionContractError("repository must be owner/repository")
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise ProjectionContractError("observed_at must be a non-empty string")
    if source_status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise ProjectionContractError(f"invalid source_status: {source_status!r}")
    if source_error is not None and (
        not isinstance(source_error, str) or not source_error.strip()
    ):
        raise ProjectionContractError("source_error must be a non-empty string or null")

    freshness = "CURRENT" if source_status == "AVAILABLE" else "UNKNOWN"
    if source_status == "UNAVAILABLE":
        return RepositoryProjection(
            repository=repository.strip(),
            observed_at=observed_at.strip(),
            source_status=source_status,
            source_freshness=freshness,
            source_error=source_error,
            open_issue_count=0,
            machine_task_count=0,
            legacy_hint_count=0,
            unclassified_count=0,
            invalid_metadata_count=0,
            untrusted_metadata_count=0,
            machine_type_counts={},
            legacy_hint_type_counts={},
            task_records=(),
            ready_tasks=(),
            implementing_tasks=(),
            newest_open_issue=None,
            recently_active_issue=None,
            records=(),
        )

    records = [classify_issue(issue) for issue in issues]
    open_records = [record for record in records if record.state == "open"]
    open_records.sort(key=lambda item: item.number)

    machine_records = [
        record for record in open_records if record.source_kind == "MACHINE"
    ]
    task_records = [
        record for record in machine_records if record.is_task
    ]
    legacy_records = [
        record for record in open_records if record.source_kind == "LEGACY_HINT"
    ]

    return RepositoryProjection(
        repository=repository.strip(),
        observed_at=observed_at.strip(),
        source_status=source_status,
        source_freshness=freshness,
        source_error=source_error,
        open_issue_count=len(open_records),
        machine_task_count=len(task_records),
        legacy_hint_count=len(legacy_records),
        unclassified_count=sum(
            1 for record in open_records if record.source_kind == "UNCLASSIFIED"
        ),
        invalid_metadata_count=sum(
            1 for record in open_records if record.source_kind == "INVALID_METADATA"
        ),
        untrusted_metadata_count=sum(
            1 for record in open_records if record.source_kind == "UNTRUSTED_METADATA"
        ),
        machine_type_counts=_count_types(machine_records),
        legacy_hint_type_counts=_count_types(legacy_records),
        task_records=tuple(task_records),
        ready_tasks=tuple(
            record
            for record in task_records
            if record.work_status == "READY_FOR_IMPLEMENTATION"
        ),
        implementing_tasks=tuple(
            record
            for record in task_records
            if record.work_status == "IMPLEMENTING"
        ),
        newest_open_issue=_latest_record(open_records, "created_at"),
        recently_active_issue=_latest_record(open_records, "updated_at"),
        records=tuple(open_records),
    )
