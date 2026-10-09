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


def _accepted_permissions(headers: Any) -> str | None:
    """Validate every item; preserve GitHub's AND (comma) / OR (semicolon)."""
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
    elif status == 422:
        category = "validation_failed"
    else:
        category = "unclassified"

    result = [f"category={category}"]
    permissions = _accepted_permissions(headers)
    if permissions is not None:
        result.append(f"accepted_permissions={permissions}")
    request_id = _header(headers, "X-GitHub-Request-Id")
    if request_id and _REQUEST_ID.fullmatch(request_id.strip()):
        result.append(f"request_id={request_id.strip()}")
    if remaining is not None:
        result.append(f"rate_remaining={remaining}")
    if reset is not None:
        result.append(f"rate_reset_epoch={reset}")
    if retry_after is not None:
        result.append(f"retry_after_seconds={retry_after}")
    return " ".join(result)
