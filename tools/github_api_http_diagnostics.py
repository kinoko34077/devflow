"""Allowlisted, credential-safe diagnostics for failed GitHub REST requests.

Never include arbitrary GitHub response text, request headers, or response header
values in errors: an upstream response may contain credentials or private data.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_ERROR_BODY_BYTES = 4096

_ALLOWED_PERMISSIONS = frozenset({
    "actions", "administration", "checks", "commit_statuses", "contents",
    "issues", "metadata", "pull_requests", "workflows",
})
_PERMISSION = re.compile(r"([a-z_]+)\s*=\s*(read|write|admin)", re.IGNORECASE)
# GitHub request IDs are colon-delimited hex groups; reject opaque IDs/tokens.
_REQUEST_ID = re.compile(r"[0-9A-F]{3,10}(?::[0-9A-F]{3,12}){2,4}\Z", re.IGNORECASE)
_VALIDATION_FIELDS = frozenset({
    "required_status_checks", "required_pull_request_reviews", "enforce_admins",
    "restrictions", "allow_force_pushes", "allow_deletions",
    "required_conversation_resolution", "contexts", "checks", "strict", "app_id",
    "required_status_checks.contexts", "required_status_checks.checks",
    "required_status_checks.checks.context", "required_status_checks.checks.app_id",
    "required_status_checks.strict",
    "required_pull_request_reviews.required_approving_review_count",
    "required_pull_request_reviews.bypass_pull_request_allowances",
    "required_pull_request_reviews.bypass_pull_request_allowances.users",
    "required_pull_request_reviews.bypass_pull_request_allowances.teams",
    "required_pull_request_reviews.bypass_pull_request_allowances.apps",
    "required_pull_request_reviews.dismiss_stale_reviews",
    "required_pull_request_reviews.require_code_owner_reviews",
    "required_pull_request_reviews.require_last_push_approval",
})
_VALIDATION_CODES = frozenset({
    "already_exists", "custom", "invalid", "missing", "missing_field", "unprocessable",
})


def _normalize_validation_field(value: str) -> str:
    """Normalize only numeric array indexes in a GitHub field path."""
    normalized = re.sub(r"\[\d+\]", "", value)
    return re.sub(r"\.(\d+)\.", ".", normalized)


def _safe_validation_field(value: Any) -> str | None:
    """Return a known field after removing only numeric array indexes."""
    if not isinstance(value, str):
        return None
    normalized = _normalize_validation_field(value.strip())
    return normalized if normalized in _VALIDATION_FIELDS else None


def _safe_validation_code(value: Any) -> str | None:
    """Return a known GitHub validation code; never echo unknown values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized if normalized in _VALIDATION_CODES else None


def _safe_validation_error_from_text(value: str) -> tuple[str | None, str | None]:
    """Extract only a known field and code from a GitHub string error item."""
    normalized = _normalize_validation_field(value[:MAX_ERROR_BODY_BYTES].casefold())

    for field in sorted(_VALIDATION_FIELDS, key=len, reverse=True):
        field_pattern = re.compile(
            rf"(?<![a-z0-9_.]){re.escape(field)}(?![a-z0-9_.])"
        )
        match = field_pattern.search(normalized)
        if match is None:
            continue
        tail = normalized[match.end():match.end() + 96]
        codes = "|".join(
            re.escape(code) for code in sorted(_VALIDATION_CODES, key=len, reverse=True)
        )
        code_pattern = re.compile(
            rf"^[\s:=,;\"']*({codes})(?![a-z0-9_])"
        )
        code_match = code_pattern.search(tail)
        if code_match is None:
            code_pattern = re.compile(
                rf"\bcode[\"']?\s*[:=]\s*[\"']?({codes})(?![a-z0-9_])"
            )
            code_match = code_pattern.search(tail)
        code = code_match.group(1) if code_match is not None else None
        return field, code
    return None, None


def _validation_error_item_shape(errors: list[Any]) -> str:
    """Return a fixed JSON-type label for non-object error array entries."""
    kinds: set[str] = set()
    for error in errors[:16]:
        if isinstance(error, dict):
            kinds.add("object")
        elif isinstance(error, list):
            kinds.add("array")
        elif error is None:
            kinds.add("null")
        elif isinstance(error, bool):
            kinds.add("boolean")
        elif isinstance(error, (int, float)):
            kinds.add("number")
        elif isinstance(error, str):
            kinds.add("string")
        else:
            kinds.add("other")
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixed"


def _header(headers: Any, name: str) -> str | None:
    """Read only named headers; never serialize the header collection."""
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except (AttributeError, TypeError, ValueError):
        return None
    return value if isinstance(value, str) else None


def _number(headers: Any, name: str, upper: int) -> str | None:
    value = _header(headers, name)
    if value is None:
        return None
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,16}", value, flags=re.ASCII):
        return None
    return str(int(value)) if int(value) <= upper else None


def _endpoint_required_permissions(headers: Any) -> str | None:
    """Validate endpoint-required permissions, not the caller token's grants."""
    raw = _header(headers, "X-Accepted-GitHub-Permissions")
    if not raw or len(raw) > 256:
        return None
    groups: list[str] = []
    for alternative in raw.split(";"):
        pairs: list[str] = []
        for part in alternative.split(","):
            match = _PERMISSION.fullmatch(part.strip())
            if match is None:
                return None
            name, level = match.groups()
            if name.lower() not in _ALLOWED_PERMISSIONS:
                return None
            pairs.append(f"{name.lower()}={level.lower()}")
        if not pairs:
            return None
        groups.append(",".join(pairs))
    return ";".join(groups) if groups else None


def _message_kind(response_body: bytes) -> str:
    """Classify known GitHub messages without copying any message into logs."""
    try:
        parsed = json.loads(response_body[:MAX_ERROR_BODY_BYTES].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return ""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("message"), str):
        return ""
    message = parsed["message"][:MAX_ERROR_BODY_BYTES].casefold()
    if (
        "refusing to allow" in message
        and "workflow" in message
        and ("scope" in message or "permission" in message)
    ) or ("workflow scope" in message and ("missing" in message or "without" in message)):
        return "workflow_scope_denied"
    if "secondary rate limit" in message or "secondary rate limits" in message:
        return "secondary_rate_limited"
    if "rate limit exceeded" in message or "api rate limit" in message:
        return "rate_limited"
    if "endpoint" in message and "spam" in message:
        return "endpoint_spammed"
    if (
        "protected branch" in message
        or "branch protection" in message
        or "repository rule" in message
        or "ruleset" in message
    ):
        return "repository_policy_denied"
    if "resource not accessible by integration" in message or "resource not accessible by personal access token" in message:
        return "integration_permission_denied"
    return ""


def _validation_details(response_body: bytes) -> list[str]:
    """Expose only fixed schema hints and allowlisted field/code pairs."""
    if not isinstance(response_body, bytes):
        return ["validation_errors=unavailable"]
    if len(response_body) > MAX_ERROR_BODY_BYTES:
        return ["validation_errors=oversize"]
    if not response_body:
        return ["validation_errors=empty_body"]
    try:
        parsed = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return ["validation_errors=malformed"]
    if not isinstance(parsed, dict):
        return ["validation_errors=unexpected_root"]

    messages: list[str] = []
    top_message = parsed.get("message")
    if isinstance(top_message, str):
        messages.append(top_message[:MAX_ERROR_BODY_BYTES].casefold())

    raw_errors = parsed.get("errors")
    errors = raw_errors[:16] if isinstance(raw_errors, list) else []
    if "errors" not in parsed:
        error_shape = "absent"
    elif not isinstance(raw_errors, list):
        error_shape = "unexpected_shape"
    elif not raw_errors:
        error_shape = "empty"
    else:
        error_shape = "unclassified"
    for error in errors:
        if isinstance(error, dict):
            error_message = error.get("message")
            if isinstance(error_message, str):
                messages.append(error_message[:MAX_ERROR_BODY_BYTES].casefold())
        elif isinstance(error, str):
            messages.append(error[:MAX_ERROR_BODY_BYTES].casefold())

    details: list[str] = []
    if any(
        re.search(r"(?<![a-z0-9_])more than one subschema in oneof matched(?![a-z0-9_])", item)
        for item in messages
    ):
        details.append("validation_shape=one_of_conflict")
    elif any(
        re.search(r"(?<![a-z0-9_])no subschema in oneof matched(?![a-z0-9_])", item)
        for item in messages
    ):
        details.append("validation_shape=no_one_of_match")

    for error in errors:
        if not isinstance(error, dict):
            continue
        field = _safe_validation_field(error.get("field"))
        code = _safe_validation_code(error.get("code"))
        if field is not None and code is not None:
            details.append(f"validation_error={field}:{code}")
            break
    if not any(item.startswith("validation_error=") for item in details):
        for error in errors:
            if not isinstance(error, str):
                continue
            field, code = _safe_validation_error_from_text(error)
            if field is not None and code is not None:
                details.append(f"validation_error={field}:{code}")
                break
    if not any(item.startswith("validation_error=") for item in details):
        details.append(f"validation_errors={error_shape}")
    if not any(item.startswith("validation_error=") for item in details):
        for field in sorted(_VALIDATION_FIELDS, key=len, reverse=True):
            schema_paths = ["properties/" + "/properties/".join(
                re.escape(segment) for segment in field.split(".")
            )]
            if field.startswith("required_status_checks.checks."):
                leaf = re.escape(field.rsplit(".", 1)[1])
                schema_paths.append(
                    "properties/required_status_checks/properties/checks/items/properties/"
                    + leaf
                )
            if any(
                re.search(rf"{schema_path}(?![a-z0-9_])", item)
                for schema_path in schema_paths
                for item in messages
            ):
                details.append(f"validation_field={field}")
                break
    if not any(
        item.startswith(("validation_error=", "validation_field="))
        for item in details
    ):
        for error in errors:
            if not isinstance(error, str):
                continue
            field, _code = _safe_validation_error_from_text(error)
            if field is not None:
                details.append(f"validation_field={field}")
                break
    if not any(item.startswith("validation_error=") for item in details):
        for error in errors:
            if not isinstance(error, dict):
                continue
            field = _safe_validation_field(error.get("field"))
            code = _safe_validation_code(error.get("code"))
            details.append(
                "validation_error="
                f"{field or 'unclassified_field'}:"
                f"{code or 'unclassified_code'}"
            )
            break
    if errors and any(not isinstance(error, dict) for error in errors):
        details.append(f"validation_error_items={_validation_error_item_shape(errors)}")
    return details


def summarize_github_http_error(status: int, headers: Any, response_body: bytes) -> str:
    """Return bounded classification and validated metadata; never raw error text."""
    message_kind = _message_kind(response_body)
    remaining = _number(headers, "X-RateLimit-Remaining", 100000000)
    retry_after = _number(headers, "Retry-After", 86400)
    reset = _number(headers, "X-RateLimit-Reset", 9999999999)
    if status in (403, 429) and remaining == "0":
        category = "primary_rate_limited"
    elif status in (403, 429) and message_kind == "secondary_rate_limited":
        category = "secondary_rate_limited"
    elif message_kind == "workflow_scope_denied":
        category = "workflow_scope_denied"
    elif message_kind == "repository_policy_denied":
        category = "repository_policy_denied"
    elif message_kind == "integration_permission_denied":
        category = "integration_permission_denied"
    elif status == 429 or (status == 403 and message_kind == "rate_limited"):
        category = "rate_limited"
    elif status == 401:
        category = "unauthorized"
    elif status == 403:
        category = "forbidden_unclassified"
    elif status == 422 and message_kind == "endpoint_spammed":
        category = "endpoint_spammed"
    elif status == 422:
        category = "validation_failed"
    else:
        category = "unclassified"

    result = [f"category={category}"]
    permissions = _endpoint_required_permissions(headers)
    if permissions is not None:
        result.append(f"endpoint_required_permissions={permissions}")
    request_id = _header(headers, "X-GitHub-Request-Id")
    if request_id and _REQUEST_ID.fullmatch(request_id.strip()):
        result.append(f"request_id={request_id.strip()}")
    if remaining is not None:
        result.append(f"rate_remaining={remaining}")
    if reset is not None:
        result.append(f"rate_reset_epoch={reset}")
    if retry_after is not None:
        result.append(f"retry_after_seconds={retry_after}")
    if status == 422:
        result.extend(_validation_details(response_body))
    return " ".join(result)
