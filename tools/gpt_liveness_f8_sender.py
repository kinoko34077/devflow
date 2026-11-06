"""F8: one-mailbox, explicitly invoked GPT KAEP liveness sender entrypoint.

The F8 sender is PINNED to devflow #554. No recurring scheduler, no
autonomous launch, no credentials/permissions changes, no Claim authority.
Existing F6/F7/F4 are the only enrollment/preview/transport validators.
Default is GET-only; the write path must be explicitly requested, matched
to the exact hardcoded mailbox, and revalidated by existing F4 sender.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Callable

from tools.kaep_mailbox_codec import InvalidMessage
from tools.gpt_liveness_fleet_plan import (
    parse_manifest, fetch_owning_issue, plan as fleet_admission,
)
from tools.gpt_liveness_dispatch_preview import compose
from tools.kaep_inbox_reader import fetch_gh_pages
from tools.gpt_liveness_pilot import main as single_target_pilot_main

ALLOWED_MAILBOX = "kinoko34077/devflow#554"
ALLOWED_REPO = "kinoko34077/devflow"
ALLOWED_ISSUE = 554


def require_exact_target(raw_manifest: str) -> None:
    """An Issue-body enrollment never authorizes another repository/issue."""
    targets = parse_manifest(raw_manifest)
    if targets != [ALLOWED_MAILBOX]:
        raise InvalidMessage("F8_TARGET_NOT_AUTHORIZED")


def preview(*, raw_manifest: str, snapshot: dict[str, Any],
            pages: str | None, now: datetime) -> dict[str, Any]:
    """Fail closed on wrong/missing active mailbox; no external side effects."""
    require_exact_target(raw_manifest)
    snapshots = {ALLOWED_MAILBOX: snapshot}
    admitted = fleet_admission(manifest=raw_manifest, snapshots=snapshots, now=now)
    active = admitted["targets"][0]["status"] == "ACTIVE_ENROLLMENT_REPORTED"
    if active and type(pages) is not str:
        raise InvalidMessage("ACTIVE_MAILBOX_REQUIRED")
    if not active and pages is not None:
        raise InvalidMessage("INACTIVE_MAILBOX_PAGES_FORBIDDEN")
    result = compose(
        manifest=raw_manifest,
        snapshots=snapshots,
        pages={ALLOWED_MAILBOX: pages} if active else {},
        now=now,
    )
    return result


def dispatch(*, report: dict[str, Any], want_send: bool,
             confirmed_mailbox: str | None,
             sender: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    """Only explicitly confirmed READY may invoke existing F4 sender once.

    The supplied sender is the accepted F4 CLI, which re-fetches live Issue
    + full GitHub KAEP mailbox and immediately re-checks enrollment before
    its existing idempotent POST+readback. Never send a nonce from the F7
    dry-run preview itself.
    """
    if report.get("schema") != "gpt-liveness-dispatch-preview.v0.1":
        raise InvalidMessage("INVALID_PREVIEW")
    rows = report.get("targets")
    if type(rows) is not list or len(rows) != 1 or rows[0].get("mailbox_ref") != ALLOWED_MAILBOX:
        raise InvalidMessage("INVALID_PREVIEW_TARGET")
    if not want_send:
        return {"status": "PREVIEW_ONLY", "preview": report,
                "post_attempted": False, "claim_authority": False,
                "gpt_currently_alive_proven": False}
    if confirmed_mailbox != ALLOWED_MAILBOX:
        raise InvalidMessage("F8_SEND_CONFIRMATION_MISSING")
    if (report.get("simulation_only") is not True or
            report.get("deployment_authorized") is not False or
            report.get("claim_authority") is not False or
            report.get("any_current_gpt_alive_proven") is not False):
        raise InvalidMessage("PREVIEW_AUTHORITY_MISMATCH")
    if rows[0].get("dispatch_state") != "READY" or rows[0].get("would_ping_if_authorized") is not True:
        return {"status": "SUPPRESSED_BY_POLICY",
                "reason": rows[0]["dispatch_state"],
                "post_attempted": False, "claim_authority": False,
                "gpt_currently_alive_proven": False}
    # This callback is the existing bounded F4 trusted sender path, not a
    # wrapper around a preview payload. Re-verification remains mandatory.
    result = sender([
        "--repository", ALLOWED_REPO, "--issue", str(ALLOWED_ISSUE),
        "--send",
    ])
    if type(result) is not dict:
        raise InvalidMessage("INVALID_F4_RESULT")
    state = result.get("status")
    if state not in ("SENT_AND_READ_BACK", "ALREADY_SENT", "NO_ACTIVE_ENROLLMENT",
                     "SUSPECT_NO_REPLY", "ALREADY_PINGED", "LONG_RUNNING",
                     "FINISHED", "IDLE", "NEED_USER"):
        raise InvalidMessage("F4_POST_OR_READBACK_FAILED")
    return {
        "status": state,
        "post_attempted": state == "SENT_AND_READ_BACK",
        "posted_comment_id": result.get("posted_comment_id") if state in
            ("SENT_AND_READ_BACK", "ALREADY_SENT") else None,
        "readback_confirmed": state == "SENT_AND_READ_BACK",
        "claim_authority": False,
        "gpt_currently_alive_proven": False,
    }


def _invoke_existing_f4(arguments: list[str]) -> dict[str, Any]:
    """Capture F4 real result, never treat its exit code alone as POST proof."""
    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = single_target_pilot_main(arguments)
    if exit_code != 0:
        raise InvalidMessage("F4_POST_OR_READBACK_FAILED")
    try:
        result = json.loads(output.getvalue())
    except ValueError as exc:
        raise InvalidMessage("INVALID_F4_RESULT") from exc
    if type(result) is not dict:
        raise InvalidMessage("INVALID_F4_RESULT")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="explicit one-Issue allowlist; no default fleet")
    parser.add_argument("--send", action="store_true",
                        help="opt-in one message via existing F4, only if READY")
    parser.add_argument("--confirm-mailbox", help="must equal exact pinned devflow#554 for --send")
    args = parser.parse_args(argv)
    try:
        raw = args.manifest.read_text(encoding="utf-8")
        require_exact_target(raw)
        if args.send and args.confirm_mailbox != ALLOWED_MAILBOX:
            raise InvalidMessage("F8_SEND_CONFIRMATION_MISSING")
        if not args.send and args.confirm_mailbox is not None:
            raise InvalidMessage("UNEXPECTED_CONFIRMATION")
        now = datetime.now(timezone.utc)
        own = fetch_owning_issue(ALLOWED_MAILBOX)
        admitted = fleet_admission(manifest=raw,
                                   snapshots={ALLOWED_MAILBOX: own}, now=now)
        active = admitted["targets"][0]["status"] == "ACTIVE_ENROLLMENT_REPORTED"
        pages = fetch_gh_pages(ALLOWED_REPO, ALLOWED_ISSUE) if active else None
        result = preview(raw_manifest=raw, snapshot=own, pages=pages, now=now)
        output = dispatch(report=result, want_send=args.send,
                          confirmed_mailbox=args.confirm_mailbox,
                          sender=_invoke_existing_f4)
        print(json.dumps(output, sort_keys=True, ensure_ascii=False))
        return 0
    except (InvalidMessage, ValueError, TypeError, OSError, UnicodeError) as exc:
        code = str(exc) if isinstance(exc, InvalidMessage) else "READ_OR_EXECUTION_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason_code": code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
