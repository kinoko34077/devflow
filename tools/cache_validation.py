from __future__ import annotations

from datetime import datetime
from typing import Any

from tools.repository_identity import is_repository_name


def require_mapping(
    value: object,
    field: str,
    error_type: type[ValueError],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise error_type(f"{field} must be an object")
    return dict(value)


def require_exact_fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    field: str,
    error_type: type[ValueError],
) -> None:
    keys = set(value)
    missing = sorted(allowed - keys)
    unknown = sorted(keys - allowed)
    if missing:
        raise error_type(f"{field} missing fields: " + ", ".join(missing))
    if unknown:
        raise error_type(f"{field} has unknown fields: " + ", ".join(unknown))


def require_repository(
    value: object,
    field: str,
    error_type: type[ValueError],
) -> str:
    if not is_repository_name(value):
        raise error_type(f"{field} must be owner/repository")
    return value.strip()


def require_timestamp(
    value: object,
    field: str,
    error_type: type[ValueError],
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field} must be an RFC-3339 timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise error_type(f"{field} must be an RFC-3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise error_type(
            f"{field} must include an RFC-3339 timezone offset"
        )
    return text


def timestamp_value(
    value: object,
    field: str,
    error_type: type[ValueError],
) -> datetime:
    return datetime.fromisoformat(
        require_timestamp(value, field, error_type).replace("Z", "+00:00")
    )


def format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def require_bool(
    value: object,
    field: str,
    error_type: type[ValueError],
) -> bool:
    if not isinstance(value, bool):
        raise error_type(f"{field} must be boolean")
    return value


def require_optional_string(
    value: object,
    field: str,
    error_type: type[ValueError],
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field} must be a non-empty string or null")
    return value.strip()

