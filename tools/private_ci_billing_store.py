"""Local, token-free SQLite observation journal for Private CI, devflow #752.

State is account-scoped and durable, but NOT authenticated authority.  Reads
from this file must never directly launch a runner or mint successful checks.
The caller must separately verify GitHub identities and privileges.
No network, credential access, background task or executor lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from tools.private_ci_billing_block import JobLaunchReceipt, classify_job_launch

_JST = timezone(timedelta(hours=9))
_DAILY_KINDS = frozenset({
    "REPORT_RECEIVED_INCONCLUSIVE",
    "BILLING_API_UNAVAILABLE",
    "BILLING_AUTH_UNAVAILABLE",
})


@dataclass(frozen=True)
class BillingBlockSnapshot:
    account: str
    billing_month: str
    check_run_id: int
    repository: str
    recorded_at_utc: str
    # Deliberately not a verified/executable MonthFlag.
    verified_for_dispatch: bool = False


@dataclass(frozen=True)
class DailyObservationSnapshot:
    account: str
    date_jst: str
    billing_month: str
    observation: str
    recorded_at_utc: str


def _check_account(account: object) -> str:
    if (type(account) is not str or not account or len(account) > 39
            or not all(c.isascii() and (c.isalnum() or c == "-")
                       for c in account)
            or account[0] == "-" or account[-1] == "-"):
        raise ValueError("INVALID_ACCOUNT")
    return account


def _check_now(now: object) -> datetime:
    if (type(now) is not datetime or now.tzinfo is None
            or now.utcoffset() != timedelta(0)):
        raise ValueError("UTC_TIME_REQUIRED")
    return now


class LocalBillingObservationStore:
    """Caller-chosen SQLite file; own-user file permissions are prerequisite."""

    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        if not path.parent.is_dir() or not path.name:
            raise ValueError("EXISTING_PARENT_DIRECTORY_REQUIRED")
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_observations(
                account TEXT NOT NULL,
                date_jst TEXT NOT NULL,
                billing_month TEXT NOT NULL,
                observation TEXT NOT NULL,
                recorded_at_utc TEXT NOT NULL,
                PRIMARY KEY (account, billing_month, date_jst)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monthly_billing_blocks(
                account TEXT NOT NULL,
                billing_month TEXT NOT NULL,
                check_run_id INTEGER NOT NULL,
                repository TEXT NOT NULL,
                recorded_at_utc TEXT NOT NULL,
                PRIMARY KEY (account, billing_month)
            )
        """)
        return conn

    def record_daily(
        self, account: str, now_utc: datetime, observation: str,
    ) -> DailyObservationSnapshot:
        """Store one sanitized observation per JST date; duplicates idempotent."""
        account = _check_account(account)
        now_utc = _check_now(now_utc)
        if type(observation) is not str or observation not in _DAILY_KINDS:
            raise ValueError("INVALID_DAILY_OBSERVATION")
        day = now_utc.astimezone(_JST).strftime("%Y-%m-%d")
        month = now_utc.strftime("%Y-%m")
        iso = now_utc.isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT OR IGNORE INTO daily_observations
                VALUES (?, ?, ?, ?, ?)
            """, (account, day, month, observation, iso))
            row = conn.execute("""
                SELECT account, date_jst, billing_month, observation,
                       recorded_at_utc
                FROM daily_observations
                WHERE account = ? AND billing_month = ? AND date_jst = ?
            """, (account, month, day)).fetchone()
            if row[:4] != (account, day, month, observation):
                raise ValueError("CONFLICTING_DAILY_OBSERVATION")
            conn.execute("COMMIT")
            return DailyObservationSnapshot(*row)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def read_daily(
        self, account: str, now_utc: datetime,
    ) -> DailyObservationSnapshot | None:
        account = _check_account(account)
        now_utc = _check_now(now_utc)
        day = now_utc.astimezone(_JST).strftime("%Y-%m-%d")
        with closing(self._connect()) as conn:
            row = conn.execute("""
                SELECT account, date_jst, billing_month, observation,
                       recorded_at_utc
                FROM daily_observations
                WHERE account = ? AND billing_month = ? AND date_jst = ?
            """, (account, now_utc.strftime("%Y-%m"), day)).fetchone()
        if row is None:
            return None
        if row[2] != now_utc.strftime("%Y-%m") or row[3] not in _DAILY_KINDS:
            raise ValueError("STALE_OR_TAMPERED_DAILY_OBSERVATION")
        return DailyObservationSnapshot(*row)

    def record_launch_block(
        self, receipt: JobLaunchReceipt, now_utc: datetime,
    ) -> BillingBlockSnapshot:
        """Journal proposed block from typed observed evidence; NOT approval."""
        now_utc = _check_now(now_utc)
        if type(receipt) is not JobLaunchReceipt:
            raise ValueError("INVALID_RECEIPT")
        account = _check_account(receipt.account)
        decision = classify_job_launch(receipt, now_utc, account)
        if decision.action != "RECORD_BILLING_BLOCK":
            raise ValueError("BLOCK_EVIDENCE_NOT_ADMISSIBLE_FOR_JOURNAL")
        month = now_utc.strftime("%Y-%m")
        row = (account, month, receipt.job_id, receipt.repository,
               now_utc.isoformat())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT OR IGNORE INTO monthly_billing_blocks
                VALUES (?, ?, ?, ?, ?)
            """, row)
            stored = conn.execute("""
                SELECT account, billing_month, check_run_id, repository,
                       recorded_at_utc
                FROM monthly_billing_blocks
                WHERE account = ? AND billing_month = ?
            """, (account, month)).fetchone()
            if stored[:4] != row[:4]:
                raise ValueError("CONFLICTING_MONTHLY_EVIDENCE")
            conn.execute("COMMIT")
            return BillingBlockSnapshot(*stored)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def read_monthly_block(
        self, account: str, now_utc: datetime,
    ) -> BillingBlockSnapshot | None:
        """Return only matching UTC month; never trust old month implicitly."""
        account = _check_account(account)
        month = _check_now(now_utc).strftime("%Y-%m")
        with closing(self._connect()) as conn:
            row = conn.execute("""
                SELECT account, billing_month, check_run_id, repository,
                       recorded_at_utc
                FROM monthly_billing_blocks
                WHERE account = ? AND billing_month = ?
            """, (account, month)).fetchone()
        if row is None:
            return None
        if (type(row[2]) is not int or row[2] <= 0
                or not row[3].startswith(account + "/")):
            raise ValueError("INVALID_STORED_MONTHLY_EVIDENCE")
        return BillingBlockSnapshot(*row)


__all__ = [
    "BillingBlockSnapshot", "DailyObservationSnapshot", "LocalBillingObservationStore",
]
