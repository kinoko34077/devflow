"""Read-only personal GitHub Billing Overview observation (#752).

The existing REST summary cannot prove included Compute quota. This adapter
normalizes the two authenticated browser UI pages without handling tokens.
It provides a separate advisory source, not a job-launch receipt, Claim,
runner permission, or successful GitHub Check.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

SCHEMA = "devflow.github-billing-ui-observation.v1"
REQUEST_SCHEMA = "devflow.github-billing-ui-request.v1"
SOURCE = "github_personal_billing_settings_ui"
MAX_JSON = 32768
MAX_AGE = timedelta(hours=12)
REQUEST_AGE = timedelta(minutes=30)
REPLAY_RETENTION = timedelta(days=7)
_ACCOUNT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_MONEY = r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?"
_NUMBER = r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?"
_REQ_ID = re.compile(r"^[a-f0-9]{32}$")
_MARKER = re.compile(r"^billing-request-([0-9]{8}T[0-9]{6}Z)-([a-f0-9]{32})\.request$")
_IDLE_MARKER = "billing-request-idle.request"
_MONTHS = (
    "", "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)
_MONEY_FIELDS = (
    "gross_metered_usd", "included_discount_usd",
    "actions_consumed_usd", "actions_discount_usd", "actions_billable_usd",
    "compute_used_usd", "compute_included_usd",
    "actions_budget_spent_usd", "actions_budget_limit_usd",
)
_STORAGE_FIELDS = ("storage_used_gb", "storage_included_gb")


class ObservationUnavailable(ValueError):
    """Bounded non-sensitive error, safe to emit to calling agents."""


def _utc(now: datetime) -> datetime:
    if (not isinstance(now, datetime) or now.tzinfo is None
            or now.utcoffset() != timedelta(0)):
        raise ObservationUnavailable("UTC_CLOCK_REQUIRED")
    return now


def _account(value: str) -> str:
    if not isinstance(value, str) or not _ACCOUNT.fullmatch(value):
        raise ObservationUnavailable("INVALID_ACCOUNT")
    return value


def _match(value: object, pattern: str) -> re.Match[str]:
    if not isinstance(value, str) or len(value) > 250:
        raise ObservationUnavailable("BILLING_FIELD_INVALID")
    match = re.fullmatch(pattern, value)
    if match is None:
        raise ObservationUnavailable("BILLING_FIELD_INVALID")
    return match


def _decimal(value: str, *, money: bool) -> str:
    _match(value, _MONEY if money else _NUMBER)
    try:
        number = Decimal(value.replace(",", ""))
        if not number.is_finite() or number < 0 or number > Decimal("1000000000"):
            raise ObservationUnavailable("BILLING_NUMBER_OUT_OF_RANGE")
        return format(number, ".2f") if money else format(number.normalize(), "f")
    except InvalidOperation as exc:
        raise ObservationUnavailable("BILLING_NUMBER_INVALID") from exc


def _money(value: object) -> str:
    return _decimal(_match(value, r"\$(" + _MONEY + r")").group(1), money=True)


def _state(data: dict) -> str:
    used = Decimal(data["compute_used_usd"])
    cap = Decimal(data["compute_included_usd"])
    if used >= cap:
        if data["actions_budget_usage_blocked"] is True:
            return "INCLUDED_COMPUTE_AT_OR_ABOVE_LIMIT_AND_BUDGET_BLOCKED"
        return "INCLUDED_COMPUTE_AT_OR_ABOVE_LIMIT"
    # A $0 additional budget can be blocked even while included Compute
    # remains. Keep both independent observations visible to MCP consumers.
    if data["actions_budget_usage_blocked"] is True:
        return "WITHIN_INCLUDED_COMPUTE_AND_BUDGET_BLOCKED"
    return "WITHIN_INCLUDED_COMPUTE"


def normalize_ui(raw: object, account: str, now_utc: datetime) -> dict:
    """Accept only the allowlisted fields from the fixed UI adapter."""
    account, now_utc = _account(account), _utc(now_utc)
    if not isinstance(raw, dict) or raw.get("account") != account:
        raise ObservationUnavailable("BILLING_ACCOUNT_MISMATCH")
    month = _MONTHS[now_utc.month]
    last_day = calendar.monthrange(now_utc.year, now_utc.month)[1]
    period = f"{month} 1 - {month} {last_day}, {now_utc.year}."
    if (raw.get("period") != "Gross metered usage for " + period or
            raw.get("discount_period") != "Included usage discounts for " + period):
        raise ObservationUnavailable("BILLING_PERIOD_NOT_CURRENT_UTC_MONTH")
    compute = _match(raw.get("compute"), r"\$(" + _MONEY + r") used / \$(" + _MONEY + r") included")
    storage = _match(raw.get("storage"), r"(" + _NUMBER + r") GB used / (" + _NUMBER + r") GB included")
    budget = _match(raw.get("budget_amount"), r"\$(" + _MONEY + r") / \$(" + _MONEY + r") spent")
    state = _match(raw.get("budget_state"), r"([0-9]+)% of budget limit used ([0-9]+)%( Usage blocked)?")
    if state.group(1) != state.group(2):
        raise ObservationUnavailable("BUDGET_STATUS_INCONSISTENT")
    data = {
        "schema": SCHEMA, "source": SOURCE,
        "account": account,
        "observed_at_utc": now_utc.isoformat(),
        "billing_month": now_utc.strftime("%Y-%m"),
        "gross_metered_usd": _money(raw.get("gross")),
        "included_discount_usd": _money(raw.get("included_discount")),
        "actions_consumed_usd": _money(raw.get("consumed")),
        "actions_discount_usd": _money(raw.get("actions_discount")),
        "actions_billable_usd": _money(raw.get("billable")),
        "compute_used_usd": _decimal(compute.group(1), money=True),
        "compute_included_usd": _decimal(compute.group(2), money=True),
        "storage_used_gb": _decimal(storage.group(1), money=False),
        "storage_included_gb": _decimal(storage.group(2), money=False),
        "actions_budget_spent_usd": _decimal(budget.group(1), money=True),
        "actions_budget_limit_usd": _decimal(budget.group(2), money=True),
        # The absence of the known "Usage blocked" UI label is not proof
        # that spending, or any specific job launch, is allowed.
        "actions_budget_usage_blocked": True if state.group(3) else None,
        "verified_for_dispatch": False,
    }
    data["status"] = _state(data)
    return data


def _read_json(path: Path) -> object:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_JSON + 1)
        if len(payload) > MAX_JSON:
            raise ObservationUnavailable("OBSERVATION_FILE_TOO_LARGE")
        return json.loads(payload.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ObservationUnavailable("OBSERVATION_FILE_UNAVAILABLE") from exc


def load_cached_observation(path: Path, account: str, now_utc: datetime) -> dict:
    """Shared read-only verified cache boundary for CLI and local MCP.

    In particular, a raw JSON file's claimed status or fresh timestamp
    cannot authorize any execution path.
    """
    return validate_cached(_read_json(path), account, now_utc)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ObservationUnavailable("OBSERVATION_TIMESTAMP_INVALID")
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ObservationUnavailable("OBSERVATION_TIMESTAMP_INVALID") from exc


def validate_cached(raw: object, account: str, now_utc: datetime) -> dict:
    """No caller-supplied cache becomes authenticated execution authority."""
    account, now_utc = _account(account), _utc(now_utc)
    if (not isinstance(raw, dict) or raw.get("schema") != SCHEMA
            or raw.get("source") != SOURCE or raw.get("account") != account
            or raw.get("verified_for_dispatch") is not False):
        raise ObservationUnavailable("OBSERVATION_SOURCE_INVALID")
    stamp = _parse_timestamp(raw.get("observed_at_utc"))
    age = now_utc - stamp
    if (age < timedelta(0) or age > MAX_AGE
            or stamp.strftime("%Y-%m") != now_utc.strftime("%Y-%m")
            or raw.get("billing_month") != now_utc.strftime("%Y-%m")):
        raise ObservationUnavailable("OBSERVATION_STALE_OR_FUTURE")
    if raw.get("status") == "UNKNOWN":
        raise ObservationUnavailable("LATEST_OBSERVATION_UNAVAILABLE")
    data = {k: raw.get(k) for k in (
        "schema", "source", "account", "observed_at_utc",
        "billing_month", "verified_for_dispatch", "actions_budget_usage_blocked",
        *_MONEY_FIELDS, *_STORAGE_FIELDS,
    )}
    for field in _MONEY_FIELDS:
        value = data[field]
        if not isinstance(value, str) or _decimal(value, money=True) != value:
            raise ObservationUnavailable("OBSERVATION_MONEY_INVALID")
    for field in _STORAGE_FIELDS:
        value = data[field]
        if not isinstance(value, str) or _decimal(value, money=False) != value:
            raise ObservationUnavailable("OBSERVATION_STORAGE_INVALID")
    if data["actions_budget_usage_blocked"] is not True and data["actions_budget_usage_blocked"] is not None:
        raise ObservationUnavailable("OBSERVATION_BUDGET_STATUS_INVALID")
    data["status"] = _state(data)
    if raw.get("status") != data["status"]:
        raise ObservationUnavailable("OBSERVATION_STATUS_INCONSISTENT")
    request_id = raw.get("request_id")
    if request_id is not None:
        if not isinstance(request_id, str) or not _REQ_ID.fullmatch(request_id):
            raise ObservationUnavailable("OBSERVATION_REQUEST_ID_INVALID")
        data["request_id"] = request_id
    return data


def parse_request(raw: object, account: str, now_utc: datetime) -> str:
    """Fixed account and single read-only operation; no code, paths or URLs."""
    account, now_utc = _account(account), _utc(now_utc)
    if (not isinstance(raw, dict) or set(raw) != {
        "schema", "account", "action", "request_id", "requested_at_utc"
    } or raw.get("schema") != REQUEST_SCHEMA or raw.get("account") != account
            or raw.get("action") != "OBSERVE_BILLING"):
        raise ObservationUnavailable("BILLING_REQUEST_INVALID")
    request_id = raw.get("request_id")
    if not isinstance(request_id, str) or not _REQ_ID.fullmatch(request_id):
        raise ObservationUnavailable("BILLING_REQUEST_ID_INVALID")
    age = now_utc - _parse_timestamp(raw.get("requested_at_utc"))
    if age < timedelta(0) or age > REQUEST_AGE:
        raise ObservationUnavailable("BILLING_REQUEST_EXPIRED_OR_FUTURE")
    return request_id


def parse_marker_directory(directory: Path, account: str, now_utc: datetime) -> str | None:
    """A sync-directory filename can request just the fixed observation.

    The content is never opened, and the filename cannot choose commands,
    URLs, credentials, output paths or accounts. A stale/duplicate marker
    must not trigger a new observation.
    """
    try:
        markers = [p.name for p in directory.iterdir()
                   if p.name.startswith("billing-request-")
                   and p.name.endswith(".request")]
    except OSError as exc:
        raise ObservationUnavailable("BILLING_REQUEST_DIRECTORY_UNAVAILABLE") from exc
    if not markers or markers == [_IDLE_MARKER]:
        return None
    if len(markers) != 1:
        raise ObservationUnavailable("BILLING_REQUEST_MARKER_AMBIGUOUS")
    match = _MARKER.fullmatch(markers[0])
    if not match:
        raise ObservationUnavailable("BILLING_REQUEST_MARKER_INVALID")
    try:
        stamp = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ObservationUnavailable("BILLING_REQUEST_TIMESTAMP_INVALID") from exc
    # An expired mailbox marker is no pending work, not a reason to
    # reopen the browser or repeatedly fail a periodic mailbox poll.
    if _utc(now_utc) - stamp > REQUEST_AGE:
        return None
    return parse_request({
        "schema": REQUEST_SCHEMA, "account": account,
        "action": "OBSERVE_BILLING", "request_id": match.group(2),
        "requested_at_utc": stamp.isoformat(),
    }, account, now_utc)


def reserve_request(path: Path, account: str, request_id: str, now_utc: datetime) -> bool:
    """Durable local at-most-once reservation, independent of output/cache.

    Reserve before capture. A crash or failed observation is not retried
    implicitly; the requester can issue a new nonce. This is not Claim.
    """
    account, now_utc = _account(account), _utc(now_utc)
    if not _REQ_ID.fullmatch(request_id) or not path.parent.is_dir():
        raise ObservationUnavailable("BILLING_REQUEST_LEDGER_INVALID")
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS observed_requests (
                account TEXT NOT NULL, request_id TEXT NOT NULL,
                reserved_at_utc TEXT NOT NULL, PRIMARY KEY(account, request_id)
            )
        """)
        conn.execute("DELETE FROM observed_requests WHERE reserved_at_utc < ?",
                     ((now_utc - REPLAY_RETENTION).isoformat(),))
        inserted = conn.execute(
            "INSERT OR IGNORE INTO observed_requests VALUES (?, ?, ?)",
            (account.casefold(), request_id, now_utc.isoformat()),
        ).rowcount
        conn.execute("COMMIT")
        return inserted == 1
    except (sqlite3.Error, OSError) as exc:
        raise ObservationUnavailable("BILLING_REQUEST_LEDGER_UNAVAILABLE") from exc
    finally:
        if conn is not None:
            conn.close()


def _request_ledger_path(path: Path | None) -> Path:
    if path is not None:
        return path
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        raise ObservationUnavailable("LOCAL_REQUEST_LEDGER_REQUIRED")
    parent = Path(local_appdata) / "KiNoTch" / "devflow-billing-observer"
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ObservationUnavailable("LOCAL_REQUEST_LEDGER_DIRECTORY_UNAVAILABLE") from exc
    return parent / "billing-request-ledger.sqlite3"


def _atomic_write(path: Path, data: dict) -> None:
    # Explicit output path chosen by local operator, never by remote request.
    # No raw page/UI text, token, or arbitrary request body in the cache.
    if not path.parent.is_dir():
        raise ObservationUnavailable("OBSERVATION_OUTPUT_PARENT_MISSING")
    pending = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".billing-", suffix=".tmp", delete=False
        ) as out:
            pending = Path(out.name)
            json.dump(data, out, ensure_ascii=True, indent=2)
            out.write("\n")
        os.replace(pending, path)
    except OSError as exc:
        raise ObservationUnavailable("OBSERVATION_OUTPUT_WRITE_FAILED") from exc
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def _collect(account: str) -> dict:
    _account(account)
    if os.name != "nt":
        raise ObservationUnavailable("INTERACTIVE_WINDOWS_HOST_REQUIRED")
    adapter = Path(__file__).resolve().with_suffix(".ps1")
    before = datetime.now(timezone.utc)
    try:
        response = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
             str(adapter), "-Account", account],
            capture_output=True, encoding="utf-8", errors="strict",
            timeout=75, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ObservationUnavailable("BILLING_UI_ADAPTER_UNAVAILABLE") from exc
    if response.returncode != 0 or len(response.stdout) > MAX_JSON:
        reason = response.stderr.strip()
        if not re.fullmatch(r"[A-Z_]{8,80}", reason):
            reason = "BILLING_UI_OBSERVATION_FAILED"
        raise ObservationUnavailable(reason)
    try:
        raw = json.loads(response.stdout)
    except json.JSONDecodeError as exc:
        raise ObservationUnavailable("BILLING_UI_OUTPUT_INVALID") from exc
    now = datetime.now(timezone.utc)
    if now.strftime("%Y-%m") != before.strftime("%Y-%m"):
        raise ObservationUnavailable("BILLING_MONTH_CHANGED_DURING_OBSERVATION")
    return normalize_ui(raw, account, now)


def status_view(data: dict) -> dict:
    """Safe reduced output for CI logs; cache destination still must be private."""
    return {key: data[key] for key in (
        "schema", "source", "observed_at_utc", "billing_month", "status",
        "verified_for_dispatch", "actions_budget_usage_blocked",
        "request_id", "reason"
    ) if key in data}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--account", required=True)
    p.add_argument("--cache", type=Path)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--read-cache", action="store_true")
    mode.add_argument("--serve-request", type=Path, metavar="REQUEST_JSON")
    mode.add_argument("--serve-marker-dir", type=Path, metavar="REQUEST_DIRECTORY")
    p.add_argument("--status-only", action="store_true")
    p.add_argument("--request-ledger", type=Path, help="Local non-synced SQLite request reservation ledger")
    args = p.parse_args(argv)
    request_id = None
    collecting = False
    try:
        _account(args.account)
        now = datetime.now(timezone.utc)
        if args.read_cache:
            if args.cache is None:
                raise ObservationUnavailable("CACHE_PATH_REQUIRED")
            data = load_cached_observation(args.cache, args.account, now)
        else:
            if args.serve_request is not None or args.serve_marker_dir is not None:
                if args.cache is None:
                    raise ObservationUnavailable("CACHE_PATH_REQUIRED")
                if args.serve_marker_dir is not None:
                    request_id = parse_marker_directory(args.serve_marker_dir, args.account, now)
                else:
                    if args.serve_request.resolve() == args.cache.resolve():
                        raise ObservationUnavailable("REQUEST_AND_CACHE_MUST_DIFFER")
                    if args.serve_request.is_file():
                        request_id = parse_request(_read_json(args.serve_request), args.account, now)
                if request_id is None:
                    print(json.dumps({"status": "NO_REQUEST", "verified_for_dispatch": False}))
                    return 0
                # Independent local ledger prevents A -> B -> delayed A,
                # even when direct reads replace the latest cache.
                ledger = _request_ledger_path(args.request_ledger)
                if ledger.resolve() == args.cache.resolve():
                    raise ObservationUnavailable("REQUEST_LEDGER_AND_CACHE_MUST_DIFFER")
                reserved = reserve_request(ledger, args.account, request_id, now)
                try:
                    previous = _read_json(args.cache)
                except ObservationUnavailable:
                    previous = None
                migrated = (isinstance(previous, dict)
                            and previous.get("schema") == SCHEMA
                            and previous.get("account") == args.account
                            and previous.get("request_id") == request_id)
                if not reserved or migrated:
                    print(json.dumps({"status": "REQUEST_ALREADY_HANDLED",
                                      "request_id": request_id,
                                      "verified_for_dispatch": False}))
                    return 0
            collecting = True
            data = _collect(args.account)
            if request_id is not None:
                data["request_id"] = request_id
            if args.cache is not None:
                _atomic_write(args.cache, data)
        print(json.dumps(status_view(data) if args.status_only else data))
        return 0
    except (ObservationUnavailable, OSError) as exc:
        # Failure never leaves a prior successful observation appearing fresh.
        stamp = datetime.now(timezone.utc)
        failure = {"schema": SCHEMA, "source": SOURCE,
                   "account": args.account, "observed_at_utc": stamp.isoformat(),
                   "billing_month": stamp.strftime("%Y-%m"), "status": "UNKNOWN",
                   "reason": str(exc) if isinstance(exc, ObservationUnavailable) else "BILLING_IO_ERROR",
                   "verified_for_dispatch": False}
        if request_id is not None:
            failure["request_id"] = request_id
        if collecting and args.cache is not None:
            try:
                _atomic_write(args.cache, failure)
            except (ObservationUnavailable, OSError):
                failure["cache_write_failed"] = True
        print(json.dumps(status_view(failure) if args.status_only else failure))
        return 2


if __name__ == "__main__":
    sys.exit(main())
