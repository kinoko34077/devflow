"""Offline-only shape checks for M9 workflow_dispatch response and run identity.

This module never issues requests, verifies protection/identity/permissions,
or grants an execution/claim. Inputs, including expected pins, are untrusted
unless a separately reviewed authenticated adapter proves their provenance.
Do not turn either MATCHED result into ADMITTED, EXECUTED or a receipt.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z", re.ASCII)
_PATH = re.compile(r"\.github/workflows/[A-Za-z0-9_-]{1,80}\.ya?ml\Z", re.ASCII)
_REF = re.compile(r"refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]{0,95}\Z", re.ASCII)
_MAX_RUN_ID = 2**63 - 1


@dataclass(frozen=True)
class M9OfflinePin:
    """Caller-supplied expected fields are NOT a reviewed trust root."""
    repository_id: int
    repository: str
    workflow_id: int
    workflow_path: str
    ref: str
    head_sha: str


@dataclass(frozen=True)
class M9Evidence:
    status: str
    reason: str
    run_id: int | None = None


def _is_positive_int(value: Any) -> bool:
    return type(value) is int and 0 < value <= _MAX_RUN_ID


def _valid_pin(pin: object) -> bool:
    if type(pin) is not M9OfflinePin:
        return False
    if not (_is_positive_int(pin.repository_id) and _is_positive_int(pin.workflow_id)):
        return False
    if not (type(pin.repository) is str and _REPO.fullmatch(pin.repository)):
        return False
    if not (type(pin.workflow_path) is str and _PATH.fullmatch(pin.workflow_path)):
        return False
    if not (type(pin.ref) is str and _REF.fullmatch(pin.ref)):
        return False
    if (".." in pin.ref or "//" in pin.ref or "@{" in pin.ref
            or pin.ref.endswith(("/", ".", ".lock"))
            or any(x.startswith(".") or x.endswith((".", ".lock"))
                   for x in pin.ref.split("/")[2:])):
        return False
    return type(pin.head_sha) is str and _SHA.fullmatch(pin.head_sha) is not None


def _urls(pin: M9OfflinePin, run_id: int) -> tuple[str, str]:
    suffix = f"{pin.repository}/actions/runs/{run_id}"
    return f"https://api.github.com/repos/{suffix}", f"https://github.com/{suffix}"


def inspect_dispatch_response(
    pin: M9OfflinePin, *, http_status: Any, response: Any,
) -> M9Evidence:
    """Check the 2026 run-details REST response shape, not a real dispatch."""
    if not _valid_pin(pin):
        return M9Evidence("BLOCKED", "INVALID_EXPECTED_PIN")
    if type(http_status) is not int or http_status != 200:
        return M9Evidence("DISPATCH_OUTCOME_UNKNOWN", "NO_VERIFIED_RUN_DETAILS")
    if type(response) is not dict or set(response) != {"workflow_run_id", "run_url", "html_url"}:
        return M9Evidence("DISPATCH_OUTCOME_UNKNOWN", "INVALID_RESPONSE_SHAPE")
    run_id = response.get("workflow_run_id")
    if not _is_positive_int(run_id):
        return M9Evidence("DISPATCH_OUTCOME_UNKNOWN", "INVALID_RUN_ID")
    api, browser = _urls(pin, run_id)
    if (type(response.get("run_url")) is not str
            or type(response.get("html_url")) is not str
            or response["run_url"] != api or response["html_url"] != browser):
        return M9Evidence("DISPATCH_OUTCOME_UNKNOWN", "RUN_URL_MISMATCH")
    return M9Evidence("OFFLINE_RESPONSE_SHAPE_MATCHED", "NOT_AUTHENTICATED_NOT_DISPATCHED", run_id)


def inspect_run_metadata(
    pin: M9OfflinePin, *, expected_run_id: Any, run: Any,
) -> M9Evidence:
    """Check synthetic GET /actions/runs/{id} metadata only.

    Does not verify protected ref/immutable workflow blob, job-side pre-effect
    gates, durable request IDs, GitHub transport, execution or permissions.
    """
    if not _valid_pin(pin) or not _is_positive_int(expected_run_id):
        return M9Evidence("BLOCKED", "INVALID_EXPECTED_PIN_OR_RUN")
    if type(run) is not dict:
        return M9Evidence("BLOCKED", "INVALID_RUN_OBJECT")
    repo = run.get("repository")
    if type(repo) is not dict:
        return M9Evidence("BLOCKED", "MISSING_REPOSITORY")
    if (not _is_positive_int(repo.get("id")) or repo["id"] != pin.repository_id
            or type(repo.get("full_name")) is not str
            or repo["full_name"] != pin.repository):
        return M9Evidence("BLOCKED", "REPOSITORY_MISMATCH")
    if (type(run.get("id")) is not int or run["id"] != expected_run_id
            or type(run.get("workflow_id")) is not int
            or run["workflow_id"] != pin.workflow_id):
        return M9Evidence("BLOCKED", "RUN_OR_WORKFLOW_ID_MISMATCH")
    if (type(run.get("event")) is not str or run["event"] != "workflow_dispatch"
            or type(run.get("head_sha")) is not str or run["head_sha"] != pin.head_sha):
        return M9Evidence("BLOCKED", "RUN_EVENT_OR_HEAD_MISMATCH")
    if (type(run.get("path")) is not str
            or run["path"] != pin.workflow_path + "@" + pin.ref
            or type(run.get("head_branch")) is not str
            or run["head_branch"] != pin.ref.split("/", 2)[2]):
        return M9Evidence("BLOCKED", "RUN_PATH_OR_REF_MISMATCH")
    if not _is_positive_int(run.get("run_attempt")):
        return M9Evidence("BLOCKED", "INVALID_RUN_ATTEMPT")
    api, browser = _urls(pin, expected_run_id)
    if (type(run.get("url")) is not str or run["url"] != api
            or type(run.get("html_url")) is not str or run["html_url"] != browser):
        return M9Evidence("BLOCKED", "RUN_URL_MISMATCH")
    return M9Evidence("OFFLINE_RUN_METADATA_MATCHED", "NOT_AUTHENTICATED_NOT_EXECUTED", expected_run_id)
