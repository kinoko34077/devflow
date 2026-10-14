"""Advisory, read-only GPT liveness fleet admission and idle scheduler cost plan.

Not a sender, session authority, provider wake-up mechanism or authentication
service. The only registration source is the current owning GitHub Issue body.
The caller-maintained allowlist is NOT enrollment and never grants Claim rights.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from tools.gpt_liveness_pilot import enrollment, utc
from tools.kaep_mailbox_codec import InvalidMessage

SCHEMA = "gpt-liveness-fleet-plan.v0.1"
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MAILBOX = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)\Z")
MAX_TARGETS = 12
MAX_ISSUE_BYTES = 200_000
TICKS_PER_DAY = 24 * 60 // 5
THIRTY_DAY_TICKS = 30 * TICKS_PER_DAY


def _fail(reason: str) -> None:
    raise InvalidMessage(reason)


def parse_manifest(raw: str) -> list[str]:
    """Return exact allowlisted targets. No implicit fleet membership."""
    if type(raw) is not str or len(raw) > 3_000:
        _fail("MANIFEST_TOO_LARGE")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        _fail("INVALID_MANIFEST_JSON")
    if type(data) is not dict or set(data) != {"schema", "targets"}:
        _fail("INVALID_MANIFEST_SCHEMA")
    if data["schema"] != SCHEMA or type(data["targets"]) is not list:
        _fail("INVALID_MANIFEST_SCHEMA")
    if len(data["targets"]) > MAX_TARGETS:
        _fail("TOO_MANY_TARGETS")
    found: set[str] = set()
    for target in data["targets"]:
        if type(target) is not str or MAILBOX.fullmatch(target) is None:
            _fail("INVALID_TARGET")
        folded = target.casefold()
        if folded in found:
            _fail("DUPLICATE_TARGET")
        found.add(folded)
    return data["targets"]


def validate_snapshot(record: dict[str, Any], *, target: str) -> tuple[str, str]:
    """Read-only GitHub Issue identity/state; never accept a comment as an enrollment."""
    match = MAILBOX.fullmatch(target)
    if not match:
        _fail("INVALID_TARGET")
    if type(record) is not dict or set(record) != {"repository", "number", "state", "body"}:
        _fail("INVALID_ISSUE_SNAPSHOT")
    if (record["repository"].casefold() != match.group(1).casefold()
            or type(record["number"]) is not int
            or record["number"] != int(match.group(2))):
        _fail("ISSUE_IDENTITY_MISMATCH")
    if record["state"] not in ("open", "closed"):
        _fail("INVALID_ISSUE_STATE")
    if type(record["body"]) is not str or len(record["body"]) > MAX_ISSUE_BYTES:
        _fail("INVALID_ISSUE_BODY")
    return record["state"], record["body"]


def plan(*, manifest: str, snapshots: dict[str, Any], now: datetime) -> dict[str, Any]:
    if now.tzinfo is None or now.utcoffset().total_seconds() != 0:
        _fail("INVALID_PLAN_TIME")
    targets = parse_manifest(manifest)
    if type(snapshots) is not dict:
        _fail("INVALID_SNAPSHOTS")
    if set(snapshots.keys()) != set(targets):
        _fail("SNAPSHOT_SET_MISMATCH")
    result: list[dict[str, Any]] = []
    for target in targets:
        state, body = validate_snapshot(snapshots[target], target=target)
        row: dict[str, Any] = {"mailbox_ref": target, "status": "CLOSED_OR_NO_ENROLLMENT",
                               "may_send": False, "gpt_alive_proven": False,
                               "claim_authority": False}
        if state == "open":
            registration = enrollment(body, now=now)  # existing strict canonical parser
            if registration is None:
                row["status"] = "NO_ACTIVE_ENROLLMENT"
            elif registration.get("long_running_until") is not None and utc(
                    registration["long_running_until"]) > now:
                row["status"] = "LONG_RUNNING_DECLARED"
                row["registration_expires_at"] = registration["expires_at"]
                row["long_running_until"] = registration["long_running_until"]
            else:
                row["status"] = "ACTIVE_ENROLLMENT_REPORTED"
                row["registration_expires_at"] = registration["expires_at"]
            if registration is not None:
                row["session_id"] = registration["session_id"]
                row["turn_id"] = registration["turn_id"]
        result.append(row)

    repository_count = len({MAILBOX.fullmatch(x).group(1).casefold() for x in targets})
    return {
        "schema": "gpt-liveness-fleet-advisory.v0.1",
        "target_count": len(targets),
        "target_repositories": repository_count,
        "targets": result,
        "idle_cost_model": {
            "cron_interval_minutes": 5,
            "nominal_ticks_per_30_days_per_workflow": THIRTY_DAY_TICKS,
            "replicated_per_repo_nominal_ticks_30d": THIRTY_DAY_TICKS * repository_count,
            "single_central_workflow_nominal_ticks_30d": THIRTY_DAY_TICKS,
            "github_delivery_exact": False,
            "billable_minutes_estimated": False,
        },
        "projection_only": True,
        "read_only": True,
        "any_current_gpt_alive_proven": False,
        "claim_authority": False,
        "deployment_authorized": False,
    }


def fetch_owning_issue(target: str) -> dict[str, Any]:
    """One exact GitHub API GET, with no access to secrets, POST or session tokens."""
    match = MAILBOX.fullmatch(target)
    if not match:
        _fail("INVALID_TARGET")
    repo, number = match.group(1), int(match.group(2))
    process = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github+json",
                              f"/repos/{repo}/issues/{number}"],
                             capture_output=True, text=True, timeout=30, check=False)
    if process.returncode or len(process.stdout) > MAX_ISSUE_BYTES * 2:
        _fail("ISSUE_READ_FAILED")
    try:
        raw = json.loads(process.stdout)
    except ValueError:
        _fail("INVALID_GITHUB_RESPONSE")
    if (type(raw) is not dict or raw.get("number") != number
            or raw.get("repository_url") != f"https://api.github.com/repos/{repo}"):
        _fail("ISSUE_IDENTITY_MISMATCH")
    return {"repository": repo, "number": number,
            "state": raw.get("state"), "body": raw.get("body")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="explicit owner-maintained allowlist JSON; empty targets by default")
    mutex = parser.add_mutually_exclusive_group(required=True)
    mutex.add_argument("--live", action="store_true", help="read exact allowlisted GitHub Issues via gh GET")
    mutex.add_argument("--snapshots", type=Path, help="offline Issue snapshots JSON, projection only")
    args = parser.parse_args(argv)
    try:
        contents = args.manifest.read_text(encoding="utf-8")
        targets = parse_manifest(contents)
        if args.live:
            bodies = {t: fetch_owning_issue(t) for t in targets}
        else:
            bodies = json.loads(args.snapshots.read_text(encoding="utf-8"))
        summary = plan(manifest=contents, snapshots=bodies, now=datetime.now(timezone.utc))
        print(json.dumps(summary, sort_keys=True))
        return 0
    except (InvalidMessage, ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        code = str(exc) if isinstance(exc, InvalidMessage) else "READ_ONLY_IO_FAILURE"
        print(json.dumps({"status": "BLOCKED", "reason_code": code}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
