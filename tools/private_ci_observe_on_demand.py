"""On-demand observation-only orchestration for Private CI, #752.

One call per Private CI request, no resident daemon, no runner dispatch and
no implicit GitHub Actions retries.  Credentials are ephemeral caller input.
A local journal is NOT authoritative execution/Claim permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3

from tools.private_ci_billing_readonly import fetch_actions_summary_once
from tools.private_ci_billing_store import LocalBillingObservationStore


@dataclass(frozen=True)
class PrivateCiObservation:
    status: str  # HOLD | PLAN_ONLY
    action: str  # PRIVATE_HOSTED_SUPPRESSED | RETAIN_DAILY_INCONCLUSIVE | QUERY_BILLING_ERROR | REPORT_CACHED | HOLD
    reason: str
    queried_github_billing: bool = False


def observe_private_ci_on_demand(
    account: str, now_utc: datetime, token: str, db_path: str | Path, *, opener=None
) -> PrivateCiObservation:
    """Observe/cache; NEVER declare runner eligible or quota depleted."""
    try:
        store = LocalBillingObservationStore(db_path)
        previous_block = store.read_monthly_block(account, now_utc)
        if previous_block is not None:
            # State is merely observed and explicitly not verified_for_dispatch.
            return PrivateCiObservation(
                "HOLD", "PRIVATE_HOSTED_SUPPRESSED",
                "LOCAL_MONTH_BILLING_BLOCK_REQUIRES_TRUSTED_RECHECK",
            )
        cached = store.read_daily(account, now_utc)
        if cached is not None:
            return PrivateCiObservation(
                "PLAN_ONLY", "RETAIN_DAILY_INCONCLUSIVE",
                "CACHED_USAGE_REPORT_DOES_NOT_PROVE_INCLUDED_MINUTES",
            )
    except (ValueError, sqlite3.Error, OSError):
        return PrivateCiObservation("HOLD", "HOLD", "LOCAL_OBSERVATION_JOURNAL_UNAVAILABLE")

    result = fetch_actions_summary_once(account, now_utc, token, opener=opener)
    if result.status != "REPORT_RECEIVED_INCONCLUSIVE":
        # Failure must not be cached as a whole-day terminal decision;
        # owner may fix the ephemeral token or GitHub transport and retry.
        return PrivateCiObservation(
            "HOLD", "QUERY_BILLING_ERROR", result.reason,
            queried_github_billing=result.status not in ("AUTH_UNAVAILABLE", "HOLD"),
        )
    try:
        store.record_daily(account, now_utc, "REPORT_RECEIVED_INCONCLUSIVE")
    except (ValueError, sqlite3.Error, OSError):
        return PrivateCiObservation(
            "HOLD", "HOLD", "BILLING_OBSERVATION_PERSISTENCE_FAILED",
            queried_github_billing=True,
        )
    return PrivateCiObservation(
        "PLAN_ONLY", "REPORT_CACHED",
        "BILLING_SUMMARY_OBSERVED_PRIVATE_ALLOWANCE_STILL_UNKNOWN",
        queried_github_billing=True,
    )


__all__ = ["PrivateCiObservation", "observe_private_ci_on_demand"]
