"""Explicit, read-only Plan:read GitHub billing summary adapter for #752.

No background triggers, credential storage, repository writes or job launch.
The caller supplies an ephemeral user Plan:read token only for one fixed GitHub
API GET. A successful API response is *not* remaining included-minute proof:
summary discounts include unlimited Public Actions free usage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from json import JSONDecodeError
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

_ACCOUNT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_MAX_RESPONSE = 1024 * 1024
_TIMEOUT_SECONDS = 10


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class BillingReadResult:
    status: str  # REPORT_RECEIVED_INCONCLUSIVE | AUTH_UNAVAILABLE | API_UNAVAILABLE | HOLD
    reason: str
    account: str
    billing_month: str
    usage_rows: int = 0
    # Deliberately NEVER an authenticated runner authorization or quota proof.
    included_minutes_exhausted: bool | None = None
    request_attempted: bool = False


def fetch_actions_summary_once(
    account: str,
    now_utc: datetime,
    token: str,
    *,
    opener=None,
) -> BillingReadResult:
    """Explicit fixed-host GET. A fake test opener does not grant trust."""
    if (type(account) is not str or not _ACCOUNT.fullmatch(account)
            or type(now_utc) is not datetime or now_utc.tzinfo is None
            or now_utc.utcoffset() != timedelta(0)):
        return BillingReadResult("HOLD", "INVALID_ACCOUNT_OR_UTC_CLOCK", "", "")
    month = now_utc.strftime("%Y-%m")
    if type(token) is not str or not token or "\r" in token or "\n" in token:
        return BillingReadResult("AUTH_UNAVAILABLE", "MISSING_OR_INVALID_EPHEMERAL_TOKEN", account, month)

    url = (
        "https://api.github.com/users/" + account
        + "/settings/billing/usage/summary?year=" + str(now_utc.year)
        + "&month=" + str(now_utc.month) + "&product=Actions"
    )
    request = Request(
        url, method="GET", headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "kinotch-devflow-billing-preflight",
        },
    )
    opener = build_opener(_NoRedirect()) if opener is None else opener
    try:
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            if response.geturl() != url:
                return BillingReadResult("HOLD", "UNEXPECTED_FINAL_ENDPOINT", account, month, request_attempted=True)
            if response.status != 200:
                return BillingReadResult("API_UNAVAILABLE", "UNEXPECTED_HTTP_STATUS", account, month, request_attempted=True)
            payload = response.read(_MAX_RESPONSE + 1)
    except HTTPError as exc:
        if exc.code in (401, 403, 404):
            return BillingReadResult("AUTH_UNAVAILABLE", "BILLING_API_AUTH_REJECTED", account, month, request_attempted=True)
        return BillingReadResult("API_UNAVAILABLE", "BILLING_API_HTTP_ERROR", account, month, request_attempted=True)
    except (URLError, OSError, TimeoutError):
        return BillingReadResult("API_UNAVAILABLE", "BILLING_API_UNREACHABLE", account, month, request_attempted=True)

    if len(payload) > _MAX_RESPONSE:
        return BillingReadResult("HOLD", "BILLING_API_RESPONSE_TOO_LARGE", account, month, request_attempted=True)
    try:
        report = json.loads(payload)
    except (JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return BillingReadResult("HOLD", "INVALID_BILLING_REPORT_JSON", account, month, request_attempted=True)
    if (type(report) is not dict or type(report.get("user")) is not str
            or report["user"].casefold() != account.casefold()):
        return BillingReadResult("HOLD", "MISMATCHED_BILLING_OWNER", account, month, request_attempted=True)
    period = report.get("timePeriod")
    # Official user summary examples may report only timePeriod.year even
    # when the request is pinned to a single month. The fixed HTTPS request
    # carries the month constraint; reject an explicit contradictory month.
    if (type(period) is not dict or type(period.get("year")) is not int
            or period["year"] != now_utc.year
            or ("month" in period and (
                type(period["month"]) is not int
                or period["month"] != now_utc.month))):
        return BillingReadResult("HOLD", "BILLING_PERIOD_NOT_PROVEN", account, month, request_attempted=True)
    items = report.get("usageItems")
    if type(items) is not list:
        return BillingReadResult("HOLD", "MISSING_USAGE_ITEMS", account, month, request_attempted=True)
    for item in items:
        if (type(item) is not dict or type(item.get("product")) is not str
                or item["product"].casefold() != "actions"):
            return BillingReadResult("HOLD", "UNEXPECTED_BILLING_PRODUCT", account, month, request_attempted=True)
    return BillingReadResult(
        "REPORT_RECEIVED_INCONCLUSIVE", "PUBLIC_AND_INCLUDED_DISCOUNTS_NOT_SEPARABLE",
        account, month, len(items), request_attempted=True,
    )


__all__ = ["BillingReadResult", "fetch_actions_summary_once"]
