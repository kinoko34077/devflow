"""Regression tests for the read-only Codex Cloud MCP-unavailable CLI."""
import json
import unittest
from unittest.mock import patch

from tools import devflow_read_cli as cli
from tools.devflow_mcp_core import DevflowMCPError


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

    def test_invalid_cli_options_rejected_before_service_access(self):
        cases = [
            ["bootstrap", "--repository", ""],
            ["inbox", "--repository", self.REPOSITORY, "--limit", "0"],
            ["inbox", "--repository", self.REPOSITORY, "--offset", "-1"],
            ["work-view", "--repository", self.REPOSITORY, "--recipient", "claude-code"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with patch("tools.devflow_read_cli.default_service") as get_service:
                    with patch("builtins.print") as out:
                        self.assertEqual(cli.main(arguments), 2)
                    get_service.assert_not_called()
                self.assertEqual(json.loads(out.call_args.args[0])["status"], "BLOCKED")

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

    def test_unknown_operation_is_not_dispatched(self):
        service = FakeService()
        with self.assertRaisesRegex(ValueError, "INVALID_OPERATION"):
            cli.read_operation(service, operation="write", repository=self.REPOSITORY)
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
