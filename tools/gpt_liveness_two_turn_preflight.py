"""CH9 two-GPT active-turn READ-ONLY preflight, no sender or privilege.

Accept exactly two explicitly designated devflow mailbox Issues. Verify live Issue
identity and active independent F4 enrollment, then preview each using canonical
F7/F5/F4 inspectors. This reports only conditional readiness, never permission
to dispatch, send, create Issue, wake GPT or mutate any Claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from tools.gpt_liveness_fleet_plan import MAILBOX, fetch_owning_issue
from tools.gpt_liveness_dispatch_preview import compose as f7_compose
from tools.gpt_liveness_turn_router import format_manifest, plan as turn_plan
from tools.kaep_inbox_reader import fetch_gh_pages
from tools.kaep_mailbox_codec import InvalidMessage

SCHEMA = "gpt.liveness.two-turn-preflight.v0.1"
ALLOWED_REPO = "kinoko34077/devflow"
EXPECTED_ACTOR = "kinoko34077"
MAX_FIXTURE_CHARS = 5_000_000


def fail(reason: str) -> None:
    raise InvalidMessage(reason)


def _targets(raw: str) -> list[str]:
    from tools.gpt_liveness_fleet_plan import parse_manifest
    found = parse_manifest(raw)
    if len(found) != 2:
        fail("EXACTLY_TWO_MAILBOXES_REQUIRED")
    for target in found:
        loc = MAILBOX.fullmatch(target)
        if loc is None or loc.group(1) != ALLOWED_REPO:
            fail("OUT_OF_SCOPE_MAILBOX")
    return found


def preflight(
    *, manifest: str, snapshots: dict[str, Any],
    pages: dict[str, str], now: datetime,
) -> dict[str, Any]:
    """Fail closed on malformed targets or cross-turn collision.

    pages must contain only active mailbox pages (never another Issue's
    comments). F5/F7 validates source URLs, GitHub REST metadata and KAEP.
    """
    targets = _targets(manifest)
    if not isinstance(pages, dict) or any(
        type(key) is not str or type(value) is not str or key not in targets
        for key, value in pages.items()
    ):
        fail("INVALID_MAILBOX_PAGES")
    turns = turn_plan(manifest=manifest, snapshots=snapshots, now=now)
    slots = turns["targets"]
    active = [s for s in slots if s["status"] == "ACTIVE_TURN_ENROLLMENT"]
    for item in slots:
        if item.get("expected_actor") not in (None, EXPECTED_ACTOR):
            fail("NON_OWNER_TURN_ACTOR")
    expected_pages = {s["mailbox_ref"] for s in active}
    if set(pages) != expected_pages:
        fail("ACTIVE_MAILBOX_SET_MISMATCH")
    f7 = f7_compose(manifest=manifest, snapshots=snapshots, pages=pages, now=now)
    if (
        f7.get("schema") != "gpt-liveness-dispatch-preview.v0.1"
        or f7.get("read_only") is not True
        or f7.get("simulation_only") is not True
        or f7.get("deployment_authorized") is not False
        or f7.get("claim_authority") is not False
        or f7.get("any_current_gpt_alive_proven") is not False
        or len(f7.get("targets", [])) != 2
    ):
        fail("INVALID_F7_SIMULATION")
    out = []
    for identity, status in zip(slots, f7["targets"]):
        if identity["mailbox_ref"] != status.get("mailbox_ref"):
            fail("F7_TURN_ROUTE_MISMATCH")
        ready = (
            identity["status"] == "ACTIVE_TURN_ENROLLMENT"
            and status.get("dispatch_state") == "READY"
            and status.get("would_ping_if_authorized") is True
            and status.get("may_send") is False
        )
        out.append({
            "mailbox_ref": identity["mailbox_ref"],
            "participant_id": identity["participant_id"],
            "session_id": identity["session_id"],
            "turn_state": identity["status"],
            "preview_state": status.get("dispatch_state"),
            "conditionally_ready": ready,
            "send_authorized": False,
        })
    # Never upgrade READY to an effectful authorization.
    complete = len(active) == 2 and all(x["conditionally_ready"] for x in out)
    return {
        "schema": SCHEMA,
        "status": "TWO_TURNS_PREVIEW_READY" if complete else "HOLD_NOT_READY",
        "targets": out,
        "has_two_distinct_active_turns": len(active) == 2,
        "deployment_authorized": False,
        "post_attempted": False,
        "write_authorized": False,
        "gpt_currently_alive_proven": False,
        "claim_authority": False,
    }


def live_inputs(raw: str, *, now: datetime) -> tuple[dict[str, Any], dict[str, str]]:
    """Fetch existing, explicitly admitted Issues and authenticated comment pages."""
    targets = _targets(raw)
    snapshots = {ref: fetch_owning_issue(ref) for ref in targets}
    # Determine active targets with canonical F4 parser before fetching pages.
    t = turn_plan(manifest=raw, snapshots=snapshots, now=now)
    pages: dict[str, str] = {}
    for entry in t["targets"]:
        if entry["status"] != "ACTIVE_TURN_ENROLLMENT":
            continue
        ref = entry["mailbox_ref"]
        match = MAILBOX.fullmatch(ref)
        if match is None:
            fail("INVALID_TARGET")
        pages[ref] = fetch_gh_pages(match.group(1), int(match.group(2)))
    return snapshots, pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailbox-a", required=True)
    parser.add_argument("--mailbox-b", required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--live", action="store_true")
    inputs.add_argument("--fixture", type=Path)
    args = parser.parse_args(argv)
    try:
        raw = format_manifest([args.mailbox_a, args.mailbox_b])
        _targets(raw)
        now = datetime.now(timezone.utc)
        if args.live:
            snapshots, pages = live_inputs(raw, now=now)
        else:
            raw_fixture = args.fixture.read_text(encoding="utf-8")
            if len(raw_fixture) > MAX_FIXTURE_CHARS:
                fail("OVERSIZED_FIXTURE")
            fixture = json.loads(raw_fixture)
            if not isinstance(fixture, dict) or set(fixture) != {"snapshots", "pages"}:
                fail("INVALID_FIXTURE")
            snapshots, pages = fixture["snapshots"], fixture["pages"]
        result = preflight(manifest=raw, snapshots=snapshots, pages=pages, now=now)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (InvalidMessage, OSError, UnicodeError, TypeError, ValueError) as exc:
        code = str(exc) if isinstance(exc, InvalidMessage) else "READ_ONLY_IO_FAILURE"
        print(json.dumps({"status": "BLOCKED", "reason_code": code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
