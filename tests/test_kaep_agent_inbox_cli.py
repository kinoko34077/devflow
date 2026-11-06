"""Native KAEP Agent Inbox CLI regression tests; no external GitHub access."""
import json
import unittest
from unittest.mock import patch

from tools import kaep_agent_inbox_cli as cli


class FakeService:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def get_agent_inbox(self, repository, recipient, *, work_status, limit, offset):
        self.calls.append((repository, recipient, work_status, limit, offset))
        # Return an isolated copy: no caller may alter the service view.
        return json.loads(json.dumps(self.results[repository]))


def view(*, unknown=False):
    return {
        "repository": "kinoko34077/devflow",
        "has_unknown_work": unknown,
        "can_authorize_execution": False,
        "issues": [
            {"issue_number": 537, "requests": [
                {"status": "PENDING_REPLY", "source_message_id": "msg_new"}]},
            {"issue_number": 532, "requests": [
                {"status": "ANSWER_OBSERVED", "source_message_id": "msg_done"}]},
            {"issue_number": 999, "requests": None, "source_state": "UNAVAILABLE"},
            {"issue_number": 535, "requests": []},
        ],
    }


class AgentInboxCLITests(unittest.TestCase):
    def test_pending_only_keeps_pending_and_unavailable_diagnostics(self):
        service = FakeService({"kinoko34077/devflow": view()})
        result = cli.read_checkin(
            service, repositories=["kinoko34077/devflow"],
            recipient="claude-code", work_status="AWAITING_REVIEW",
            limit=20, offset=0, pending_only=True)
        self.assertEqual(
            [x["issue_number"] for x in result["repositories"][0]["issues"]],
            [537, 999])
        self.assertEqual(service.calls, [
            ("kinoko34077/devflow", "claude-code", "AWAITING_REVIEW", 20, 0)])
        self.assertFalse(result["can_authorize_execution"])
        self.assertFalse(result["can_modify_checkin_schedule"])

    def test_read_all_keeps_separate_task_and_message_views(self):
        service = FakeService({"kinoko34077/devflow": view()})
        result = cli.read_checkin(
            service, repositories=["kinoko34077/devflow"],
            recipient="codex", work_status=None, limit=10, offset=5,
            pending_only=False)
        self.assertEqual(len(result["repositories"][0]["issues"]), 4)
        self.assertEqual(result["checked_repository_count"], 1)
        self.assertEqual(service.calls[0][1:], ("codex", None, 10, 5))

    def test_partial_or_unavailable_is_not_empty_success(self):
        service = FakeService({"kinoko34077/devflow": view(unknown=True)})
        result = cli.read_checkin(
            service, repositories=["kinoko34077/devflow"],
            recipient="claude-code", work_status=None, limit=20, offset=0,
            pending_only=True)
        self.assertEqual(result["status"], "INCOMPLETE_OR_UNKNOWN")
        self.assertTrue(result["has_unknown_work"])

    def test_explicit_limit_five_repositories_and_dedup(self):
        service = FakeService({f"kinoko34077/r{i}":view() for i in range(6)})
        valid = [f"kinoko34077/r{i}" for i in range(5)]
        result = cli.read_checkin(
            service, repositories=valid, recipient="claude-code",
            work_status=None, limit=20, offset=0, pending_only=False)
        self.assertEqual(result["checked_repository_count"], 5)
        for invalid in ([],valid+[f"kinoko34077/r5"],[valid[0],valid[0]]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    cli.read_checkin(
                        service, repositories=invalid, recipient="claude-code",
                        work_status=None, limit=20, offset=0, pending_only=False)

    def test_cli_safe_json_and_no_background_work(self):
        service = FakeService({"kinoko34077/devflow":view(unknown=True)})
        with patch("tools.kaep_agent_inbox_cli.default_service",return_value=service):
            with patch("builtins.print") as out:
                code = cli.main(["--repository","kinoko34077/devflow",
                                 "--pending-only","--work-status","AWAITING_REVIEW"])
        self.assertEqual(code,0)
        data=json.loads(out.call_args.args[0])
        self.assertEqual(data["status"],"INCOMPLETE_OR_UNKNOWN")
        self.assertEqual(data["checked_repository_count"],1)
        self.assertFalse(data["can_modify_checkin_schedule"])

    def test_cli_invalid_repos_fail_before_any_read(self):
        with patch("tools.kaep_agent_inbox_cli.default_service",
                   return_value=FakeService({})) as load:
            with patch("builtins.print") as out:
                code=cli.main(["--repository","kinoko34077/demo",
                               "--repository","kinoko34077/demo"])
        self.assertEqual(code,2)
        data=json.loads(out.call_args.args[0])
        self.assertEqual(data["reason_code"],"DUPLICATE_REPOSITORY")
        load.assert_called_once()


if __name__ == "__main__":
    unittest.main()
