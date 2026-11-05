"""Pure plan-only Private CI quota preflight, devflow #752.

No GitHub requests, secrets, filesystem reads/writes or job execution occur
here. Production callers must independently authenticate every input and
persist flags with an atomic, auditable single-writer protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from math import isfinite

JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class UsageProof:
    account: str
    billing_month: str
    checked_on_jst: str
    equivalent_minutes: float | None
    included_minutes: int | None
    authenticated: bool = False
    metering_complete: bool = False


@dataclass(frozen=True)
class MonthFlag:
    account: str
    billing_month: str
    source_verified: bool = False


@dataclass(frozen=True)
class QuotaPlan:
    status: str  # PLAN_ONLY | HOLD
    action: str  # QUERY_BILLING | WRITE_FLAG | HOSTED_CANDIDATE | FALLBACK_CANDIDATE | HOLD
    reason: str


def _month(value: object) -> bool:
    return (
        type(value) is str and len(value) == 7 and value[4] == "-"
        and value[:4].isascii() and value[:4].isdigit()
        and value[5:].isascii() and value[5:].isdigit()
        and 1 <= int(value[5:]) <= 12 and int(value[:4]) >= 1
    )


def plan_private_quota_preflight(
    account: str, now_utc: datetime,
    usage: UsageProof | None = None,
    flag: MonthFlag | None = None,
) -> QuotaPlan:
    """Plan a daily GET or monthly override; never authorize a runner."""
    def hold(reason: str) -> QuotaPlan:
        return QuotaPlan("HOLD", "HOLD", reason)

    def propose(action: str, reason: str) -> QuotaPlan:
        return QuotaPlan("PLAN_ONLY", action, reason)

    if type(account) is not str or not account or "/" in account:
        return hold("INVALID_ACCOUNT")
    if (type(now_utc) is not datetime or now_utc.tzinfo is None
            or now_utc.utcoffset() != timedelta(0)):
        return hold("UTC_TIME_REQUIRED")

    month = now_utc.strftime("%Y-%m")
    day_jst = now_utc.astimezone(JST).strftime("%Y-%m-%d")

    if flag is not None:
        if (type(flag) is not MonthFlag or flag.account != account
                or not _month(flag.billing_month)
                or type(flag.source_verified) is not bool
                or not flag.source_verified):
            return hold("FLAG_SOURCE_NOT_VERIFIED")
        if flag.billing_month > month:
            return hold("FUTURE_BILLING_MONTH_FLAG")
        if flag.billing_month == month:
            return propose("FALLBACK_CANDIDATE", "CURRENT_MONTH_EXHAUSTION_FLAG")
        # Older month is logically expired; no background reset required.

    if usage is None:
        return propose("QUERY_BILLING", "FIRST_QUERY_OF_EXECUTION_DAY")
    if (type(usage) is not UsageProof or usage.account != account
            or not _month(usage.billing_month)
            or type(usage.authenticated) is not bool
            or type(usage.metering_complete) is not bool
            or not usage.authenticated):
        return hold("BILLING_SOURCE_NOT_VERIFIED")
    if usage.billing_month > month:
        return hold("FUTURE_USAGE_PERIOD")
    if usage.billing_month != month or usage.checked_on_jst != day_jst:
        return propose("QUERY_BILLING", "DAILY_CACHE_EXPIRED")

    # An unknown SKU, entitlement, multiplier or a partial report is NOT a
    # verified '0 remaining'. Calling layers may independently launch one
    # approved hosted attempt and classify its actual launch outcome.
    if not usage.metering_complete:
        return hold("METERING_NOT_PROVEN")
    used, allowance = usage.equivalent_minutes, usage.included_minutes
    if (type(used) not in (float, int) or not isfinite(used)
            or used < 0 or type(allowance) is not int or allowance <= 0):
        return hold("INVALID_ENTITLEMENT_OR_METERING")
    if used >= allowance:
        return propose("WRITE_FLAG", "MONTHLY_INCLUDED_MINUTES_EXHAUSTED")
    return propose("HOSTED_CANDIDATE", "DAILY_USAGE_BELOW_ALLOWANCE")


__all__ = ["UsageProof", "MonthFlag", "QuotaPlan", "plan_private_quota_preflight"]
