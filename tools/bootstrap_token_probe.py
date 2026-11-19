"""Read-only check of the Repository Bootstrap Actions credential."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


USER_ENDPOINT = "https://api.github.com/user"
PROTECTED_MAIN_ENDPOINT = "https://api.github.com/repos/kinoko34077/devflow/branches/main/protection"
EXPECTED_USER_ID = 79015263
EXPECTED_LOGIN = "kinoko34077"
REQUEST_TIMEOUT_SECONDS = 15
_SAFE_REQUEST_ID = re.compile(r"[0-9A-F]{3,10}(?::[0-9A-F]{3,12}){2,4}\Z", re.IGNORECASE)
_SAFE_RUN_ID = re.compile(r"[0-9]{1,20}\Z")


class ProbeInputError(ValueError):
    """The credential cannot safely be used by this probe."""


class _RejectRedirects(HTTPRedirectHandler):
    """Never replay the credential to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_urlopen(request: Request, *, timeout: int):
    return build_opener(_RejectRedirects).open(request, timeout=timeout)


def _request_id(headers: Any) -> str | None:
    value = headers.get("X-GitHub-Request-Id") if headers is not None else None
    if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return None


def _http_classification(status: int) -> str:
    if 200 <= status < 300:
        return "success"
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "forbidden_or_rate_limited"
    if status == 404:
        return "not_found_or_unavailable"
    if status == 422:
        return "validation_failed"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "github_service_error"
    return "http_error"


def _get_json(endpoint: str, token: str, opener: Callable[..., Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    request = Request(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "kinoko34077-devflow-bootstrap-token-probe",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        method="GET",
    )
    try:
        with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = int(response.status)
            headers = response.headers
            body = response.read()
    except HTTPError as error:
        status = int(error.code)
        headers = error.headers
        # Do not read or include the HTTP error body: GitHub messages may contain
        # details that are unnecessary for this credential identity check.
        result = {
            "status": status,
            "classification": _http_classification(status),
            "request_id": _request_id(headers),
        }
        error.close()
        return None, result
    except (TimeoutError, URLError, OSError):
        return None, {"status": None, "classification": "transport_error", "request_id": None}

    classification = _http_classification(status)
    if classification != "success":
        return None, {
            "status": status,
            "classification": classification,
            "request_id": _request_id(headers),
        }

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        return None, {
            "status": status,
            "classification": "invalid_response",
            "request_id": _request_id(headers),
        }
    return payload, {
        "status": status,
        "classification": "success",
        "request_id": _request_id(headers),
    }


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_probe(
    token: str,
    *,
    opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Call only two pinned GET endpoints and return a redacted report."""
    malformed = (
        not isinstance(token, str)
        or not token
        or token != token.strip()
        or "\n" in token
        or "\r" in token
    )
    if malformed:
        raise ProbeInputError("credential is missing or malformed")

    started_at = _timestamp(now)
    http_open = opener or _safe_urlopen
    user, user_result = _get_json(USER_ENDPOINT, token, http_open)
    principal_matches = bool(
        user
        and type(user.get("id")) is int
        and user.get("id") == EXPECTED_USER_ID
        and isinstance(user.get("login"), str)
        and user.get("login", "").casefold() == EXPECTED_LOGIN.casefold()
    )
    protection_result: dict[str, Any]
    if not principal_matches:
        protection_result = {"status": None, "classification": "not_run", "request_id": None}
        result = (
            "PRINCIPAL_MISMATCH"
            if user_result["classification"] == "success"
            else "USER_READ_FAILED"
        )
    else:
        _, protection_result = _get_json(PROTECTED_MAIN_ENDPOINT, token, http_open)
        result = (
            "READ_CHECKS_PASSED"
            if protection_result["classification"] == "success"
            else "PROTECTED_MAIN_READ_FAILED"
        )

    safe_run_id = run_id if isinstance(run_id, str) and _SAFE_RUN_ID.fullmatch(run_id) else None
    return {
        "schema": "repository-bootstrap-token-probe.v1",
        "probe_started_at_utc": started_at,
        "probe_finished_at_utc": _timestamp(now),
        "run_id": safe_run_id,
        "result": result,
        "principal_matches_expected": principal_matches,
        "user_read": user_result,
        "protected_main_read": protection_result,
    }


def main(
    *,
    opener: Callable[..., Any] | None = None,
    write: Callable[[str], Any] = print,
) -> int:
    token = os.environ.get("REPOSITORY_BOOTSTRAP_TOKEN", "")
    try:
        report = run_probe(token, opener=opener, run_id=os.environ.get("GITHUB_RUN_ID"))
    except ProbeInputError:
        report = {
            "schema": "repository-bootstrap-token-probe.v1",
            "probe_started_at_utc": _timestamp(None),
            "probe_finished_at_utc": _timestamp(None),
            "run_id": None,
            "result": "INPUT_ERROR",
            "error_code": "credential_missing_or_malformed",
        }
    write(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report.get("result") == "READ_CHECKS_PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
