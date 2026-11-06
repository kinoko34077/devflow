"""Read-only fleet planning tests: no sending, launch, Claim or GitHub mutations."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from tools.gpt_liveness_fleet_plan import (
    SCHEMA, THIRTY_DAY_TICKS, parse_manifest, plan, fetch_owning_issue, main,
)
from tools.gpt_liveness_pilot import iso, MARKER, END
from tools.kaep_mailbox_codec import InvalidMessage

NOW = datetime(2026, 10, 15, 1, tzinfo=timezone.utc)
REF = "kinoko34077/devflow#519"
OTHER = "kinoko34077/devflow#545"


def manifest(*targets):
    return json.dumps({"schema": SCHEMA, "targets": list(targets)})


def registration(*, enabled=True, before=1, after=45, **updates):
    obj = {
        "schema": "gpt.liveness.v0.1",
        "session_id": "session_f6_test001",
        "turn_id": "turn_f6_test0001",
        "started_at": iso(NOW - timedelta(minutes=before)),
        "expires_at": iso(NOW + timedelta(minutes=after)),
        "expected_actor": "kinoko34077",
        "enabled": enabled,
    }
    obj.update(updates)
    return "example owning Issue\n" + MARKER + json.dumps(obj) + END


def snapshot(ref=REF, *, state="open", body=""):
    repo, no = ref.split("#")
    return {"repository": repo, "number": int(no), "state": state, "body": body}


class FleetAdmissionTests(unittest.TestCase):
    def test_empty_fleet_default_is_non_effectful(self):
        result = plan(manifest=manifest(), snapshots={}, now=NOW)
        self.assertEqual(result["target_count"], 0)
        self.assertEqual(result["idle_cost_model"]["single_central_workflow_nominal_ticks_30d"], 8640)
        self.assertEqual(result["idle_cost_model"]["replicated_per_repo_nominal_ticks_30d"], 0)
        self.assertFalse(result["any_current_gpt_alive_proven"])
        self.assertFalse(result["deployment_authorized"])
        self.assertTrue(result["read_only"])

    def test_active_registration_is_not_gpt_alive(self):
        result = plan(manifest=manifest(REF), snapshots={REF: snapshot(body=registration())}, now=NOW)
        self.assertEqual(result["targets"][0]["status"], "ACTIVE_ENROLLMENT_REPORTED")
        self.assertFalse(result["targets"][0]["may_send"])
        self.assertFalse(result["targets"][0]["gpt_alive_proven"])
        self.assertFalse(result["targets"][0]["claim_authority"])

    def test_disabled_expired_and_closed_never_count_as_active(self):
        for state, issue_body, expected in (
            ("closed", registration(), "CLOSED_OR_NO_ENROLLMENT"),
            ("open", registration(enabled=False), "NO_ACTIVE_ENROLLMENT"),
            ("open", "no registration", "NO_ACTIVE_ENROLLMENT"),
            ("open", registration(before=60, after=-10), "NO_ACTIVE_ENROLLMENT"),
        ):
            with self.subTest(state=state, expected=expected):
                p = plan(manifest=manifest(REF), snapshots={
                    REF: snapshot(state=state, body=issue_body)}, now=NOW)
                self.assertEqual(p["targets"][0]["status"], expected)

    def test_bounded_long_running_does_not_grant_claim(self):
        b = registration(long_running_until=iso(NOW + timedelta(minutes=30)))
        result = plan(manifest=manifest(REF), snapshots={REF: snapshot(body=b)}, now=NOW)
        self.assertEqual(result["targets"][0]["status"], "LONG_RUNNING_DECLARED")
        self.assertFalse(result["targets"][0]["claim_authority"])

    def test_multiple_targets_one_repo_one_scheduler_not_per_repo(self):
        data = plan(manifest=manifest(REF, OTHER),
                    snapshots={REF: snapshot(body=registration()), OTHER: snapshot(OTHER)},
                    now=NOW)
        self.assertEqual(data["target_count"], 2)
        self.assertEqual(data["target_repositories"], 1)
        self.assertEqual(data["idle_cost_model"]["replicated_per_repo_nominal_ticks_30d"], 8640)

    def test_cross_repo_cost_is_only_nominal_not_minutes_or_sla(self):
        other = "kinoko34077/execution-coordinator#138"
        result = plan(manifest=manifest(REF, other),
            snapshots={REF: snapshot(body=registration()), other: snapshot(other)}, now=NOW)
        self.assertEqual(result["target_repositories"], 2)
        self.assertEqual(result["idle_cost_model"]["replicated_per_repo_nominal_ticks_30d"], 17280)
        self.assertFalse(result["idle_cost_model"]["github_delivery_exact"])
        self.assertFalse(result["idle_cost_model"]["billable_minutes_estimated"])

    def test_invalid_or_duplicate_targets_fail_closed(self):
        for targets in [(REF, REF), (REF, REF.upper()), ("github.com/outside",), ("x/y#0",),
                        tuple(REF for _ in range(13))]:
            with self.subTest(targets=targets):
                with self.assertRaises(InvalidMessage):
                    parse_manifest(manifest(*targets))

    def test_rejects_duplicate_manifest_json_fields_and_snapshot_repo_type(self):
        raw = '{"schema":"' + SCHEMA + '","targets":[],"targets":["' + REF + '"]}'
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_MANIFEST_FIELD"):
            parse_manifest(raw)
        wrong_type = snapshot(body=registration())
        wrong_type["repository"] = []
        with self.assertRaisesRegex(InvalidMessage, "ISSUE_IDENTITY_MISMATCH"):
            plan(manifest=manifest(REF), snapshots={REF: wrong_type}, now=NOW)

    def test_scope_and_missing_snapshot_refused(self):
        with self.assertRaisesRegex(InvalidMessage, "SNAPSHOT_SET_MISMATCH"):
            plan(manifest=manifest(REF), snapshots={}, now=NOW)
        with self.assertRaisesRegex(InvalidMessage, "ISSUE_IDENTITY_MISMATCH"):
            plan(manifest=manifest(REF), snapshots={REF:snapshot(OTHER)}, now=NOW)

    def test_duplicate_enrollment_marker_refused(self):
        body = registration() + "\n" + registration()
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_ENROLLMENT"):
            plan(manifest=manifest(REF), snapshots={REF:snapshot(body=body)}, now=NOW)

    def test_manifest_invalid_types_and_oversize(self):
        for raw in (json.dumps([]), json.dumps({"schema":SCHEMA, "targets":"all"}),
                    json.dumps({"schema":SCHEMA, "targets":[], "write":True}),
                    "x" * 3001):
            with self.subTest(raw=raw[:15]):
                with self.assertRaises(InvalidMessage):
                    parse_manifest(raw)

    def test_live_get_is_only_gh_api_get(self):
        payload = {"number":519, "repository_url":"https://api.github.com/repos/kinoko34077/devflow",
                   "state":"closed", "body":"done"}
        response = type("R", (), {"returncode":0, "stdout":json.dumps(payload)})()
        with patch("tools.gpt_liveness_fleet_plan.subprocess.run", return_value=response) as call:
            result = fetch_owning_issue(REF)
        self.assertEqual(result["state"], "closed")
        command = call.call_args.args[0]
        self.assertEqual(command[0:2], ["gh", "api"])
        self.assertTrue(command[-1].endswith("/issues/519"))
        self.assertNotIn("POST", command)
        self.assertNotIn("PATCH", command)

    def test_live_identity_mismatch_rejected(self):
        response = type("R", (), {"returncode":0, "stdout":json.dumps({
            "number":1, "repository_url":"https://api.github.com/repos/kinoko34077/devflow",
            "state":"open", "body":""})})()
        with patch("tools.gpt_liveness_fleet_plan.subprocess.run", return_value=response):
            with self.assertRaisesRegex(InvalidMessage, "ISSUE_IDENTITY_MISMATCH"):
                fetch_owning_issue(REF)

    def test_disabled_real_pilot_snapshot_read_only(self):
        # A closed historical #519 must not be projected as a currently live GPT.
        p = plan(manifest=manifest(REF), snapshots={REF: snapshot(state="closed",
                    body=registration(enabled=False))}, now=NOW)
        self.assertEqual(p["targets"][0]["status"], "CLOSED_OR_NO_ENROLLMENT")
        self.assertFalse(p["any_current_gpt_alive_proven"])


if __name__ == "__main__":
    unittest.main()
