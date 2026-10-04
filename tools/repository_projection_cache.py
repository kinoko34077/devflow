from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any

from tools import maintenance_sync_check, marker_json


CACHE_MARKER_BEGIN = "<!-- DEVFLOW_REPOSITORY_PROJECTION_V1_BEGIN -->"
CACHE_MARKER_END = "<!-- DEVFLOW_REPOSITORY_PROJECTION_V1_END -->"
CACHE_SCHEMA_VERSION = "repository-projection-cache.v1"
CONTROL_TRUST_SOURCE = "DEVFLOW_SHARED_CONTROL_VERIFIER"
MAX_TASK_SUMMARIES = 20

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "repository",
        "generated_at",
        "generation_id",
        "source",
        "coverage",
        "counts",
        "type_counts",
        "tasks",
        "references",
        "control_trust",
    }
)
_SOURCE_FIELDS = frozenset(
    {"status", "freshness", "observed_at", "error", "digest"}
)
_COVERAGE_FIELDS = frozenset(
    {
        "status",
        "ambiguous",
        "active_work_evidence",
        "can_replace_manual_active_work",
    }
)
_COUNT_FIELDS = frozenset(
    {
        "open_issues",
        "machine_records",
        "machine_tasks",
        "legacy_hints",
        "unclassified",
        "invalid_metadata",
        "untrusted_metadata",
    }
)
_TYPE_COUNT_FIELDS = frozenset({"machine", "legacy_hint"})
_TASK_FIELDS = frozenset({"ready", "implementing"})
_REFERENCE_FIELDS = frozenset({"newest_open_issue", "recently_active_issue"})
_CONTROL_TRUST_FIELDS = frozenset(
    {"status", "freshness", "source", "observed_at", "detail"}
)


class RepositoryProjectionCacheError(ValueError):
    pass


@dataclass(frozen=True)
class CachedRepositoryProjection:
    payload: dict[str, Any]


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RepositoryProjectionCacheError(f"{field} must be an object")
    return dict(value)


def _require_exact_fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    field: str,
) -> None:
    keys = set(value)
    missing = sorted(allowed - keys)
    unknown = sorted(keys - allowed)
    if missing:
        raise RepositoryProjectionCacheError(
            f"{field} missing fields: " + ", ".join(missing)
        )
    if unknown:
        raise RepositoryProjectionCacheError(
            f"{field} has unknown fields: " + ", ".join(unknown)
        )


def _require_repository(value: object, field: str = "repository") -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value.strip()) is None:
        raise RepositoryProjectionCacheError(f"{field} must be owner/repository")
    return value.strip()


def _require_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RepositoryProjectionCacheError(f"{field} must be an RFC-3339 timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RepositoryProjectionCacheError(
            f"{field} must be an RFC-3339 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RepositoryProjectionCacheError(
            f"{field} must include an RFC-3339 timezone offset"
        )
    return text


def _require_nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RepositoryProjectionCacheError(f"{field} must be a non-negative integer")
    return value


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise RepositoryProjectionCacheError(f"{field} must be boolean")
    return value


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RepositoryProjectionCacheError(
            f"{field} must be a canonical sha256 identity"
        )
    return value


def _require_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RepositoryProjectionCacheError(
            f"{field} must be a non-empty string or null"
        )
    return value.strip()


def _compact_issue_ref(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    item = _require_mapping(value, "issue reference")
    number = _require_nonnegative_int(item.get("issue_number"), "issue_number")
    if number < 1:
        raise RepositoryProjectionCacheError("issue_number must be >= 1")
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RepositoryProjectionCacheError("issue title must be a non-empty string")
    url = item.get("url")
    if url is not None and (not isinstance(url, str) or not url.strip()):
        raise RepositoryProjectionCacheError("issue url must be a non-empty string or null")
    return {
        "issue_number": number,
        "title": title.strip(),
        "url": url.strip() if isinstance(url, str) else None,
        "source_kind": _require_optional_string(
            item.get("source_kind"),
            "issue source_kind",
        ),
        "record_role": _require_optional_string(
            item.get("record_role"),
            "issue record_role",
        ),
        "type": _require_optional_string(item.get("type"), "issue type"),
        "work_status": _require_optional_string(
            item.get("work_status"),
            "issue work_status",
        ),
        "attention_disposition": _require_optional_string(
            item.get("attention_disposition"),
            "issue attention_disposition",
        ),
    }


def _compact_task_list(value: object, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RepositoryProjectionCacheError(f"{field} must be an array")
    compact: list[dict[str, Any]] = []
    for item in value[:MAX_TASK_SUMMARIES]:
        ref = _compact_issue_ref(item)
        if ref is None:
            raise RepositoryProjectionCacheError(f"{field} entries must be issue objects")
        compact.append(ref)
    return compact


def _validate_type_counts(value: object, field: str) -> dict[str, int]:
    mapping = _require_mapping(value, field)
    result: dict[str, int] = {}
    for key, count in mapping.items():
        if not isinstance(key, str) or not key:
            raise RepositoryProjectionCacheError(f"{field} keys must be non-empty strings")
        result[key] = _require_nonnegative_int(count, f"{field}.{key}")
    return dict(sorted(result.items()))


def _validate_control_trust(value: object) -> dict[str, Any]:
    trust = _require_mapping(value, "control_trust")
    _require_exact_fields(trust, _CONTROL_TRUST_FIELDS, "control_trust")
    status = trust["status"]
    if status not in {"VERIFIED", "UNVERIFIED", "UNKNOWN"}:
        raise RepositoryProjectionCacheError(
            f"invalid control_trust.status: {status!r}"
        )
    freshness = trust["freshness"]
    if freshness not in {"CURRENT", "STALE", "UNKNOWN"}:
        raise RepositoryProjectionCacheError(
            f"invalid control_trust.freshness: {freshness!r}"
        )
    if trust["source"] != CONTROL_TRUST_SOURCE:
        raise RepositoryProjectionCacheError(
            "control_trust.source is unsupported"
        )
    return {
        "status": status,
        "freshness": freshness,
        "source": CONTROL_TRUST_SOURCE,
        "observed_at": _require_timestamp(
            trust["observed_at"],
            "control_trust.observed_at",
        ),
        "detail": _require_optional_string(
            trust["detail"],
            "control_trust.detail",
        ),
    }


def _coverage_from_live(
    live_projection: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    open_issues = _require_nonnegative_int(
        live_projection.get("open_issue_count"),
        "open_issue_count",
    )
    machine_tasks = _require_nonnegative_int(
        live_projection.get("machine_task_count"),
        "machine_task_count",
    )
    legacy = _require_nonnegative_int(
        live_projection.get("legacy_hint_count"),
        "legacy_hint_count",
    )
    unclassified = _require_nonnegative_int(
        live_projection.get("unclassified_count"),
        "unclassified_count",
    )
    invalid = _require_nonnegative_int(
        live_projection.get("invalid_metadata_count"),
        "invalid_metadata_count",
    )
    untrusted = _require_nonnegative_int(
        live_projection.get("untrusted_metadata_count"),
        "untrusted_metadata_count",
    )
    non_machine = legacy + unclassified + invalid + untrusted
    if non_machine > open_issues:
        raise RepositoryProjectionCacheError(
            "repository projection source-kind counts exceed open_issue_count"
        )
    machine_records = open_issues - non_machine
    if machine_tasks > machine_records:
        raise RepositoryProjectionCacheError(
            "machine_task_count exceeds machine record coverage"
        )

    source_status = live_projection.get("source_status")
    source_freshness = live_projection.get("source_freshness")

    if source_status == "UNAVAILABLE":
        coverage_status = "UNAVAILABLE"
        ambiguous = True
        evidence = "SOURCE_UNAVAILABLE"
    elif source_freshness == "STALE":
        coverage_status = "STALE"
        ambiguous = True
        evidence = "SOURCE_STALE"
    elif source_freshness != "CURRENT":
        coverage_status = "UNKNOWN"
        ambiguous = True
        evidence = "SOURCE_FRESHNESS_UNKNOWN"
    elif non_machine:
        coverage_status = "INCOMPLETE"
        ambiguous = True
        evidence = (
            "PARTIAL_MACHINE_TASK_EVIDENCE"
            if machine_tasks
            else "NO_MACHINE_TASK_EVIDENCE"
        )
    else:
        coverage_status = "COMPLETE"
        ambiguous = False
        evidence = (
            "MACHINE_TASK_EVIDENCE"
            if machine_tasks
            else "NO_MACHINE_TASKS_UNDER_COMPLETE_COVERAGE"
        )

    coverage = {
        "status": coverage_status,
        "ambiguous": ambiguous,
        "active_work_evidence": evidence,
        # M2 is transport/display evidence only. M3 owns authority removal.
        "can_replace_manual_active_work": False,
    }
    counts = {
        "open_issues": open_issues,
        "machine_records": machine_records,
        "machine_tasks": machine_tasks,
        "legacy_hints": legacy,
        "unclassified": unclassified,
        "invalid_metadata": invalid,
        "untrusted_metadata": untrusted,
    }
    return coverage, counts


def _source_identity_material(live_projection: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(live_projection)
    # Observation time/freshness describe when/how the same source snapshot was
    # seen. They belong to cache generation/freshness, not source identity.
    value.pop("observed_at", None)
    value.pop("source_freshness", None)
    return value


def _generation_material(payload: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(payload)
    value.pop("generation_id", None)
    return value


def recompute_generation_id(payload: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(payload)
    value["generation_id"] = _canonical_digest(_generation_material(value))
    return value


def build_cached_projection(
    repository: str,
    live_projection: dict[str, Any],
    *,
    generated_at: str,
    control_trust: dict[str, Any],
) -> dict[str, Any]:
    repository = _require_repository(repository)
    live = _require_mapping(live_projection, "live_projection")
    if _require_repository(live.get("repository"), "live_projection.repository") != repository:
        raise RepositoryProjectionCacheError("live projection repository identity mismatch")

    source_status = live.get("source_status")
    if source_status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise RepositoryProjectionCacheError(
            f"invalid live projection source_status: {source_status!r}"
        )
    source_freshness = live.get("source_freshness")
    if source_freshness not in {"CURRENT", "STALE", "UNKNOWN"}:
        raise RepositoryProjectionCacheError(
            f"invalid live projection source_freshness: {source_freshness!r}"
        )
    if source_status == "UNAVAILABLE" and source_freshness == "CURRENT":
        raise RepositoryProjectionCacheError(
            "unavailable source cannot be CURRENT"
        )

    observed_at = _require_timestamp(
        live.get("observed_at"),
        "live_projection.observed_at",
    )
    generated_at = _require_timestamp(generated_at, "generated_at")
    coverage, counts = _coverage_from_live(live)
    trust = _validate_control_trust(control_trust)

    source_digest = _canonical_digest(_source_identity_material(live))
    payload: dict[str, Any] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "repository": repository,
        "generated_at": generated_at,
        "generation_id": "",
        "source": {
            "status": source_status,
            "freshness": source_freshness,
            "observed_at": observed_at,
            "error": _require_optional_string(
                live.get("source_error"),
                "live_projection.source_error",
            ),
            "digest": source_digest,
        },
        "coverage": coverage,
        "counts": counts,
        "type_counts": {
            "machine": _validate_type_counts(
                live.get("machine_type_counts", {}),
                "machine_type_counts",
            ),
            "legacy_hint": _validate_type_counts(
                live.get("legacy_hint_type_counts", {}),
                "legacy_hint_type_counts",
            ),
        },
        "tasks": {
            "ready": _compact_task_list(
                live.get("ready_tasks", []),
                "ready_tasks",
            ),
            "implementing": _compact_task_list(
                live.get("implementing_tasks", []),
                "implementing_tasks",
            ),
        },
        "references": {
            "newest_open_issue": _compact_issue_ref(
                live.get("newest_open_issue")
            ),
            "recently_active_issue": _compact_issue_ref(
                live.get("recently_active_issue")
            ),
        },
        "control_trust": trust,
    }
    return recompute_generation_id(payload)


def _validate_cached_payload(
    payload: dict[str, Any],
    repository: str,
) -> dict[str, Any]:
    _require_exact_fields(payload, _TOP_LEVEL_FIELDS, "repository projection cache")
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise RepositoryProjectionCacheError(
            f"unsupported schema_version: {payload.get('schema_version')!r}"
        )
    recorded_repository = _require_repository(
        payload.get("repository"),
        "cache repository",
    )
    if recorded_repository != repository:
        raise RepositoryProjectionCacheError(
            "repository identity mismatch"
        )
    _require_timestamp(payload.get("generated_at"), "generated_at")
    generation_id = _require_sha256(
        payload.get("generation_id"),
        "generation_id",
    )

    source = _require_mapping(payload.get("source"), "source")
    _require_exact_fields(source, _SOURCE_FIELDS, "source")
    if source.get("status") not in {"AVAILABLE", "UNAVAILABLE"}:
        raise RepositoryProjectionCacheError(
            f"invalid source.status: {source.get('status')!r}"
        )
    if source.get("freshness") not in {"CURRENT", "STALE", "UNKNOWN"}:
        raise RepositoryProjectionCacheError(
            f"invalid source.freshness: {source.get('freshness')!r}"
        )
    _require_timestamp(source.get("observed_at"), "source.observed_at")
    _require_optional_string(source.get("error"), "source.error")
    _require_sha256(source.get("digest"), "source.digest")

    coverage = _require_mapping(payload.get("coverage"), "coverage")
    _require_exact_fields(coverage, _COVERAGE_FIELDS, "coverage")
    if coverage.get("status") not in {
        "COMPLETE",
        "INCOMPLETE",
        "STALE",
        "UNKNOWN",
        "UNAVAILABLE",
    }:
        raise RepositoryProjectionCacheError(
            f"invalid coverage.status: {coverage.get('status')!r}"
        )
    _require_bool(coverage.get("ambiguous"), "coverage.ambiguous")
    evidence = coverage.get("active_work_evidence")
    if evidence not in {
        "MACHINE_TASK_EVIDENCE",
        "NO_MACHINE_TASKS_UNDER_COMPLETE_COVERAGE",
        "PARTIAL_MACHINE_TASK_EVIDENCE",
        "NO_MACHINE_TASK_EVIDENCE",
        "SOURCE_STALE",
        "SOURCE_FRESHNESS_UNKNOWN",
        "SOURCE_UNAVAILABLE",
    }:
        raise RepositoryProjectionCacheError(
            f"invalid coverage.active_work_evidence: {evidence!r}"
        )
    if _require_bool(
        coverage.get("can_replace_manual_active_work"),
        "coverage.can_replace_manual_active_work",
    ):
        raise RepositoryProjectionCacheError(
            "M2 cache cannot replace manual Active Work authority"
        )

    counts = _require_mapping(payload.get("counts"), "counts")
    _require_exact_fields(counts, _COUNT_FIELDS, "counts")
    normalized_counts = {
        key: _require_nonnegative_int(value, f"counts.{key}")
        for key, value in counts.items()
    }
    if normalized_counts["machine_tasks"] > normalized_counts["machine_records"]:
        raise RepositoryProjectionCacheError(
            "counts.machine_tasks exceeds machine_records"
        )
    if (
        normalized_counts["machine_records"]
        + normalized_counts["legacy_hints"]
        + normalized_counts["unclassified"]
        + normalized_counts["invalid_metadata"]
        + normalized_counts["untrusted_metadata"]
        != normalized_counts["open_issues"]
    ):
        raise RepositoryProjectionCacheError(
            "cache source-kind counts do not sum to open_issues"
        )

    type_counts = _require_mapping(payload.get("type_counts"), "type_counts")
    _require_exact_fields(type_counts, _TYPE_COUNT_FIELDS, "type_counts")
    _validate_type_counts(type_counts["machine"], "type_counts.machine")
    _validate_type_counts(type_counts["legacy_hint"], "type_counts.legacy_hint")

    tasks = _require_mapping(payload.get("tasks"), "tasks")
    _require_exact_fields(tasks, _TASK_FIELDS, "tasks")
    _compact_task_list(tasks["ready"], "tasks.ready")
    _compact_task_list(tasks["implementing"], "tasks.implementing")

    references = _require_mapping(payload.get("references"), "references")
    _require_exact_fields(references, _REFERENCE_FIELDS, "references")
    _compact_issue_ref(references["newest_open_issue"])
    _compact_issue_ref(references["recently_active_issue"])

    _validate_control_trust(payload.get("control_trust"))

    expected_generation_id = _canonical_digest(_generation_material(payload))
    if generation_id != expected_generation_id:
        raise RepositoryProjectionCacheError(
            "generation_id does not match cached projection payload"
        )
    return payload


def render_cached_projection(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return f"{CACHE_MARKER_BEGIN}\n{encoded}\n{CACHE_MARKER_END}"


def parse_cached_projection(
    body: str,
    repository: str,
) -> CachedRepositoryProjection | None:
    repository = _require_repository(repository)
    try:
        payload = marker_json.parse_json_object_block(
            body,
            CACHE_MARKER_BEGIN,
            CACHE_MARKER_END,
            label="repository projection cache",
        )
    except marker_json.MarkerJSONError as exc:
        raise RepositoryProjectionCacheError(str(exc)) from exc
    if payload is None:
        return None
    validated = _validate_cached_payload(payload, repository)
    return CachedRepositoryProjection(payload=copy.deepcopy(validated))


def replace_cached_projection(
    body: str,
    repository: str,
    payload: dict[str, Any],
    *,
    expected_body_sha256: str,
) -> str:
    repository = _require_repository(repository)
    if not isinstance(body, str):
        raise RepositoryProjectionCacheError("Control body must be a string")
    actual_body_sha256 = maintenance_sync_check.canonical_body_sha256(body)
    if actual_body_sha256 != expected_body_sha256:
        raise RepositoryProjectionCacheError(
            "Control body digest drift detected before cache write"
        )

    validated = _validate_cached_payload(
        copy.deepcopy(payload),
        repository,
    )
    try:
        bounds = marker_json.marker_bounds(
            body,
            CACHE_MARKER_BEGIN,
            CACHE_MARKER_END,
            label="repository projection cache",
        )
    except marker_json.MarkerJSONError as exc:
        raise RepositoryProjectionCacheError(str(exc)) from exc

    block = render_cached_projection(validated)
    if bounds is None:
        prefix = body.rstrip()
        return prefix + ("\n\n" if prefix else "") + block

    # Existing machine state must itself be parseable before replacement.
    parse_cached_projection(body, repository)
    begin, end = bounds
    prefix = body[:begin]
    suffix = body[end + len(CACHE_MARKER_END):]
    return prefix + block + suffix
