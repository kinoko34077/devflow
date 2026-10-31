import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.goal_plan_assessment import (
    PLAN_MARKER_END,
    PLAN_MARKER_START,
    PlanAssessmentError,
    assess_plan,
    assess_issue_plan,
    fetch_public_issue,
    main,
    parse_declared_plan,
    parse_plan_json,
    write_action_summary,
)


TASK = "org/repo#14"


def context(specifications, *, parent_chain_status="COMPLETE", coverage="RECORDED_CLAIMS_ONLY"):
    return {
        "parent_chain_status": parent_chain_status,
        "coverage": {"structured_specifications": coverage},
        "source_contexts": [{"issue_ref": TASK}],
        "effective_specifications": specifications,
        "unknowns": [],
    }


def adopted(key, value, *, scope="default", authority="accepted_spec", state="adopted"):
    return {
        "key": key,
        "scope": scope,
        "state": state,
        "authority": authority,
        "value": value,
        "claim_ref": "org/repo#14:condition",
        "source_issue": TASK,
        "evidence_ref": "org/repo#14",
    }


def plan(effects, *, task_ref=TASK):
    return {
        "schema_version": 1,
        "task_ref": task_ref,
        "steps": [{"id": "implementation", "intent": "Implement the declared plan", "declared_effects": effects}],
    }


class GoalPlanAssessmentTests(unittest.TestCase):
    def effect(self, key, value, *, scope="default"):
        return {"key": key, "scope": scope, "state": "set", "value": value}

    def test_adopted_source_condition_detects_exact_declared_conflict(self):
        result = assess_plan(
            context([adopted("runtime.mode", "realtime")]),
            plan([self.effect("runtime.mode", "offline-preview")]),
        )
        self.assertEqual(result["status"], "CONFLICTS_DETECTED")
        self.assertEqual(result["mechanical_conflicts"][0]["step_id"], "implementation")
        self.assertEqual(result["mechanical_conflicts"][0]["claim_ref"], "org/repo#14:condition")
        self.assertFalse(result["can_authorize_execution"])
        self.assertEqual(result["semantic_critique"], "NOT_PERFORMED")
        self.assertEqual(result["citation_semantics"], "NOT_VERIFIED")
        self.assertEqual(result["source_authority"], "ASSERTED_IN_SOURCE_NOT_AUTHENTICATED")

    def test_latest_effective_scoped_specification_is_used_and_false_is_not_missing(self):
        result = assess_plan(
            context([adopted("feature.enabled", False, scope="runtime")]),
            plan([self.effect("feature.enabled", True, scope="runtime")]),
        )
        self.assertEqual(result["status"], "CONFLICTS_DETECTED")
        self.assertEqual(result["mechanical_conflicts"][0]["scope"], "runtime")

    def test_matching_adopted_effect_and_materially_different_unrelated_plan_are_not_rejected(self):
        candidate = plan([self.effect("runtime.mode", "realtime")])
        candidate["steps"].append({"id": "ui-redesign", "intent": "Explore a new UI layout"})
        result = assess_plan(context([adopted("runtime.mode", "realtime")]), candidate)
        self.assertEqual(result["status"], "NO_DECLARED_CONFLICT")
        self.assertEqual(result["checked_effect_count"], 1)
        self.assertFalse(result["blocks_execution"])
        self.assertFalse(result["asserts_plan_completeness"])

    def test_proposed_or_inferred_condition_never_becomes_a_deterministic_conflict(self):
        source = adopted("runtime.mode", "realtime", authority="inferred_hypothesis", state="unknown")
        result = assess_plan(context([source]), plan([self.effect("runtime.mode", "offline")]))
        self.assertEqual(result["status"], "NEEDS_EVIDENCE")
        self.assertEqual(result["mechanical_conflicts"], [])
        self.assertFalse(result["blocks_execution"])

    def test_missing_parent_source_stays_unknown_even_when_visible_claim_disagrees(self):
        result = assess_plan(
            context([adopted("runtime.mode", "realtime")], parent_chain_status="PARTIAL_UNKNOWN"),
            plan([self.effect("runtime.mode", "offline")]),
        )
        self.assertEqual(result["status"], "NEEDS_EVIDENCE")
        self.assertEqual(result["mechanical_conflicts"], [])

    def test_unrepresented_or_unrelated_work_is_not_a_global_block(self):
        result = assess_plan(
            context([adopted("runtime.mode", "realtime")]),
            plan([self.effect("docs.heading", "New heading")]),
        )
        self.assertEqual(result["status"], "NEEDS_EVIDENCE")
        self.assertFalse(result["blocks_execution"])
        self.assertEqual(result["unchecked_effects"][0]["reason_code"], "NO_MATCHING_ADOPTED_SPECIFICATION")

    def test_removed_condition_conflicts_only_with_reintroducing_a_value(self):
        removed = adopted("ui.preview_panel", None, state="removed")
        del removed["value"]
        result = assess_plan(
            context([removed]),
            plan([self.effect("ui.preview_panel", True)]),
        )
        self.assertEqual(result["status"], "CONFLICTS_DETECTED")

    def test_wrong_task_reference_and_malformed_plan_fail_closed_without_blocking(self):
        wrong = assess_plan(
            context([adopted("runtime.mode", "realtime")]),
            plan([self.effect("runtime.mode", "offline")], task_ref="org/repo#15"),
        )
        self.assertEqual(wrong["status"], "NEEDS_EVIDENCE")
        self.assertEqual(wrong["mechanical_conflicts"], [])
        huge_number = assess_issue_plan(
            "org/repo#" + "9" * 5_000, plan([self.effect("runtime.mode", "offline")]),
        )
        self.assertEqual(huge_number["reason_code"], "TASK_REFERENCE_INVALID")
        for candidate in ({}, {"schema_version": 1, "task_ref": TASK, "steps": []}):
            with self.subTest(candidate=candidate):
                result = assess_plan(context([adopted("runtime.mode", "realtime")]), candidate)
                self.assertEqual(result["status"], "NEEDS_EVIDENCE")
                self.assertFalse(result["blocks_execution"])

    def test_plan_body_parser_accepts_one_packet_and_rejects_duplicate_markers_or_json_keys(self):
        packet = plan([self.effect("runtime.mode", "offline")])
        body = f"Plan follows\n{PLAN_MARKER_START}\n{json.dumps(packet)}\n{PLAN_MARKER_END}"
        state, parsed = parse_declared_plan(body)
        self.assertEqual(state, "PLAN_DECLARED")
        self.assertEqual(parsed, packet)
        self.assertEqual(parse_declared_plan("No structured plan here")[0], "NO_DECLARED_PLAN")
        self.assertEqual(parse_declared_plan(body + "\n" + body)[0], "PLAN_MARKERS_INVALID")
        duplicate = (
            f'{PLAN_MARKER_START}{{"schema_version":1,"schema_version":1,"task_ref":"{TASK}","steps":[]}}'
            f'{PLAN_MARKER_END}'
        )
        self.assertEqual(parse_declared_plan(duplicate), ("PLAN_INVALID", None))
        with self.assertRaises(PlanAssessmentError):
            parse_plan_json('{"schema_version":1,"schema_version":1}')

    def test_non_string_effect_state_is_invalid_and_never_raises_type_error(self):
        for state in ([], {}, None, 1):
            candidate = plan([{"key": "runtime.mode", "scope": "default", "state": state}])
            with self.subTest(state=state):
                result = assess_plan(context([adopted("runtime.mode", "realtime")]), candidate)
                self.assertEqual(result["status"], "NEEDS_EVIDENCE")
                self.assertEqual(result["reason_code"], "PLAN_INVALID")
                with self.assertRaises(PlanAssessmentError):
                    parse_plan_json(json.dumps(candidate))

    def test_public_reader_is_anonymous_and_checks_observed_issue_identity(self):
        payload = json.dumps({
            "number": 14, "title": "task", "state": "open", "body": "source",
            "url": "https://api.github.com/repos/org/repo/issues/14",
            "repository_url": "https://api.github.com/repos/org/repo",
            "html_url": "https://github.com/org/repo/issues/14",
        }).encode()

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return "https://api.github.com/repos/org/repo/issues/14"

            def read(self, _size):
                return payload

        with patch("urllib.request.urlopen", return_value=Response()) as open_url:
            result = fetch_public_issue("org/repo", 14)
        request = open_url.call_args.args[0]
        self.assertEqual(result["issue_number"], 14)
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(request.full_url, "https://api.github.com/repos/org/repo/issues/14")

        class Redirected(Response):
            def geturl(self):
                return "https://example.invalid/repos/org/repo/issues/14"

        with patch("urllib.request.urlopen", return_value=Redirected()):
            with self.assertRaises(PlanAssessmentError):
                fetch_public_issue("org/repo", 14)

        pull_request_payload = json.dumps({
            "number": 14, "title": "PR", "state": "open", "body": "not an owning Issue",
            "repository_url": "https://api.github.com/repos/org/repo",
            "pull_request": {"url": "https://api.github.com/repos/org/repo/pulls/14"},
        }).encode()

        class PullRequestResponse(Response):
            def read(self, _size):
                return pull_request_payload

        with patch("urllib.request.urlopen", return_value=PullRequestResponse()):
            with self.assertRaises(PlanAssessmentError):
                fetch_public_issue("org/repo", 14)

        for invalid_payload in (
            {"number": True},
            {"number": 14.0},
            {"html_url": "https://github.com/other/repo/issues/14"},
            {"url": "https://api.github.com/repos/org/repo/issues/15"},
            {"body": {"text": "not source text"}},
        ):
            altered = {
                "number": 14, "title": "task", "state": "open", "body": "source",
                "url": "https://api.github.com/repos/org/repo/issues/14",
                "repository_url": "https://api.github.com/repos/org/repo",
                "html_url": "https://github.com/org/repo/issues/14",
                **invalid_payload,
            }
            mutated_body = json.dumps(altered).encode()

            class MismatchedIdentityResponse(Response):
                def read(self, _size):
                    return mutated_body

            with self.subTest(invalid_payload=invalid_payload):
                with patch("urllib.request.urlopen", return_value=MismatchedIdentityResponse()):
                    with self.assertRaises(PlanAssessmentError):
                        fetch_public_issue("org/repo", 14)

    def test_source_unavailable_is_unknown_and_non_blocking(self):
        result = assess_issue_plan(
            TASK,
            plan([self.effect("runtime.mode", "offline")]),
            fetch_issue=lambda *_args: (_ for _ in ()).throw(PermissionError("private response")),
        )
        self.assertEqual(result["status"], "NEEDS_EVIDENCE")
        self.assertEqual(result["reason_code"], "SOURCE_UNAVAILABLE")
        self.assertFalse(result["blocks_execution"])
        self.assertNotIn("private response", json.dumps(result))

    def test_actions_adapter_fails_only_for_deterministic_declared_conflict(self):
        packet = plan([self.effect("runtime.mode", "offline")])
        event = {"pull_request": {"body": (
            f"{PLAN_MARKER_START}\n{json.dumps(packet)}\n{PLAN_MARKER_END}"
        )}}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as event_file:
            json.dump(event, event_file)
            event_file.flush()
            output = []
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_file.name}):
                with patch("tools.goal_plan_assessment.assess_issue_plan", return_value={
                    "status": "CONFLICTS_DETECTED", "checked_effect_count": 1,
                    "mechanical_conflicts": [{}], "unchecked_effects": [],
                }):
                    with patch("builtins.print", side_effect=output.append):
                        result = main()
        self.assertEqual(result, 1)
        self.assertTrue(any("CONFLICTS_DETECTED" in line for line in output))
        self.assertFalse(any("offline" in line for line in output))

        with tempfile.NamedTemporaryFile("r+", encoding="utf-8") as summary:
            write_action_summary({
                "status": "CONFLICTS_DETECTED",
                "observed_at": "2026-10-31T19:00:00Z",
                "source_revisions": [{"issue_ref": TASK, "body_sha256": "a" * 64}],
            }, summary.name)
            summary.seek(0)
            text = summary.read()
        self.assertIn("org/repo#14", text)
        self.assertIn("a" * 64, text)
        self.assertIn("does not authorize work", text)

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as event_file:
            json.dump({"pull_request": {"body": "No declaration"}}, event_file)
            event_file.flush()
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_file.name}):
                with patch("builtins.print") as output:
                    self.assertEqual(main(), 0)
                    self.assertIn("SKIPPED_NO_DECLARED_PLAN", output.call_args.args[0])

    def test_existing_gate_keeps_read_permissions_and_runs_plan_check_on_pull_requests(self):
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/goal-plan-assessment-pilot.yml"
        source = workflow.read_text(encoding="utf-8")
        self.assertIn("permissions: {}", source)
        self.assertNotIn("project-sync-tests.yml", source)
        self.assertNotIn("issues: read", source)
        self.assertIn("Assess declared source-bound plan effects", source)
        self.assertIn("Assess declared source-bound plan effects with trusted base code", source)
        self.assertIn("BASE_SHA: ${{ github.event.pull_request.base.sha }}", source)
        self.assertNotIn("${{ github.sha }}", source)
        self.assertIn("pull_request:", source)


if __name__ == "__main__":
    unittest.main()
