"""No-effect end-to-end KAEP/F6 central dispatch eligibility tests."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from tools.gpt_liveness_dispatch_preview import compose, main
from tools.gpt_liveness_pilot import MARKER, END, SCHEMA, plan as plan_one, iso
from tools.gpt_liveness_fleet_plan import SCHEMA as FLEET_SCHEMA
from tools.kaep_request_sender import make_request
from tools.kaep_mailbox_codec import InvalidMessage, encode_comment

REPO = "kinoko34077/devflow"
TARGET = REPO + "#519"
ISSUE = 519
NOW = datetime(2026, 10, 15, 8, 5, tzinfo=timezone.utc)
SESSION = "session_f7_dryrun"
TURN = "turn_f7_dryrun01"
BOT = "github-actions[bot]"


def manifest(*refs):
    return json.dumps({"schema": FLEET_SCHEMA, "targets": list(refs)})


def own_body(*, status=True, long_running_until=None):
    data = {
        "schema": SCHEMA, "session_id": SESSION, "turn_id": TURN,
        "started_at": iso(NOW - timedelta(minutes=2)),
        "expires_at": iso(NOW + timedelta(minutes=55)),
        "expected_actor": "kinoko34077", "enabled": status,
    }
    if long_running_until is not None:
        data["long_running_until"] = long_running_until
    return MARKER + json.dumps(data) + END


def snapshot(*, state="open", body=None):
    return {"repository": REPO, "number": ISSUE, "state": state,
            "body": body if body is not None else own_body()}


def raw_pages(*items):
    return json.dumps([list(items)])


def comment(msg, id, at, actor=BOT):
    return {
        "id": id,
        "body": encode_comment(msg),
        "created_at": iso(at),
        "user": {"login": actor},
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/{ISSUE}",
        "html_url": f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-{id}",
    }


def request(at, *, nonce="a" * 32, id=1):
    calculated = plan_one(body=own_body(), comments=[], repo=REPO,
                          issue=ISSUE, now=at, nonce=nonce)
    envelope, _ = make_request(raw_pages(), repository=REPO, issue=ISSUE,
                               recipient="chatgpt", intent="PING",
                               request_key=calculated["request_key"],
                               request_text=calculated["request_text"],
                               expect_existing_actor=BOT)
    return comment(envelope, id, at)


def run(*, state="open", body=None, comments="[[ ]]",
        when=NOW, overrides=None):
    targets = {TARGET: snapshot(state=state, body=body)}
    if overrides is not None:
        targets.update(overrides)
    return compose(manifest=manifest(*targets.keys()), snapshots=targets,
                   pages={TARGET: comments}, now=when)


class F7DryRunTests(unittest.TestCase):
    def test_empty_scope_does_not_launch_or_claim(self):
        r = compose(manifest=manifest(), snapshots={}, pages={}, now=NOW)
        self.assertEqual(r["target_count"], 0)
        self.assertFalse(r["deployment_authorized"])
        self.assertFalse(r["any_current_gpt_alive_proven"])
        self.assertFalse(r["claim_authority"])

    def test_active_enrollment_no_messages_is_only_hypothetical(self):
        p = run()
        row = p["targets"][0]
        self.assertTrue(row["would_ping_if_authorized"])
        self.assertEqual(row["dispatch_state"], "READY")
        self.assertFalse(row["may_send"])
        self.assertFalse(row["gpt_currently_alive_proven"])
        self.assertNotIn("request_text", row)
        self.assertNotIn("nonce", row)

    def test_disabled_and_closed_are_never_live_or_dispatchable(self):
        for state, body in (("closed", own_body()), ("open", own_body(status=False))):
            with self.subTest(state=state):
                r = run(state=state, body=body, comments="[]")
                self.assertFalse(r["targets"][0]["would_ping_if_authorized"])
                self.assertFalse(r["targets"][0]["may_send"])

    def test_longrunning_predeclaration_never_emits_ping(self):
        r = run(body=own_body(long_running_until=iso(NOW + timedelta(minutes=5))))
        self.assertEqual(r["targets"][0]["dispatch_state"], "LONG_RUNNING")
        self.assertFalse(r["targets"][0]["would_ping_if_authorized"])

    def test_existing_same_bucket_deduplicated(self):
        p = run(comments=raw_pages(request(NOW)))
        self.assertEqual(p["targets"][0]["dispatch_state"], "ALREADY_PINGED")
        self.assertFalse(p["targets"][0]["would_ping_if_authorized"])

    def test_unanswered_limit_suppresses_even_next_slot(self):
        items = [request(NOW + timedelta(minutes=n * 5), nonce=f"{n:032x}", id=n + 10)
                 for n in range(3)]
        p = run(comments=raw_pages(*items),
                when=NOW + timedelta(minutes=15))
        self.assertEqual(p["targets"][0]["dispatch_state"], "SUSPECT_NO_REPLY")
        self.assertEqual(p["targets"][0]["unanswered"], 3)
        self.assertFalse(p["targets"][0]["would_ping_if_authorized"])

    def test_untrusted_request_never_blocks_real_slot(self):
        item = request(NOW, id=4)
        item["user"]["login"] = "untrusted"
        p = run(comments=raw_pages(item))
        self.assertEqual(p["targets"][0]["dispatch_state"], "READY")
        self.assertTrue(p["targets"][0]["would_ping_if_authorized"])

    def test_mismatched_real_comment_identity_blocks(self):
        item = request(NOW, id=4)
        item["issue_url"] = "https://api.github.com/repos/other/repo/issues/519"
        with self.assertRaises(InvalidMessage):
            run(comments=raw_pages(item))

    def test_missing_active_mailbox_fails_closed(self):
        with self.assertRaisesRegex(InvalidMessage, "MISSING_ACTIVE_MAILBOX"):
            compose(manifest=manifest(TARGET), snapshots={TARGET: snapshot()},
                    pages={}, now=NOW)

    def test_unlisted_mailbox_fails_closed(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_PAGES_SCOPE"):
            compose(manifest=manifest(), snapshots={},
                    pages={TARGET: "[]"}, now=NOW)

    def test_duplicate_enrollment_fails_closed(self):
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_ENROLLMENT"):
            run(body=own_body() + "\n" + own_body())

    def test_actual_gh_reads_only_admitted_targets(self):
        import tools.gpt_liveness_dispatch_preview as dp
        closed = snapshot(state="closed")
        with patch.object(dp, "fetch_owning_issue", return_value=closed) as lookup, \
             patch.object(dp, "fetch_gh_pages") as pages:
            # A closed target cannot reach the mailbox-comment fetch at all.
            admissions = compose(manifest=manifest(TARGET), snapshots={TARGET: closed},
                                 pages={}, now=NOW)
            self.assertEqual(admissions["targets"][0]["dispatch_state"],
                             "CLOSED_OR_NO_ENROLLMENT")
            pages.assert_not_called()


if __name__ == "__main__":
    unittest.main()
