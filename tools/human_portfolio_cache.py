from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Any

from tools import marker_json


CACHE_MARKER_BEGIN = "<!-- DEVFLOW_HUMAN_PORTFOLIO_V1_BEGIN -->"
CACHE_MARKER_END = "<!-- DEVFLOW_HUMAN_PORTFOLIO_V1_END -->"
CACHE_SCHEMA_VERSION = "human-portfolio-cache.v1"
LIVE_SCHEMA_VERSION = "human-portfolio-read.v1"
CACHE_VALIDITY_SECONDS = 24 * 60 * 60
MAX_ENTRIES = 200
MAX_TASK_ERRORS = 100

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TASK_REF = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)$")
_ENTRY_REF = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)$"
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "repository",
        "observed_at",
        "generated_at",
        "valid_until",
        "generation_id",
        "complete",
        "repository_source",
        "reconciliation_source",
        "entries",
    }
)
_REPOSITORY_SOURCE_FIELDS = frozenset({"status", "freshness", "error"})
_RECONCILIATION_SOURCE_FIELDS = frozenset(
    {
        "status",
        "trust",
        "control_issue_number",
        "control_url",
        "error",
        "task_errors",
    }
)
_TASK_ERROR_FIELDS = frozenset({"task_ref", "error"})
_ENTRY_FIELDS = frozenset(
    {
        "repository",
        "task_ref",
        "entry_ref",
        "disposition",
        "role",
        "source_kind",
        "observed_at",
        "work_status",
        "publication_id",
        "evidence_freshness",
        "evidence_trust",
    }
)
_DISPOSITIONS = frozenset(
    {
        "READY",
        "IMPLEMENTING",
        "NEEDS_HUMAN",
        "WAIT_EXTERNAL",
        "NEEDS_EVIDENCE",
        "NEEDS_REVIEWER",
        "NEEDS_RECOVERY",
    }
)
_SOURCE_KINDS = frozenset({"REPOSITORY_PROJECTION", "RECONCILIATION"})
_EVIDENCE_FRESHNESS = frozenset({"CURRENT", "STALE", "UNKNOWN"})
_EVIDENCE_TRUST = frozenset({"VERIFIED", "UNTRUSTED", "UNKNOWN"})


class HumanPortfolioCacheError(ValueError):
    pass


@dataclass(frozen=True)
class CachedHumanPortfolio:
    payload: dict[str, Any]


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _generation_material(payload: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(payload)
    value.pop("generation_id", None)
    return value


def recompute_generation_id(payload: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(payload)
    value["generation_id"] = _canonical_digest(_generation_material(value))
    return value


def _require_exact_fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    field: str,
) -> None:
    missing = sorted(allowed - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise HumanPortfolioCacheError(
            f"{field} missing fields: " + ", ".join(missing)
        )
    if unknown:
        raise HumanPortfolioCacheError(
            f"{field} has unknown fields: " + ", ".join(unknown)
        )


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HumanPortfolioCacheError(f"{field} must be an object")
    return dict(value)


def _require_repository(value: object, field: str = "repository") -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value.strip()) is None:
        raise HumanPortfolioCacheError(f"{field} must be owner/repository")
    return value.strip()


def _require_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HumanPortfolioCacheError(
            f"{field} must be an RFC-3339 timestamp"
        )
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HumanPortfolioCacheError(
            f"{field} must be an RFC-3339 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HumanPortfolioCacheError(
            f"{field} must include an RFC-3339 timezone offset"
        )
    return text


def _timestamp_value(value: object, field: str) -> datetime:
    return datetime.fromisoformat(
        _require_timestamp(value, field).replace("Z", "+00:00")
    )


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HumanPortfolioCacheError(f"{field} must be boolean")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HumanPortfolioCacheError(f"{field} must be a positive integer")
    return value


def _require_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HumanPortfolioCacheError(
            f"{field} must be a non-empty string or null"
        )
    return value.strip()


def _validate_repository_source(value: object) -> dict[str, Any]:
    source = _require_mapping(value, "repository_source")
    _require_exact_fields(
        source,
        _REPOSITORY_SOURCE_FIELDS,
        "repository_source",
    )
    status = source.get("status")
    if status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise HumanPortfolioCacheError(
            f"invalid repository_source.status: {status!r}"
        )
    freshness = source.get("freshness")
    if freshness not in {"CURRENT", "STALE", "UNKNOWN"}:
        raise HumanPortfolioCacheError(
            f"invalid repository_source.freshness: {freshness!r}"
        )
    if status == "UNAVAILABLE" and freshness == "CURRENT":
        raise HumanPortfolioCacheError(
            "unavailable repository source cannot be CURRENT"
        )
    return {
        "status": status,
        "freshness": freshness,
        "error": _require_optional_string(
            source.get("error"),
            "repository_source.error",
        ),
    }


def _validate_task_error(value: object, repository: str) -> dict[str, str]:
    item = _require_mapping(value, "reconciliation task error")
    _require_exact_fields(
        item,
        _TASK_ERROR_FIELDS,
        "reconciliation task error",
    )
    task_ref = item.get("task_ref")
    if not isinstance(task_ref, str):
        raise HumanPortfolioCacheError("task error task_ref must be a string")
    match = _TASK_REF.fullmatch(task_ref)
    if match is None or match.group(1) != repository:
        raise HumanPortfolioCacheError(
            "task error task_ref must belong to cached repository"
        )
    error = item.get("error")
    if not isinstance(error, str) or not error.strip():
        raise HumanPortfolioCacheError(
            "task error error must be a non-empty string"
        )
    return {"task_ref": task_ref, "error": error.strip()}


def _validate_reconciliation_source(
    value: object,
    repository: str,
) -> dict[str, Any]:
    source = _require_mapping(value, "reconciliation_source")
    _require_exact_fields(
        source,
        _RECONCILIATION_SOURCE_FIELDS,
        "reconciliation_source",
    )
    status = source.get("status")
    if status not in {"AVAILABLE", "INVALID"}:
        raise HumanPortfolioCacheError(
            f"invalid reconciliation_source.status: {status!r}"
        )
    trust = source.get("trust")
    if trust not in {"VERIFIED", "UNKNOWN"}:
        raise HumanPortfolioCacheError(
            f"invalid reconciliation_source.trust: {trust!r}"
        )
    if status == "AVAILABLE" and trust != "VERIFIED":
        raise HumanPortfolioCacheError(
            "available reconciliation source must be VERIFIED"
        )
    if status == "INVALID" and trust == "VERIFIED":
        raise HumanPortfolioCacheError(
            "invalid reconciliation source cannot be VERIFIED"
        )
    control_number = _require_positive_int(
        source.get("control_issue_number"),
        "reconciliation_source.control_issue_number",
    )
    control_url = source.get("control_url")
    expected_url = (
        "https://github.com/kinoko34077/devflow/issues/"
        + str(control_number)
    )
    if control_url != expected_url:
        raise HumanPortfolioCacheError(
            "reconciliation_source.control_url does not match Control issue"
        )
    task_errors = source.get("task_errors")
    if not isinstance(task_errors, list):
        raise HumanPortfolioCacheError(
            "reconciliation_source.task_errors must be an array"
        )
    if len(task_errors) > MAX_TASK_ERRORS:
        raise HumanPortfolioCacheError(
            "reconciliation_source.task_errors exceeds bounded maximum"
        )
    validated_errors = [
        _validate_task_error(item, repository)
        for item in task_errors
    ]
    return {
        "status": status,
        "trust": trust,
        "control_issue_number": control_number,
        "control_url": control_url,
        "error": _require_optional_string(
            source.get("error"),
            "reconciliation_source.error",
        ),
        "task_errors": validated_errors,
    }


def _validate_entry(value: object, repository: str) -> dict[str, Any]:
    entry = _require_mapping(value, "human portfolio entry")
    _require_exact_fields(entry, _ENTRY_FIELDS, "human portfolio entry")
    entry_repository = _require_repository(
        entry.get("repository"),
        "human portfolio entry repository",
    )
    if entry_repository != repository:
        raise HumanPortfolioCacheError(
            "human portfolio entry repository identity mismatch"
        )
    task_ref = entry.get("task_ref")
    if not isinstance(task_ref, str):
        raise HumanPortfolioCacheError(
            "human portfolio entry task_ref must be a string"
        )
    match = _TASK_REF.fullmatch(task_ref)
    if match is None or match.group(1) != repository:
        raise HumanPortfolioCacheError(
            "human portfolio entry task_ref must belong to cached repository"
        )
    entry_ref = entry.get("entry_ref")
    if entry_ref is not None:
        if not isinstance(entry_ref, str):
            raise HumanPortfolioCacheError(
                "human portfolio entry entry_ref must be a canonical GitHub Issue URL or null"
            )
        entry_match = _ENTRY_REF.fullmatch(entry_ref)
        if entry_match is None:
            raise HumanPortfolioCacheError(
                "human portfolio entry entry_ref must be a canonical GitHub Issue URL or null"
            )
        entry_task_ref = (
            f"{entry_match.group(1)}/{entry_match.group(2)}#{entry_match.group(3)}"
        )
        if entry_task_ref != task_ref:
            raise HumanPortfolioCacheError(
                "human portfolio entry entry_ref must identify the exact owning task"
            )
    disposition = entry.get("disposition")
    if disposition not in _DISPOSITIONS:
        raise HumanPortfolioCacheError(
            f"unsupported human portfolio disposition: {disposition!r}"
        )
    role = entry.get("role")
    if not isinstance(role, str) or not role.strip():
        raise HumanPortfolioCacheError(
            "human portfolio entry role must be non-empty"
        )
    source_kind = entry.get("source_kind")
    if source_kind not in _SOURCE_KINDS:
        raise HumanPortfolioCacheError(
            f"unsupported human portfolio source_kind: {source_kind!r}"
        )
    evidence_freshness = entry.get("evidence_freshness")
    if evidence_freshness not in _EVIDENCE_FRESHNESS:
        raise HumanPortfolioCacheError(
            "unsupported human portfolio evidence_freshness"
        )
    evidence_trust = entry.get("evidence_trust")
    if evidence_trust not in _EVIDENCE_TRUST:
        raise HumanPortfolioCacheError(
            "unsupported human portfolio evidence_trust"
        )
    publication_id = _require_optional_string(
        entry.get("publication_id"),
        "human portfolio entry publication_id",
    )
    if source_kind == "RECONCILIATION" and publication_id is None:
        raise HumanPortfolioCacheError(
            "reconciliation entry requires publication_id"
        )
    if (
        source_kind == "RECONCILIATION"
        and publication_id is not None
        and _SHA256.fullmatch(publication_id) is None
    ):
        raise HumanPortfolioCacheError(
            "reconciliation publication_id must be a canonical sha256 identity"
        )
    if source_kind == "REPOSITORY_PROJECTION" and publication_id is not None:
        raise HumanPortfolioCacheError(
            "repository projection entry cannot carry publication_id"
        )
    return {
        "repository": entry_repository,
        "task_ref": task_ref,
        "entry_ref": entry_ref,
        "disposition": disposition,
        "role": role.strip(),
        "source_kind": source_kind,
        "observed_at": _require_timestamp(
            entry.get("observed_at"),
            "human portfolio entry observed_at",
        ),
        "work_status": _require_optional_string(
            entry.get("work_status"),
            "human portfolio entry work_status",
        ),
        "publication_id": publication_id,
        "evidence_freshness": evidence_freshness,
        "evidence_trust": evidence_trust,
    }


def _validate_cached_payload(
    payload: dict[str, Any],
    repository: str,
) -> dict[str, Any]:
    _require_exact_fields(payload, _TOP_LEVEL_FIELDS, "human portfolio cache")
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise HumanPortfolioCacheError(
            f"unsupported schema_version: {payload.get('schema_version')!r}"
        )
    recorded_repository = _require_repository(
        payload.get("repository"),
        "cache repository",
    )
    if recorded_repository != repository:
        raise HumanPortfolioCacheError("repository identity mismatch")
    observed_dt = _timestamp_value(
        payload.get("observed_at"),
        "observed_at",
    )
    generated_dt = _timestamp_value(
        payload.get("generated_at"),
        "generated_at",
    )
    if generated_dt < observed_dt:
        raise HumanPortfolioCacheError(
            "generated_at must not precede observed_at"
        )
    valid_until_dt = _timestamp_value(
        payload.get("valid_until"),
        "valid_until",
    )
    if valid_until_dt - generated_dt != timedelta(
        seconds=CACHE_VALIDITY_SECONDS
    ):
        raise HumanPortfolioCacheError(
            "valid_until must equal generated_at plus the canonical cache validity window"
        )
    generation_id = payload.get("generation_id")
    if not isinstance(generation_id, str) or _SHA256.fullmatch(generation_id) is None:
        raise HumanPortfolioCacheError(
            "generation_id must be a canonical sha256 identity"
        )
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise HumanPortfolioCacheError("entries must be an array")
    if len(entries) > MAX_ENTRIES:
        raise HumanPortfolioCacheError(
            "entries exceeds bounded maximum"
        )
    validated = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "repository": repository,
        "observed_at": _require_timestamp(
            payload.get("observed_at"),
            "observed_at",
        ),
        "generated_at": _require_timestamp(
            payload.get("generated_at"),
            "generated_at",
        ),
        "valid_until": _require_timestamp(
            payload.get("valid_until"),
            "valid_until",
        ),
        "generation_id": generation_id,
        "complete": _require_bool(payload.get("complete"), "complete"),
        "repository_source": _validate_repository_source(
            payload.get("repository_source")
        ),
        "reconciliation_source": _validate_reconciliation_source(
            payload.get("reconciliation_source"),
            repository,
        ),
        "entries": [
            _validate_entry(item, repository)
            for item in entries
        ],
    }
    expected_generation = _canonical_digest(
        _generation_material(validated)
    )
    if generation_id != expected_generation:
        raise HumanPortfolioCacheError(
            "generation_id does not match cached Human Portfolio payload"
        )
    return validated


def build_cached_human_portfolio(
    repository: str,
    live_read: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    repository = _require_repository(repository)
    live = _require_mapping(live_read, "live human portfolio")
    if live.get("schema_version") != LIVE_SCHEMA_VERSION:
        raise HumanPortfolioCacheError(
            "live Human Portfolio schema_version is unsupported"
        )
    if _require_repository(
        live.get("repository"),
        "live human portfolio repository",
    ) != repository:
        raise HumanPortfolioCacheError(
            "live Human Portfolio repository identity mismatch"
        )
    observed_at = _require_timestamp(
        live.get("observed_at"),
        "live human portfolio observed_at",
    )
    generated_at = _require_timestamp(generated_at, "generated_at")
    observed_dt = _timestamp_value(observed_at, "observed_at")
    generated_dt = _timestamp_value(generated_at, "generated_at")
    if generated_dt < observed_dt:
        generated_dt = observed_dt
        generated_at = _format_timestamp(generated_dt)
    entries = live.get("entries")
    if not isinstance(entries, list):
        raise HumanPortfolioCacheError(
            "live Human Portfolio entries must be an array"
        )
    if len(entries) > MAX_ENTRIES:
        raise HumanPortfolioCacheError(
            "live Human Portfolio entries exceeds bounded maximum"
        )
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "repository": repository,
        "observed_at": observed_at,
        "generated_at": generated_at,
        "valid_until": _format_timestamp(
            generated_dt + timedelta(seconds=CACHE_VALIDITY_SECONDS)
        ),
        "generation_id": "",
        "complete": _require_bool(
            live.get("complete"),
            "live human portfolio complete",
        ),
        "repository_source": _validate_repository_source(
            live.get("repository_source")
        ),
        "reconciliation_source": _validate_reconciliation_source(
            live.get("reconciliation_source"),
            repository,
        ),
        "entries": [
            _validate_entry(item, repository)
            for item in entries
        ],
    }
    return recompute_generation_id(payload)


def effective_cache_freshness(
    payload: dict[str, Any],
    *,
    now: str,
) -> str:
    repository = _require_repository(payload.get("repository"))
    value = _validate_cached_payload(copy.deepcopy(payload), repository)
    now_dt = _timestamp_value(now, "now")
    generated_dt = _timestamp_value(value["generated_at"], "generated_at")
    valid_until_dt = _timestamp_value(value["valid_until"], "valid_until")
    if now_dt < generated_dt:
        return "UNKNOWN"
    if now_dt > valid_until_dt:
        return "STALE"
    repository_source = value["repository_source"]
    if repository_source["status"] != "AVAILABLE":
        return "UNAVAILABLE"
    if repository_source["freshness"] == "STALE":
        return "STALE"
    if repository_source["freshness"] != "CURRENT":
        return "UNKNOWN"
    reconciliation_source = value["reconciliation_source"]
    if reconciliation_source["status"] != "AVAILABLE":
        return "INVALID"
    if reconciliation_source["trust"] != "VERIFIED":
        return "UNKNOWN"
    return "CURRENT"


def render_cached_human_portfolio(payload: dict[str, Any]) -> str:
    repository = _require_repository(payload.get("repository"))
    validated = _validate_cached_payload(
        copy.deepcopy(payload),
        repository,
    )
    encoded = json.dumps(
        validated,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return f"{CACHE_MARKER_BEGIN}\n{encoded}\n{CACHE_MARKER_END}"


def parse_cached_human_portfolio(
    body: str,
    repository: str,
) -> CachedHumanPortfolio | None:
    repository = _require_repository(repository)
    try:
        payload = marker_json.parse_json_object_block(
            body,
            CACHE_MARKER_BEGIN,
            CACHE_MARKER_END,
            label="human portfolio cache",
        )
    except marker_json.MarkerJSONError as exc:
        raise HumanPortfolioCacheError(str(exc)) from exc
    if payload is None:
        return None
    validated = _validate_cached_payload(payload, repository)
    return CachedHumanPortfolio(payload=copy.deepcopy(validated))


def replace_cached_human_portfolio(
    body: str,
    repository: str,
    payload: dict[str, Any],
) -> str:
    repository = _require_repository(repository)
    if not isinstance(body, str):
        raise HumanPortfolioCacheError("Control body must be a string")
    validated = _validate_cached_payload(
        copy.deepcopy(payload),
        repository,
    )
    try:
        bounds = marker_json.marker_bounds(
            body,
            CACHE_MARKER_BEGIN,
            CACHE_MARKER_END,
            label="human portfolio cache",
        )
    except marker_json.MarkerJSONError as exc:
        raise HumanPortfolioCacheError(str(exc)) from exc

    block = render_cached_human_portfolio(validated)
    if bounds is None:
        prefix = body.rstrip()
        return prefix + ("\n\n" if prefix else "") + block

    parse_cached_human_portfolio(body, repository)
    begin, end = bounds
    prefix = body[:begin]
    suffix = body[end + len(CACHE_MARKER_END):]
    return prefix + block + suffix
