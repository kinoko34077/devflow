"""Read-only local Devflow MCP adapter for the private GitHub Billing UI snapshot.

The stdio MCP process never navigates a browser, writes a request marker,
accesses credentials, or launches a billing collection. Only an explicitly
operator-configured, absolute local cache path is read; otherwise UNKNOWN.
It never grants Actions execution, Claim, or Check write authority (#752).
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Mapping

try:
    from .private_ci_billing_ui import (
        ObservationUnavailable, _read_json, status_view, validate_cached,
    )
except ImportError:  # direct script execution through devflow_mcp.py
    from private_ci_billing_ui import (  # type: ignore
        ObservationUnavailable, _read_json, status_view, validate_cached,
    )

CACHE_ENV = "DEVFLOW_GITHUB_BILLING_UI_CACHE"
ACCOUNT = "kinoko34077"


def get_configured_billing_observation(
    include_amounts: bool = False,
    *,
    environ: Mapping[str, str] | None = None,
    now_utc: datetime | None = None,
) -> dict:
    """Return bounded status or explicit details from the pinned local cache.

    No CLI-supplied or MCP-supplied path, owner, URL, token, or refresh command.
    The default output intentionally omits monetary amounts. Selecting details
    is an explicit financial-data read by an already trusted local MCP client.
    """
    unknown = {
        "schema": "devflow.github-billing-ui-observation.v1",
        "source": "github_personal_billing_settings_ui",
        "status": "UNKNOWN",
        "verified_for_dispatch": False,
    }
    if type(include_amounts) is not bool:
        return {**unknown, "reason": "INVALID_DETAILS_FLAG"}
    settings = os.environ if environ is None else environ
    configured = settings.get(CACHE_ENV, "")
    if not isinstance(configured, str) or not configured or len(configured) > 1024:
        return {**unknown, "reason": "LOCAL_BILLING_CACHE_NOT_CONFIGURED"}
    path = Path(configured)
    if not path.is_absolute() or path.suffix.lower() != ".json":
        return {**unknown, "reason": "LOCAL_BILLING_CACHE_PATH_INVALID"}
    try:
        # This is deliberately independent from the external billing summary
        # REST adapter: only the verified private-browser observation qualifies.
        validated = validate_cached(
            _read_json(path), ACCOUNT,
            datetime.now(timezone.utc) if now_utc is None else now_utc,
        )
    except (ObservationUnavailable, OSError, ValueError):
        return {**unknown, "reason": "LOCAL_BILLING_OBSERVATION_UNAVAILABLE_OR_STALE"}
    return validated if include_amounts else status_view(validated)


__all__ = ["CACHE_ENV", "get_configured_billing_observation"]
