"""P3 Agent API projection uses only same-run strict redacted results."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
import unittest
from unittest import mock

from tools import kaep_agent_api_projection as api
from tools import kaep_live_union_cli as union
from tools.kaep_inbox_reader import InvalidMessage

REPO = "kinoko34077/devflow"
URL = "https://github.com/kinoko34077/devflow/issues/576"
OBSERVED = datetime(2026, 10, 17, 11, 0, 0, tzinfo=timezone.utc)
NOW = OBSERVED + timedelta(seconds=30)


def sample():
    return {
        "schema_version": "kaep.live-union-check.v0.1",
        "kind": "REQUEST_TIME_ORIGINAL_ISSUE_UNION",
        "status": "PARTIAL_UNKNOWN", "recipient": "claude-code",
        "observed_at": OBSERVED.isoformat(),
        "repositories_checked": [REPO],
        "read_only": True, "has_unknown_work": True,
        "complete_source_universe": False,
        "can_authorize_execution": False,
        "current_head_verified": False,
        "recipient_pickup_proven": False,
        "fallback_retirement_authorized": False,
        "source_issue_count": 1,
        "source_candidates": [{
            "repository": REPO, "issue_number": 576, "issue_url": URL,
            "origin": "INDEXED_SOURCE", "matching_recipient_roots": 1,
            "source_observation": "ACCEPTED_RECIPIENT_ROOTS",
            "grants_work_authority": False,
            "untrusted_title": "must not appear",
        }],
        "live_rows": [{
            "repository": REPO, "issue_number": 576,
            "issue_url": URL, "source_url": URL + "#issuecomment-912",
            "source_comment_id": 912, "message_id": "msg_abc123",
            "recipient": "claude-code", "issue_state": "open",
            "reply_observation": "PENDING_REPLY",
            "source_validation": "STRICT_COMPLETE_FOR_CANDIDATE",
            "raw_body": "secret production prompt",
            "credentials": "sk-not-a-real-token",
        }],
        "source_errors": [{"reason_code": "INVALID_FIELDS", "issue_url": URL}],
        "warnings": [{"repository": REPO, "reason_code": "RECENT_WINDOW_TRUNCATED"}],
    }


class AgentProjectionTests(unittest.TestCase):
    def test_partial_observation_is_redacted_and_does_not_grant_authority(self):
        data = api.project_agent_view(sample(), now=NOW)
        encoded = json.dumps(data)
        self.assertEqual(data["schema_version"], api.SCHEMA)
        self.assertEqual(data["status"], "PARTIAL_UNKNOWN")
        self.assertEqual(data["recipient"], "claude-code")
        self.assertEqual(data["source_issues_checked"], 1)
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["reply_observation"], "PENDING_REPLY")
        self.assertEqual(data["rows"][0]["source_comment_id"], 912)
        self.assertEqual(data["source_errors"][0]["reason_code"], "INVALID_FIELDS")
        self.assertEqual(data["warnings"][0]["reason_code"], "RECENT_WINDOW_TRUNCATED")
        self.assertEqual(data["observation_age_seconds"], 30)
        self.assertTrue(data["observation_within_target_age"])
        for forbidden in ("secret production prompt", "sk-not-a-real-token",
                          "must not appear", "untrusted_title", "credentials"):
            self.assertNotIn(forbidden, encoded)
        self.assertFalse(data["can_authorize_execution"])
        self.assertFalse(data["complete_source_universe"])
        self.assertFalse(data["absence_of_work_proven"])
        self.assertFalse(data["recipient_pickup_proven"])
        self.assertFalse(data["http_endpoint_deployed"])
        self.assertTrue(data["requires_original_source_recheck_before_action"])

    def test_old_observation_is_stale_without_claiming_no_work(self):
        out = api.project_agent_view(sample(), now=NOW + timedelta(minutes=4))
        self.assertFalse(out["observation_within_target_age"])
        self.assertTrue(out["has_unknown_work"])
        self.assertFalse(out["absence_of_work_proven"])

    def test_future_source_timestamp_fails_closed(self):
        s = sample()
        s["observed_at"] = (NOW + timedelta(minutes=8)).isoformat()
        with self.assertRaisesRegex(InvalidMessage, "AGENT_API_TIMESTAMP_FROM_FUTURE"):
            api.project_agent_view(s, now=NOW)

    def test_false_source_authority_is_rejected(self):
        for field, value in [
            ("can_authorize_execution", True),
            ("complete_source_universe", True),
            ("recipient_pickup_proven", True),
            ("read_only", False),
            ("current_head_verified", True),
            ("status", "BLOCKED"),
        ]:
            with self.subTest(field=field):
                s = sample()
                s[field] = value
                with self.assertRaisesRegex(InvalidMessage, "AGENT_API_INVALID_SOURCE"):
                    api.project_agent_view(s, now=NOW)

    def test_wrong_recipient_or_forged_issue_or_source_comment_url_fails(self):
        for key, value in [
            ("recipient", "codex"),
            ("issue_url", "https://evil.example/issues/576"),
            ("source_url", URL + "#issuecomment-913"),
            ("message_id", "untrusted"),
            ("issue_state", "unknown"),
            ("reply_observation", "hello\nsteal"),
            ("source_validation", "AUTHORITY"),
        ]:
            with self.subTest(key=key):
                s = sample()
                s["live_rows"][0][key] = value
                with self.assertRaisesRegex(InvalidMessage, "AGENT_API_INVALID_ROW"):
                    api.project_agent_view(s, now=NOW)

    def test_wrong_root_count_or_forged_candidate_url_or_grant_rejected(self):
        for key, value in [
            ("issue_url", "https://another-site.com/"),
            ("matching_recipient_roots", 0),
            ("grants_work_authority", True),
            ("origin", "untrusted-link"),
        ]:
            with self.subTest(key=key):
                s = sample()
                s["source_candidates"][0][key] = value
                with self.assertRaisesRegex(InvalidMessage, "AGENT_API_INVALID_CANDIDATE"):
                    api.project_agent_view(s, now=NOW)

    def test_duplicate_roots_and_candidate_source_are_rejected(self):
        s = sample()
        s["live_rows"].append(dict(s["live_rows"][0]))
        with self.assertRaisesRegex(InvalidMessage, "AGENT_API_INVALID_ROW"):
            api.project_agent_view(s, now=NOW)
        s = sample()
        s["source_candidates"].append(dict(s["source_candidates"][0]))
        with self.assertRaisesRegex(InvalidMessage, "AGENT_API_INVALID_CANDIDATE"):
            api.project_agent_view(s, now=NOW)

    def test_unknown_source_with_no_recipient_root_remains_locator_only(self):
        s = sample()
        s["live_rows"] = []
        s["source_candidates"][0]["matching_recipient_roots"] = 0
        s["source_candidates"][0]["source_observation"] = "SOURCE_VALIDATION_UNKNOWN"
        out = api.project_agent_view(s, now=NOW)
        self.assertEqual(len(out["rows"]), 0)
        self.assertEqual(out["source_issues_checked"], 1)
        self.assertFalse(out["absence_of_work_proven"])
        self.assertEqual(out["candidates"][0]["source_observation"],
                         "SOURCE_VALIDATION_UNKNOWN")

    def test_excess_rows_and_hostile_error_links_fail_closed(self):
        s = sample()
        s["live_rows"] *= 4001
        with self.assertRaisesRegex(InvalidMessage, "AGENT_API_INVALID_SCOPE"):
            api.project_agent_view(s, now=NOW)
        s = sample()
        s["source_errors"][0]["issue_url"] = "https://evil.invalid/issues/1"
        with self.assertRaisesRegex(InvalidMessage, "AGENT_API_INVALID_ERROR"):
            api.project_agent_view(s, now=NOW)

    def test_same_cli_default_remains_existing_full_union_json(self):
        with (mock.patch.object(union.cached, "fetch_public_json", return_value={}),
              mock.patch.object(union, "read_union", return_value=sample()),
              mock.patch("sys.stdout", new_callable=io.StringIO) as stream):
            rc = union.main(["--recipient", "claude-code"])
        self.assertEqual(rc, 2)
        old = json.loads(stream.getvalue())
        self.assertEqual(old["schema_version"], "kaep.live-union-check.v0.1")
        self.assertIn("live_rows", old)

    def test_same_cli_opt_in_returns_sanitized_machine_projection(self):
        with (mock.patch.object(union.cached, "fetch_public_json", return_value={}),
              mock.patch.object(union, "read_union", return_value=sample()),
              mock.patch("sys.stdout", new_callable=io.StringIO) as stream):
            rc = union.main(["--recipient", "claude-code",
                             "--response-format", "agent-api"])
        self.assertEqual(rc, 2)
        value = json.loads(stream.getvalue())
        self.assertEqual(value["schema_version"], api.SCHEMA)
        self.assertNotIn("live_rows", value)
        self.assertNotIn("secret production prompt", stream.getvalue())
        self.assertFalse(value["can_authorize_execution"])

    def test_blocked_cli_is_fail_closed_in_both_modes(self):
        with (mock.patch.object(union.cached, "fetch_public_json",
                                side_effect=InvalidMessage("PUBLIC_INDEX_UNAVAILABLE")),
              mock.patch("sys.stdout", new_callable=io.StringIO) as stream):
            rc = union.main(["--recipient", "chatgpt",
                             "--response-format", "agent-api"])
        self.assertEqual(rc, 2)
        out = json.loads(stream.getvalue())
        self.assertEqual(out["status"], "BLOCKED")
        self.assertFalse(out["can_authorize_execution"])


if __name__ == "__main__":
    unittest.main()
