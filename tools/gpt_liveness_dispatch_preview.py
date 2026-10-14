"""Composed, strictly read-only KAEP liveness dispatch preview.

Uses F6 source-of-truth owning-Issue allowlist, F4 probe plan, and F5 GitHub
comment identity validation. NEVER calls a sender, or grants Claim authority.
A READY preview is not enrollment, authorization, or a live model proof.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from tools.kaep_mailbox_codec import InvalidMessage
from tools.gpt_liveness_fleet_plan import (
    MAILBOX, fetch_owning_issue, parse_manifest, plan as admission_plan,
)
from tools.gpt_liveness_evidence import validated_comments
from tools.gpt_liveness_pilot import plan as pilot_plan
from tools.kaep_inbox_reader import fetch_gh_pages

DUMMY_NONCE = "0" * 32


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def compose(*, manifest: str, snapshots: dict[str, Any],
            pages: dict[str, str], now: datetime) -> dict[str, Any]:
    """Return advisory per-target eligibility; no dispatch or reservation.

    Comments are validated via the existing KAEP issue-identity path. A
    deterministic nonce is used solely to exercise the F4 eligibility
    planner, and the generated payload is NEVER emitted to the caller.
    """
    target_ids = parse_manifest(manifest)
    if type(pages) is not dict or not set(pages).issubset(set(target_ids)):
        _fail("INVALID_PAGES_SCOPE")
    admitted = admission_plan(manifest=manifest, snapshots=snapshots, now=now)
    results: list[dict[str, Any]] = []
    for current in admitted["targets"]:
        target = current["mailbox_ref"]
        entry: dict[str, Any] = {
            "mailbox_ref": target,
            "admission": current["status"],
            "dispatch_state": "NOT_ENROLLED",
            "would_ping_if_authorized": False,
            "may_send": False,
            "claim_authority": False,
            "gpt_currently_alive_proven": False,
        }
        status = current["status"]
        if status == "ACTIVE_ENROLLMENT_REPORTED":
            if target not in pages or type(pages[target]) is not str:
                _fail("MISSING_ACTIVE_MAILBOX")
            match = MAILBOX.fullmatch(target)
            if match is None:
                _fail("INVALID_TARGET")
            comments = validated_comments(
                pages[target], repository=match.group(1), issue=int(match.group(2)))
            decision = pilot_plan(
                body=snapshots[target]["body"],
                comments=comments, repo=match.group(1),
                issue=int(match.group(2)), now=now, nonce=DUMMY_NONCE,
            )
            entry["dispatch_state"] = decision["status"]
            # An eligibility bit conveys only a hypothetical future action.
            entry["would_ping_if_authorized"] = decision["status"] == "READY"
            if "unanswered" in decision:
                entry["unanswered"] = decision["unanswered"]
            if decision["status"] == "READY":
                entry["idempotency_key_preview"] = decision["request_key"]
            elif "expected_until" in decision:
                entry["expected_until"] = decision["expected_until"]
        elif status == "LONG_RUNNING_DECLARED":
            entry["dispatch_state"] = "LONG_RUNNING"
            entry["expected_until"] = current["long_running_until"]
        elif status in ("NO_ACTIVE_ENROLLMENT", "CLOSED_OR_NO_ENROLLMENT"):
            entry["dispatch_state"] = status
        else:
            _fail("UNKNOWN_ADMISSION")
        results.append(entry)
    return {
        "schema": "gpt-liveness-dispatch-preview.v0.1",
        "targets": results,
        "target_count": len(results),
        "read_only": True,
        "simulation_only": True,
        "deployment_authorized": False,
        "any_current_gpt_alive_proven": False,
        "claim_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true",
                        help="GET allowlisted GitHub Issues / KAEP comments, never POST")
    source.add_argument("--fixture", type=Path,
                        help="JSON {snapshots, pages} for deterministic offline tests")
    args = parser.parse_args(argv)
    try:
        raw = args.manifest.read_text(encoding="utf-8")
        targets = parse_manifest(raw)
        now = datetime.now(timezone.utc)
        if args.live:
            snapshots = {ref: fetch_owning_issue(ref) for ref in targets}
            admitted = admission_plan(manifest=raw, snapshots=snapshots, now=now)
            active = {row["mailbox_ref"] for row in admitted["targets"]
                      if row["status"] == "ACTIVE_ENROLLMENT_REPORTED"}
            pages = {
                ref: fetch_gh_pages(MAILBOX.fullmatch(ref).group(1),
                                    int(MAILBOX.fullmatch(ref).group(2)))
                for ref in targets if ref in active
            }
        else:
            raw_fixture = args.fixture.read_text(encoding="utf-8")
            if len(raw_fixture) > 6_000_000:
                _fail("OVERSIZED_FIXTURE")
            fixture = json.loads(raw_fixture)
            if type(fixture) is not dict or set(fixture) != {"snapshots", "pages"}:
                _fail("INVALID_FIXTURE")
            snapshots, pages = fixture["snapshots"], fixture["pages"]
        preview = compose(manifest=raw, snapshots=snapshots, pages=pages, now=now)
        print(json.dumps(preview, sort_keys=True, ensure_ascii=False))
        return 0
    except (InvalidMessage, ValueError, OSError, UnicodeError, TypeError) as exc:
        code = str(exc) if isinstance(exc, InvalidMessage) else "READ_ONLY_IO_FAILURE"
        print(json.dumps({"status": "BLOCKED", "reason_code": code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
