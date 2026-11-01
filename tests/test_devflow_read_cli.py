"""Regression tests for the read-only Codex Cloud MCP-unavailable CLI."""
import json
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from tools import devflow_read_cli as cli
from tools.devflow_mcp_core import DevflowMCPError, DevflowService, _translate_read_error


class FakeService:
    def __init__(self):
        self.calls = []

    def bootstrap_repository(self, repository):
        self.calls.append(("bootstrap", repository))
        return {"repository": repository, "issue_number": 16}

    def get_repository_work_view(self, repository):
        self.calls.append(("work-view", repository))
        return {
            "coverage_status": "INCOMPLETE",
            "has_unknown_work": True,
            "observed_task_view": {"unresolved_open_issue_count": 87},
            "manual_control": {"active_work": "read Control"},
            "can_authorize_execution": False,
        }

    def get_agent_inbox(self, repository, recipient, *, limit, offset, work_status):
        self.calls.append(("inbox", repository, recipient, limit, offset, work_status))
        return {
            "coverage_status": "INCOMPLETE", "has_unknown_work": True,
            "issues": [], "next_offset": None,
            "can_authorize_execution": False,
        }

    def get_agent_workspace(self, repository, recipient, *, limit, offset, work_status,
                            include_recent_kaep=False, include_published_supply=False):
        route = (
            "workspace-supply" if include_published_supply else
            "workspace-recent" if include_recent_kaep else "workspace"
        )
        self.calls.append((route, repository, recipient, limit, offset, work_status))
        return {"schema_version": "devflow.agent-workspace.read.v0.1",
                "sections": {"offers": {"status": "NOT_INTEGRATED", "entries": None}},
                "has_unknown_work": True, "can_authorize_execution": False}

    def get_issue_goal_context(self, repository, issue_number):
        self.calls.append(("issue-goal-context", repository, issue_number))
        return {
            "parent_chain_status": "COMPLETE",
            "source_contexts": [{"issue_ref": f"{repository}#{issue_number}"}],
            "effective_specifications": [{
                "key": "runtime.mode", "scope": "default", "state": "adopted",
                "value": "safe", "source_issue": f"{repository}#{issue_number}",
            }],
            "unknowns": [],
        }

    def assess_issue_plan(self, repository, issue_number, plan):
        self.calls.append(("assess-issue-plan", repository, issue_number, plan))
        return {
            "status": "NEEDS_EVIDENCE", "reason_code": "NO_MATCHING_ADOPTED_SPECIFICATION",
            "mechanical_conflicts": [], "unchecked_effects": [],
            "blocks_execution": False, "can_authorize_execution": False,
            "asserts_plan_completeness": False, "semantic_critique": "NOT_PERFORMED",
        }

    def assess_outcome_observation(self, repository, issue_number, evidence):
        self.calls.append(("assess-outcome-observation", repository, issue_number, evidence))
        return {
            "status": "NEEDS_EVIDENCE" if evidence is None else "DECLARED_ALIGNED",
            "source_verification": "NOT_PERFORMED",
            "acceptance_satisfied": False,
            "can_authorize_execution": False,
        }


class CloudReadCLITests(unittest.TestCase):
    REPOSITORY = "kinoko34077/devflow"

    def test_bootstrap_reuses_service_without_transforming_data(self):
        service = FakeService()
        self.assertEqual(
            cli.read_operation(service, operation="bootstrap", repository=self.REPOSITORY),
            {"repository": self.REPOSITORY, "issue_number": 16})
        self.assertEqual(service.calls, [("bootstrap", self.REPOSITORY)])

    def test_work_view_preserves_partial_coverage_and_control(self):
        service = FakeService()
        result = cli.read_operation(service, operation="work-view", repository=self.REPOSITORY)
        self.assertEqual(result["coverage_status"], "INCOMPLETE")
        self.assertTrue(result["has_unknown_work"])
        self.assertEqual(result["observed_task_view"]["unresolved_open_issue_count"], 87)
        self.assertFalse(result["can_authorize_execution"])
        self.assertEqual(service.calls, [("work-view", self.REPOSITORY)])

    def test_inbox_forwards_codex_paging_and_keeps_unknown_empty_distinction(self):
        service = FakeService()
        result = cli.read_operation(
            service, operation="inbox", repository=self.REPOSITORY,
            recipient="codex", limit=1, offset=2, work_status="AWAITING_REVIEW")
        self.assertEqual(service.calls, [
            ("inbox", self.REPOSITORY, "codex", 1, 2, "AWAITING_REVIEW")])
        self.assertEqual(result["issues"], [])
        self.assertTrue(result["has_unknown_work"])
        self.assertIsNone(result["next_offset"])

    def test_workspace_cli_forwards_options_and_unknowns(self):
        service = FakeService()
        result = cli.read_operation(
            service, operation="workspace", repository=self.REPOSITORY,
            recipient="codex", limit=2, offset=3, work_status="BLOCKED")
        self.assertEqual(result["schema_version"], "devflow.agent-workspace.read.v0.1")
        self.assertIsNone(result["sections"]["offers"]["entries"])
        self.assertEqual(service.calls, [
            ("workspace", self.REPOSITORY, "codex", 2, 3, "BLOCKED")])

    def test_workspace_b6_flag_is_opt_in_and_workspace_only(self):
        service = FakeService()
        result = cli.read_operation(
            service, operation="workspace", repository=self.REPOSITORY,
            recipient="codex", include_recent_kaep=True)
        self.assertTrue(result["has_unknown_work"])
        self.assertEqual(service.calls[-1][0], "workspace-recent")
        with self.assertRaisesRegex(ValueError, "INVALID_RECENT_DISCOVERY_OPTION"):
            cli.read_operation(
                service, operation="inbox", repository=self.REPOSITORY,
                include_recent_kaep=True)

    def test_workspace_published_supply_flag_is_opt_in_and_workspace_only(self):
        service = FakeService()
        got = cli.read_operation(
            service, operation="workspace", repository=self.REPOSITORY,
            recipient="codex", include_published_supply=True)
        self.assertFalse(got["can_authorize_execution"])
        self.assertEqual(service.calls[-1][0], "workspace-supply")
        with self.assertRaisesRegex(ValueError, "INVALID_SUPPLY_OBSERVATION_OPTION"):
            cli.read_operation(
                service, operation="inbox", repository=self.REPOSITORY,
                include_published_supply=True)

    def test_issue_goal_context_cli_operation_preserves_shared_service_result(self):
        service = FakeService()
        direct = service.get_issue_goal_context(self.REPOSITORY, 14)
        cli_result = cli.read_operation(
            service, operation="issue-goal-context",
            repository=self.REPOSITORY, issue_number=14,
        )
        self.assertEqual(cli_result, direct)
        self.assertEqual(service.calls[-1], ("issue-goal-context", self.REPOSITORY, 14))
        self.assertEqual(cli_result["source_contexts"], [{"issue_ref": "kinoko34077/devflow#14"}])
        self.assertEqual(cli_result["effective_specifications"][0]["value"], "safe")

    def test_plan_assessment_cli_operation_delegates_exact_packet_to_shared_service(self):
        service = FakeService()
        candidate = {"schema_version": 1, "task_ref": f"{self.REPOSITORY}#14",
                     "steps": [{"id": "step-1", "intent": "Document the option"}]}
        result = cli.read_operation(
            service, operation="assess-issue-plan", repository=self.REPOSITORY,
            issue_number=14, plan=candidate)
        self.assertEqual(service.calls, [("assess-issue-plan", self.REPOSITORY, 14, candidate)])
        self.assertEqual(result["status"], "NEEDS_EVIDENCE")
        self.assertFalse(result["blocks_execution"])
        self.assertEqual(result["semantic_critique"], "NOT_PERFORMED")

    def test_outcome_assessment_cli_delegates_to_shared_service(self):
        service = FakeService()
        packet = {"task_ref": f"{self.REPOSITORY}#14", "observed_result": "FAILURE"}
        result = cli.read_operation(
            service, operation="assess-outcome-observation",
            repository=self.REPOSITORY, issue_number=14, outcome=packet,
        )
        self.assertEqual(service.calls, [(
            "assess-outcome-observation", self.REPOSITORY, 14, packet,
        )])
        self.assertEqual(result["status"], "DECLARED_ALIGNED")
        self.assertFalse(result["acceptance_satisfied"])

    def test_outcome_packet_on_another_cli_operation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "OUTCOME_ON_NON_ASSESSMENT_OPERATION"):
            cli.read_operation(
                FakeService(), operation="issue-goal-context",
                repository=self.REPOSITORY, issue_number=14, outcome={},
            )

    def test_outcome_file_cli_preserves_declared_packet(self):
        service = FakeService()
        packet = {"task_ref": f"{self.REPOSITORY}#14", "observed_result": "VALID_NEGATIVE"}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as evidence_file:
            json.dump(packet, evidence_file)
            evidence_file.flush()
            with patch("tools.devflow_read_cli.default_service", return_value=service):
                with patch("builtins.print") as out:
                    status = cli.main([
                        "assess-outcome-observation", "--repository", self.REPOSITORY,
                        "--issue-number", "14", "--outcome-file", evidence_file.name,
                    ])
        self.assertEqual(status, 0)
        self.assertEqual(service.calls, [(
            "assess-outcome-observation", self.REPOSITORY, 14, packet,
        )])
        self.assertEqual(json.loads(out.call_args.args[0])["status"], "DECLARED_ALIGNED")

    def test_malformed_or_duplicate_outcome_json_is_delegated_as_missing_evidence(self):
        for content in ('{"task_ref":"one","task_ref":"two"}', '{bad json'):
            with self.subTest(content=content):
                service = FakeService()
                with tempfile.NamedTemporaryFile("w", encoding="utf-8") as evidence_file:
                    evidence_file.write(content)
                    evidence_file.flush()
                    with patch("tools.devflow_read_cli.default_service", return_value=service):
                        with patch("builtins.print") as out:
                            status = cli.main([
                                "assess-outcome-observation", "--repository", self.REPOSITORY,
                                "--issue-number", "14", "--outcome-file", evidence_file.name,
                            ])
                self.assertEqual(status, 0)
                self.assertEqual(service.calls, [(
                    "assess-outcome-observation", self.REPOSITORY, 14, None,
                )])
                self.assertEqual(json.loads(out.call_args.args[0])["status"], "NEEDS_EVIDENCE")

    def test_plan_is_rejected_on_non_assessment_cli_operation(self):
        with self.assertRaisesRegex(ValueError, "PLAN_ON_NON_ASSESSMENT_OPERATION"):
            cli.read_operation(
                FakeService(), operation="issue-goal-context", repository=self.REPOSITORY,
                issue_number=14, plan={})

    def test_plan_file_cli_accepts_valid_json_and_keeps_invalid_input_non_blocking(self):
        service = FakeService()
        candidate = {"schema_version": 1, "task_ref": f"{self.REPOSITORY}#14",
                     "steps": [{"id": "step-1", "intent": "Keep the declared runtime behavior"}]}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as plan_file:
            json.dump(candidate, plan_file)
            plan_file.flush()
            with patch("tools.devflow_read_cli.default_service", return_value=service):
                with patch("builtins.print") as out:
                    status = cli.main(["assess-issue-plan", "--repository", self.REPOSITORY,
                                       "--issue-number", "14", "--plan-file", plan_file.name])
        self.assertEqual(status, 0)
        self.assertEqual(service.calls[0], (
            "assess-issue-plan", self.REPOSITORY, 14,
            {**candidate, "steps": [{**candidate["steps"][0], "declared_effects": []}]},
        ))
        self.assertEqual(json.loads(out.call_args.args[0])["status"], "NEEDS_EVIDENCE")

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as plan_file:
            plan_file.write('{"schema_version":1,"schema_version":1}')
            plan_file.flush()
            with patch("tools.devflow_read_cli.default_service") as get_service:
                with patch("builtins.print") as out:
                    status = cli.main(["assess-issue-plan", "--repository", self.REPOSITORY,
                                       "--issue-number", "14", "--plan-file", plan_file.name])
        get_service.assert_not_called()
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out.call_args.args[0])["reason_code"], "PLAN_INVALID")

    def test_issue_number_cli_arguments_are_validated_before_service_access(self):
        for arguments, expected in (
            (["issue-goal-context", "--repository", self.REPOSITORY], "INVALID_ISSUE_NUMBER"),
            (["issue-goal-context", "--repository", self.REPOSITORY, "--issue-number", "0"], "INVALID_ISSUE_NUMBER"),
            (["bootstrap", "--repository", self.REPOSITORY, "--issue-number", "14"], "ISSUE_NUMBER_ON_NON_ISSUE_OPERATION"),
        ):
            with self.subTest(arguments=arguments):
                with patch("tools.devflow_read_cli.default_service") as get_service:
                    with patch("builtins.print") as out:
                        self.assertEqual(cli.main(arguments), 2)
                    get_service.assert_not_called()
                self.assertEqual(json.loads(out.call_args.args[0]), {
                    "status": "BLOCKED", "reason_code": expected,
                })

    def test_main_issue_goal_context_json_uses_the_same_shared_service(self):
        service = FakeService()
        with patch("tools.devflow_read_cli.default_service", return_value=service):
            with patch("builtins.print") as out:
                status = cli.main([
                    "issue-goal-context", "--repository", self.REPOSITORY,
                    "--issue-number", "14",
                ])
        self.assertEqual(status, 0)
        result = json.loads(out.call_args.args[0])
        self.assertEqual(result["parent_chain_status"], "COMPLETE")
        self.assertEqual(result["effective_specifications"][0]["source_issue"], f"{self.REPOSITORY}#14")
        self.assertEqual(service.calls, [("issue-goal-context", self.REPOSITORY, 14)])

    def test_main_json_is_raw_core_result_and_not_a_synthetic_success(self):
        service = FakeService()
        with patch("tools.devflow_read_cli.default_service", return_value=service):
            with patch("builtins.print") as out:
                code = cli.main([
                    "inbox", "--repository", self.REPOSITORY,
                    "--recipient", "codex", "--work-status", "AWAITING_REVIEW"])
        self.assertEqual(code, 0)
        data = json.loads(out.call_args.args[0])
        self.assertEqual(data["coverage_status"], "INCOMPLETE")
        self.assertTrue(data["has_unknown_work"])
        self.assertEqual(service.calls[0][0], "inbox")


    def test_main_non_ascii_json_is_portable_to_windows_cp932_stdout(self):
        import io

        service = FakeService()
        service.bootstrap_repository = lambda repository: {
            "repository": repository,
            "label": "\u65e5\u672c\u8a9e \U0001f3b5",
        }
        output_buffer = io.BytesIO()
        # Simulates an ordinary Windows redirected Python stdout using cp932.
        encoded_stdout = io.TextIOWrapper(
            output_buffer, encoding="cp932", write_through=True,
        )
        with patch("tools.devflow_read_cli.default_service", return_value=service):
            with patch("sys.stdout", encoded_stdout):
                result = cli.main(["bootstrap", "--repository", self.REPOSITORY])
        self.assertEqual(result, 0)
        # The wire JSON stays ASCII-safe regardless of the host locale.
        wire_output = output_buffer.getvalue().decode("ascii")
        self.assertEqual(
            json.loads(wire_output),
            {"repository": self.REPOSITORY, "label": "\u65e5\u672c\u8a9e \U0001f3b5"},
        )

    def test_invalid_cli_options_rejected_before_service_access(self):
        cases = [
            ["bootstrap", "--repository", ""],
            ["inbox", "--repository", self.REPOSITORY, "--limit", "0"],
            ["inbox", "--repository", self.REPOSITORY, "--offset", "-1"],
            ["work-view", "--repository", self.REPOSITORY, "--recipient", "claude-code"],
            ["issue-goal-context", "--repository", self.REPOSITORY],
            ["issue-goal-context", "--repository", self.REPOSITORY, "--issue-number", "0"],
            ["bootstrap", "--repository", self.REPOSITORY, "--issue-number", "14"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with patch("tools.devflow_read_cli.default_service") as get_service:
                    with patch("builtins.print") as out:
                        self.assertEqual(cli.main(arguments), 2)
                    get_service.assert_not_called()
                self.assertEqual(json.loads(out.call_args.args[0])["status"], "BLOCKED")

    def test_issue_goal_context_read_failure_uses_redacted_fixed_code(self):
        service = FakeService()
        def blocked(_repository, _issue_number):
            raise DevflowMCPError(
                "private Issue body and response token",
                reason_code="GITHUB_HTTP_403",
            )
        service.get_issue_goal_context = blocked
        with patch("tools.devflow_read_cli.default_service", return_value=service):
            with patch("builtins.print") as out:
                status = cli.main([
                    "issue-goal-context", "--repository", self.REPOSITORY,
                    "--issue-number", "14",
                ])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(out.call_args.args[0]), {
            "status": "BLOCKED", "reason_code": "GITHUB_HTTP_403",
        })

    def test_inbox_limit_matches_shared_core_boundary(self):
        self.assertEqual(cli.MAX_INBOX_LIMIT, 20)
        service = FakeService()
        with patch("tools.devflow_read_cli.default_service", return_value=service):
            with patch("builtins.print") as out:
                result = cli.main([
                    "inbox", "--repository", self.REPOSITORY,
                    "--recipient", "codex", "--limit", "20",
                ])
        self.assertEqual(result, 0)
        self.assertEqual(service.calls, [
            ("inbox", self.REPOSITORY, "codex", 20, 0, None)])
        self.assertTrue(json.loads(out.call_args.args[0])["has_unknown_work"])

    def test_bad_inbox_options_fail_before_service_and_return_fixed_codes(self):
        cases = [
            (["--limit", "21"], "INVALID_PAGINATION"),
            (["--limit", "100"], "INVALID_PAGINATION"),
            (["--recipient", "not-registered"], "INVALID_RECIPIENT"),
            (["--work-status", ""], "INVALID_WORK_STATUS"),
        ]
        for option, expected in cases:
            with self.subTest(option=option):
                with patch("tools.devflow_read_cli.default_service") as factory:
                    with patch("builtins.print") as out:
                        status = cli.main([
                            "inbox", "--repository", self.REPOSITORY, *option,
                        ])
                self.assertEqual(status, 2)
                factory.assert_not_called()
                self.assertEqual(
                    json.loads(out.call_args.args[0]),
                    {"status": "BLOCKED", "reason_code": expected},
                )

    def test_transport_failure_is_redacted_and_nonzero(self):
        service = FakeService()
        def blocked(_repository):
            raise DevflowMCPError("sensitive URL / secret response text")
        service.bootstrap_repository = blocked
        with patch("tools.devflow_read_cli.default_service", return_value=service):
            with patch("builtins.print") as out:
                self.assertEqual(cli.main(["bootstrap", "--repository", self.REPOSITORY]), 2)
        self.assertEqual(json.loads(out.call_args.args[0]), {
            "status": "BLOCKED", "reason_code": "DEVFLOW_READ_UNAVAILABLE"})

    def test_http_errors_are_distinct_without_exposing_exception_text(self):
        for status, expected in [
            (401, "GITHUB_HTTP_401"),
            (403, "GITHUB_HTTP_403"),
            (404, "GITHUB_HTTP_404"),
            (429, "GITHUB_HTTP_429"),
            (503, "GITHUB_HTTP_OTHER"),
        ]:
            with self.subTest(status=status):
                error = HTTPError("https://invalid.test/private-token", status, "secret", {}, None)
                mapped = _translate_read_error(error)
                self.assertEqual(mapped.reason_code, expected)
                self.assertEqual(cli.failure_reason_code(mapped), expected)
                self.assertNotIn("secret", cli.failure_reason_code(mapped))

    def test_http_403_zero_remaining_has_distinct_redacted_diagnostic(self):
        cases = (
            ({"X-RateLimit-Remaining": "0"}, "GITHUB_HTTP_403_RATE_LIMIT"),
            ({"X-RateLimit-Remaining": " 0 "}, "GITHUB_HTTP_403_RATE_LIMIT"),
            ({"X-RateLimit-Remaining": "1"}, "GITHUB_HTTP_403"),
            ({"X-RateLimit-Remaining": "not-a-number"}, "GITHUB_HTTP_403"),
            ({}, "GITHUB_HTTP_403"),
        )
        for headers, expected in cases:
            with self.subTest(headers=headers):
                error = HTTPError("https://invalid.test/secret-url", 403, "secret", headers, None)
                mapped = _translate_read_error(error)
                self.assertEqual(mapped.reason_code, expected)
                self.assertEqual(cli.failure_reason_code(mapped), expected)
                self.assertNotIn("secret", str(mapped))
                self.assertNotIn("secret", cli.failure_reason_code(mapped))

    def test_network_json_and_unexpected_errors_are_safely_classified(self):
        self.assertEqual(
            cli.failure_reason_code(_translate_read_error(URLError("secret host"))),
            "GITHUB_NETWORK_UNAVAILABLE",
        )
        self.assertEqual(
            cli.failure_reason_code(
                _translate_read_error(json.JSONDecodeError("secret", "secret", 0))
            ),
            "GITHUB_INVALID_JSON",
        )
        self.assertEqual(
            cli.failure_reason_code(DevflowMCPError(
                "secret", reason_code="secret reason injected"
            )),
            "DEVFLOW_READ_UNAVAILABLE",
        )
        self.assertEqual(cli.failure_reason_code(ValueError("secret")), "INVALID_ARGUMENTS")

    def test_missing_control_has_finite_no_trust_bypass_code(self):
        class NoIssuesReader:
            def list_issues(self, _repository, state):
                if state != "open":
                    raise AssertionError("Unexpected read scope")
                return []

        with self.assertRaises(DevflowMCPError) as context:
            DevflowService(NoIssuesReader()).get_repository_control(self.REPOSITORY)
        self.assertEqual(context.exception.reason_code, "CONTROL_NOT_FOUND_OR_UNTRUSTED")

    def test_cli_returns_exact_finite_code_on_known_failure(self):
        service = FakeService()

        def blocked(_repository):
            raise DevflowMCPError(
                "private github url and credential", reason_code="GITHUB_HTTP_403"
            )

        service.bootstrap_repository = blocked
        with patch("tools.devflow_read_cli.default_service", return_value=service):
            with patch("builtins.print") as out:
                self.assertEqual(cli.main([
                    "bootstrap", "--repository", self.REPOSITORY
                ]), 2)
        self.assertEqual(json.loads(out.call_args.args[0]), {
            "status": "BLOCKED", "reason_code": "GITHUB_HTTP_403",
        })

    def test_unknown_operation_is_not_dispatched(self):
        service = FakeService()
        with self.assertRaisesRegex(ValueError, "INVALID_OPERATION"):
            cli.read_operation(service, operation="write", repository=self.REPOSITORY)
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
