"""Plan-only account billing-block evidence for Private CI, devflow #752.

This module **does not fetch GitHub**, assert caller identity, write flags,
read tokens, dispatch jobs, or grant Private runner execution.  A validated
shape and caller-reported source flag do not establish authentication.
Only an independently authenticated producer may emit trusted evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from tools.private_ci_quota_preflight import QuotaPlan

_BILLING_BLOCK = (
    "The job was not started because recent account payments have failed "
    "or your spending limit needs to be increased."
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class JobLaunchReceipt:
    account: str
    repository: str
    visibility: str
    run_id: int
    job_id: int
    head_sha: str
    completed_at_utc: datetime
    conclusion: str
    runner_name: str
    steps_count: int
    annotation: str
    authenticated_github_read: bool = False


@dataclass(frozen=True)
class MonthlyBillingBlock:
    account: str
    billing_month: str
    reason: str
    check_run_id: int
    source_verified: bool = False


def _utc(value: object) -> bool:
    return (
        type(value) is datetime and value.tzinfo is not None
        and value.utcoffset() == timedelta(0)
    )


def _plan(action: str, reason: str) -> QuotaPlan:
    return QuotaPlan("PLAN_ONLY", action, reason)


def _hold(reason: str) -> QuotaPlan:
    return QuotaPlan("HOLD", "HOLD", reason)


def classify_job_launch(receipt: object, now_utc: datetime, account: str) -> QuotaPlan:
    """Interpret a recent Private hosted failure, never authorize fallback."""
    if not _utc(now_utc) or type(account) is not str or not account:
        return _hold("INVALID_CURRENT_CONTEXT")
    if type(receipt) is not JobLaunchReceipt:
        return _hold("NO_TYPED_LAUNCH_RECEIPT")
    if (type(receipt.authenticated_github_read) is not bool
            or not receipt.authenticated_github_read):
        return _hold("GITHUB_READER_PROVENANCE_NOT_VERIFIED")
    if (type(receipt.account) is not str or receipt.account != account
            or type(receipt.repository) is not str
            or not receipt.repository.startswith(account + "/")
            or receipt.visibility != "private"):
        return _hold("WRONG_ACCOUNT_OR_VISIBILITY")
    if (type(receipt.run_id) is not int or receipt.run_id <= 0
            or type(receipt.job_id) is not int or receipt.job_id <= 0
            or type(receipt.head_sha) is not str
            or not _SHA.fullmatch(receipt.head_sha)):
        return _hold("MISSING_RUN_IDENTITY")
    if not _utc(receipt.completed_at_utc):
        return _hold("INVALID_RECEIPT_TIME")
    age = now_utc - receipt.completed_at_utc
    if age < timedelta(0):
        return _hold("FUTURE_RECEIPT")
    if age > timedelta(hours=24):
        return _hold("HISTORICAL_RECEIPT_RECHECK_REQUIRED")
    if (type(receipt.steps_count) is not int or receipt.steps_count < 0
            or type(receipt.runner_name) is not str
            or type(receipt.conclusion) is not str
            or type(receipt.annotation) is not str):
        return _hold("INVALID_JOB_SHAPE")
    if (receipt.conclusion != "failure"
            or receipt.steps_count != 0 or receipt.runner_name):
        return _hold("NOT_AN_UNSTARTED_HOSTED_JOB")
    if _BILLING_BLOCK not in receipt.annotation:
        return _hold("LAUNCH_FAILURE_CAUSE_NOT_BILLING_PROVEN")
    return _plan("RECORD_BILLING_BLOCK", "PRIVATE_HOSTED_BILLING_BLOCKED_NOT_QUOTA_PROOF")


def plan_monthly_billing_block(
    account: str, now_utc: datetime,
    *, flag: MonthlyBillingBlock | None = None,
    receipt: JobLaunchReceipt | None = None,
) -> QuotaPlan:
    """Model monthly suppression; evidence/flags are *not* a trust boundary."""
    if not _utc(now_utc) or type(account) is not str or not account:
        return _hold("INVALID_CURRENT_CONTEXT")
    month = now_utc.strftime("%Y-%m")
    if flag is not None:
        if (type(flag) is not MonthlyBillingBlock
                or type(flag.account) is not str or flag.account != account
                or type(flag.billing_month) is not str
                or not _MONTH.fullmatch(flag.billing_month)
                or flag.reason != "BILLING_BLOCKED"
                or type(flag.check_run_id) is not int or flag.check_run_id <= 0
                or type(flag.source_verified) is not bool or not flag.source_verified):
            return _hold("UNTRUSTED_BILLING_BLOCK_FLAG")
        if flag.billing_month > month:
            return _hold("FUTURE_BILLING_BLOCK_FLAG")
        if flag.billing_month == month:
            return _plan("FALLBACK_CANDIDATE", "CURRENT_MONTH_BILLING_BLOCK_NOT_QUOTA")
        # Older month: logical expiry, do not reuse or silently extend.
    if receipt is not None:
        return classify_job_launch(receipt, now_utc, account)
    return _plan("QUERY_BILLING", "NO_CURRENT_MONTH_BLOCK_EVIDENCE")


__all__ = [
    "JobLaunchReceipt", "MonthlyBillingBlock", "classify_job_launch",
    "plan_monthly_billing_block",
]
