"""CH9 dual-turn native dry-run: two GitHub mailboxes, no write effects."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import gpt_liveness_two_turn_preflight as probe
from tools.gpt_liveness_turn_router import format_manifest
from tools.kaep_mailbox_codec import InvalidMessage

NOW = datetime(2026, 10, 16, 3, 10, tzinfo=timezone.utc)
A, B = "kinoko34077/devflow#700", "kinoko34077/devflow#701"
TURN_A, TURN_B = "turn_" + "a" * 32, "turn_" + "b" * 32
SESSION_A, SESSION_B = "session_" + "a" * 32, "session_" + "b" * 32


def own(ref: str, session: str, turn: str, *,
        enabled: bool = True, state: str = "open",
        start: str = "2026-10-16T03:00:00Z",
        expiry: str = "2026-10-16T04:00:00Z",
        expected_actor: str = "kinoko34077", long_running_until: str | None = None):
    registration = {
        "schema": "gpt.liveness.v0.1",
        "session_id": session, "turn_id": turn,
        "started_at": start, "expires_at": expiry,
        "expected_actor": expected_actor, "enabled": enabled,
    }
    if long_running_until:
        registration["long_running_until"] = long_running_until
    return {
        "repository": "kinoko34077/devflow",
        "number": int(ref.rpartition("#")[-1]), "state": state,
        "body": "<!-- gpt-liveness:enrollment:v0.1 "
                + json.dumps(registration, separators=(",", ":")) + " -->",
    }


def fixture(*, a=None, b=None, pages=None):
    snapshots = {
        A: own(A, SESSION_A, TURN_A) if a is None else a,
        B: own(B, SESSION_B, TURN_B) if b is None else b,
    }
    return {
        "manifest": format_manifest([A, B]),
        "snapshots": snapshots,
        "pages": {A: "[[]]", B: "[[]]"} if pages is None else pages,
    }


def report(**kwargs):
    params = fixture(**kwargs)
    return probe.preflight(now=NOW, **params)


class TwoTurnPreflightTests(unittest.TestCase):
    def test_two_genuine_independent_registrations_are_only_conditional(self):
        out = report()
        self.assertEqual(out["schema"], probe.SCHEMA)
        self.assertEqual(out["status"], "TWO_TURNS_PREVIEW_READY")
        self.assertTrue(out["has_two_distinct_active_turns"])
        self.assertEqual({s["participant_id"] for s in out["targets"]}, {TURN_A, TURN_B})
        self.assertEqual({s["mailbox_ref"] for s in out["targets"]}, {A, B})
        self.assertTrue(all(s["conditionally_ready"] for s in out["targets"]))
        for key in ("deployment_authorized", "post_attempted", "write_authorized",
                    "gpt_currently_alive_proven", "claim_authority"):
            self.assertIs(out[key], False)

    def test_two_same_account_participants_do_not_share_inbox(self):
        out = report()
        self.assertNotEqual(out["targets"][0]["mailbox_ref"],
                            out["targets"][1]["mailbox_ref"])
        self.assertEqual(out["targets"][0]["participant_id"], TURN_A)
        self.assertEqual(out["targets"][1]["participant_id"], TURN_B)
        self.assertFalse(out["targets"][0]["send_authorized"])

    def test_inactive_second_turn_cannot_be_ready(self):
        out = report(b=own(B, SESSION_B, TURN_B, enabled=False), pages={A: "[[]]"})
        self.assertEqual(out["status"], "HOLD_NOT_READY")
        self.assertFalse(out["has_two_distinct_active_turns"])
        self.assertEqual(out["targets"][1]["turn_state"], "UNOBSERVED")
        self.assertIsNone(out["targets"][1]["participant_id"])

    def test_expired_and_closed_second_never_ready(self):
        for value in (
            own(B, SESSION_B, TURN_B, expiry="2026-10-16T03:01:00Z"),
            own(B, SESSION_B, TURN_B, state="closed"),
        ):
            with self.subTest(value=value["state"]):
                out = report(b=value, pages={A: "[[]]"})
                self.assertEqual(out["status"], "HOLD_NOT_READY")
                self.assertFalse(out["deployment_authorized"])

    def test_long_running_must_not_qualify_for_send(self):
        b = own(B, SESSION_B, TURN_B, long_running_until="2026-10-16T03:40:00Z")
        out = report(b=b, pages={A: "[[]]"})
        self.assertEqual(out["status"], "HOLD_NOT_READY")
        self.assertEqual(out["targets"][1]["turn_state"], "LONG_RUNNING_DECLARED")

    def test_duplicate_turn_id_in_different_mailboxes_rejected(self):
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_ACTIVE_TURN"):
            report(b=own(B, SESSION_B, TURN_A))

    def test_same_issue_twice_and_cross_repo_forbidden(self):
        f = fixture()
        for targets in (
            [A, A],
            [A, "someoneelse/devflow#701"],
            [A],
            [A, B, "kinoko34077/devflow#702"],
        ):
            raw = json.dumps({"schema": "gpt-liveness-fleet-plan.v0.1", "targets": targets})
            with self.subTest(raw=raw), self.assertRaises(InvalidMessage):
                probe.preflight(manifest=raw, snapshots=f["snapshots"],
                                pages=f["pages"], now=NOW)

    def test_reading_wrong_mailbox_pages_fails_closed(self):
        with self.assertRaisesRegex(InvalidMessage, "ACTIVE_MAILBOX_SET_MISMATCH"):
            report(pages={A: "[[]]"})
        with self.assertRaisesRegex(InvalidMessage, "INVALID_MAILBOX_PAGES"):
            report(pages={A: "[[]]", B: "[[]]", "kinoko34077/devflow#702": "[[]]"})

    def test_foreign_actor_in_enrollment_rejected(self):
        with self.assertRaisesRegex(InvalidMessage, "NON_OWNER_TURN_ACTOR"):
            report(b=own(B, SESSION_B, TURN_B, expected_actor="unexpected-user"))

    def test_f7_did_not_actually_authorize_sending(self):
        with patch.object(probe, "f7_compose", return_value={
            "schema": "gpt-liveness-dispatch-preview.v0.1",
            "read_only": True, "simulation_only": True,
            "deployment_authorized": True, "claim_authority": False,
            "any_current_gpt_alive_proven": False, "targets": [{}, {}],
        }):
            with self.assertRaisesRegex(InvalidMessage, "INVALID_F7_SIMULATION"):
                report()

    def test_unsafe_untrusted_comment_metadata_rejected(self):
        bad = json.dumps([[{
            "id": 3, "body": "not a KAEP envelope",
            "created_at": "2026-10-16T03:09:00Z",
            "user": {"login": "github-actions[bot]"},
            "issue_url": f"https://api.github.com/repos/kinoko34077/devflow/issues/701",
            "html_url": "https://github.com/kinoko34077/devflow/issues/700#issuecomment-3",
        }]])
        with self.assertRaises(InvalidMessage):
            report(pages={A: "[[]]", B: bad})

    def test_only_read_only_methods_are_present(self):
        root = Path(probe.__file__).read_text(encoding="utf-8")
        for banned in ('method="POST"', "issues: write", "workflow_dispatch(",
                       "send_request(", "subprocess.run(", "post_comment("):
            self.assertNotIn(banned, root)
        f8 = (Path(__file__).resolve().parents[1] /
              "tools/gpt_liveness_f8_sender.py").read_text(encoding="utf-8")
        self.assertIn('ALLOWED_MAILBOX = "kinoko34077/devflow#554"', f8)

    def test_live_fetch_only_called_after_2_pinned_refs(self):
        manifest = format_manifest([A, B])
        with patch.object(probe, "fetch_owning_issue", side_effect=[
            own(A, SESSION_A, TURN_A),
            own(B, SESSION_B, TURN_B),
        ]) as read_issue, patch.object(
            probe, "fetch_gh_pages", return_value="[[]]"
        ) as read_pages:
            snapshots, pages = probe.live_inputs(manifest, now=NOW)
        self.assertEqual(read_issue.call_count, 2)
        self.assertEqual(read_pages.call_count, 2)
        self.assertEqual(set(snapshots), {A, B})
        self.assertEqual(set(pages), {A, B})


if __name__ == "__main__":
    unittest.main()
