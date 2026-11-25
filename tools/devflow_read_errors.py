"""Shared finite diagnostics for the existing read-only Devflow CLI entry points.

Never expose a raw exception message or caller-controlled value as a reason_code.
The recipient-scoped native check-in CLI deliberately keeps core read errors generic.
"""
from __future__ import annotations

from tools.devflow_mcp_core import DevflowMCPError

# Never echo exception text or caller-controlled fields into machine-readable
# diagnostics. Unknown/future core error codes fail back to the generic code.
SAFE_READ_FAILURE_CODES = frozenset({
    "DEVFLOW_READ_UNAVAILABLE",
    "GITHUB_HTTP_401",
    "GITHUB_HTTP_403",
    "GITHUB_HTTP_403_RATE_LIMIT",
    "GITHUB_HTTP_404",
    "GITHUB_HTTP_429",
    "GITHUB_HTTP_OTHER",
    "GITHUB_NETWORK_UNAVAILABLE",
    "GITHUB_INVALID_JSON",
    "GITHUB_REDIRECTED_READ",
    "CONTROL_NOT_FOUND_OR_UNTRUSTED",
    "CONTROL_AMBIGUOUS",
    "CONTROL_SCHEMA_INVALID",
    "CONTROL_REPOSITORY_MISMATCH",
})
SAFE_ARGUMENT_FAILURE_CODES = frozenset({
    "INVALID_REPOSITORY",
    "REPOSITORY_ON_PORTFOLIO_OPERATION",
    "INVALID_PAGINATION",
    "INBOX_OPTIONS_ON_NON_INBOX_OPERATION",
    "INVALID_RECIPIENT",
    "INVALID_LIMIT",
    "INVALID_OFFSET",
    "INVALID_WORK_STATUS",
    "INVALID_RECENT_DISCOVERY_OPTION",
    "INVALID_SUPPLY_OBSERVATION_OPTION",
    "INVALID_ISSUE_NUMBER",
    "ISSUE_NUMBER_ON_NON_ISSUE_OPERATION",
    "PLAN_ON_NON_ASSESSMENT_OPERATION",
    "OUTCOME_ON_NON_ASSESSMENT_OPERATION",
    "INVALID_REPOSITORY_COUNT",
    "DUPLICATE_REPOSITORY",
    "MAPPED_READ_OPTIONS_CONFLICT",
    "MAPPED_READ_REQUEST_OR_SCOPE_REQUIRED",
    "MAPPED_READ_OPTIONS_ON_OTHER_OPERATION",
    "MAPPED_READ_INVALID_REQUEST_FILE",
    "INVALID_REQUEST_SHAPE",
    "UNSUPPORTED_SCHEMA",
    "UNSUPPORTED_DATASET",
    "INVALID_REPOSITORY_SCOPE",
    "INVALID_AUTHORIZED_SCOPE",
    "REPOSITORY_OUTSIDE_AUTHORIZED_SCOPE",
    "UNSUPPORTED_TIME_FIELD",
    "INVALID_UTC_TIMESTAMP",
    "INVALID_TIME_RANGE",
    "UNSUPPORTED_RESPONSE_FIELDS",
    "INVALID_RESPONSE_LIMIT",
    "INVALID_REQUEST_JSON",
    "UNSUPPORTED_FILTER",
    "UNSUPPORTED_BUDGET",
    "INVALID_SOURCE_OPTIONS",
    "CI_TARGET_ON_OTHER_OPERATION",
    "INVALID_CI_TARGET",
    "CI_OPTIONS_CONFLICT",
})


def failure_reason_code(exc: DevflowMCPError | ValueError) -> str:
    """Expose only an enumerated diagnostic; never a raw exception message."""
    if isinstance(exc, DevflowMCPError):
        code = getattr(exc, "reason_code", None)
        return code if code in SAFE_READ_FAILURE_CODES else "DEVFLOW_READ_UNAVAILABLE"
    code = str(exc)
    return code if code in SAFE_ARGUMENT_FAILURE_CODES else "INVALID_ARGUMENTS"

