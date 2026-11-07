import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import repository_bootstrap as cli
from tests.test_repository_bootstrap import issue_body


OWNER = {"id": 79015263, "login": "kinoko34077"}
OWNER_ENV = {
    "DEVFLOW_EVENT_NAME": "issues",
    "DEVFLOW_EVENT_ACTOR_ID": "79015263",
    "DEVFLOW_EVENT_ACTOR_LOGIN": "kinoko34077",
    "DEVFLOW_EVENT_TRIGGERING_ACTOR": "kinoko34077",
    "DEVFLOW_EVENT_REPOSITORY": "kinoko34077/devflow",
}


def issue_event(*, sender=None, action="opened", repository="kinoko34077/devflow"):
    return {
        "action": action,
        "issue": {
            "id": 975000,
            "number": 975,
            "html_url": "https://github.com/kinoko34077/devflow/issues/975",
            "state": "open",
            "updated_at": "2026-11-07T05:00:00Z",
            "title": "[REPO CREATE] example-repo",
            "body": issue_body(),
            "author_association": "OWNER",
            "user": OWNER,
        },
        "repository": {"full_name": repository},
        "sender": OWNER if sender is None else sender,
    }


class RepositoryBootstrapEventAdmissionTests(unittest.TestCase):
    def run_admission(self, event, env=None):
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            output_path = Path(directory) / "github-output"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            with patch.dict(os.environ, {**OWNER_ENV, **(env or {})}, clear=True):
                exit_code = cli.main(
                    [
                        "admit-event",
                        "--event",
                        str(event_path),
                        "--github-output",
                        str(output_path),
                    ]
                )
            return exit_code, output_path.read_text(encoding="utf-8")

    def test_admission_cli_accepts_only_a_consistent_allowlisted_issue_actor(self):
        cases = (
            ("owner", issue_event(), {}, "admitted=true\n"),
            (
                "unlisted sender",
                issue_event(sender={"id": 123456789, "login": "other-user"}),
                {
                    "DEVFLOW_EVENT_ACTOR_ID": "123456789",
                    "DEVFLOW_EVENT_ACTOR_LOGIN": "other-user",
                    "DEVFLOW_EVENT_TRIGGERING_ACTOR": "other-user",
                },
                "admitted=false\n",
            ),
            (
                "owner sender with different environment actor",
                issue_event(),
                {
                    "DEVFLOW_EVENT_ACTOR_ID": "123456789",
                    "DEVFLOW_EVENT_ACTOR_LOGIN": "other-user",
                },
                "admitted=false\n",
            ),
            (
                "sender missing",
                {key: value for key, value in issue_event().items() if key != "sender"},
                {},
                "admitted=false\n",
            ),
            (
                "sender login mismatch",
                issue_event(sender={"id": 79015263, "login": "other-user"}),
                {
                    "DEVFLOW_EVENT_ACTOR_LOGIN": "other-user",
                    "DEVFLOW_EVENT_TRIGGERING_ACTOR": "other-user",
                },
                "admitted=false\n",
            ),
            (
                "missing actor id",
                issue_event(),
                {"DEVFLOW_EVENT_ACTOR_ID": ""},
                "admitted=false\n",
            ),
            (
                "non-canonical actor id",
                issue_event(),
                {"DEVFLOW_EVENT_ACTOR_ID": "079015263"},
                "admitted=false\n",
            ),
            (
                "boolean sender id",
                issue_event(sender={"id": True, "login": "kinoko34077"}),
                {},
                "admitted=false\n",
            ),
            (
                "rerun actor mismatch",
                issue_event(),
                {"DEVFLOW_EVENT_TRIGGERING_ACTOR": "other-user"},
                "admitted=false\n",
            ),
            ("unsupported action", issue_event(action="deleted"), {}, "admitted=false\n"),
            (
                "malformed action",
                issue_event(action={"unexpected": True}),
                {},
                "admitted=false\n",
            ),
            (
                "wrong repository",
                issue_event(repository="someone-else/devflow"),
                {"DEVFLOW_EVENT_REPOSITORY": "someone-else/devflow"},
                "admitted=false\n",
            ),
            (
                "pull request payload",
                {**issue_event(), "issue": {**issue_event()["issue"], "pull_request": {}}},
                {},
                "admitted=false\n",
            ),
        )
        for name, event, env, expected_output in cases:
            with self.subTest(name=name):
                exit_code, output = self.run_admission(event, env)
                self.assertEqual(exit_code, 0)
                self.assertEqual(output, expected_output)

    def test_validate_event_rejects_unlisted_initiator_even_when_issue_author_is_owner(self):
        event = issue_event(sender={"id": 123456789, "login": "other-user"})
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            output_path = Path(directory) / "github-output"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DEVFLOW_EVENT_NAME": "issues",
                    "DEVFLOW_EVENT_ACTOR_ID": "123456789",
                    "DEVFLOW_EVENT_ACTOR_LOGIN": "other-user",
                    "DEVFLOW_EVENT_TRIGGERING_ACTOR": "other-user",
                    "DEVFLOW_EVENT_REPOSITORY": "kinoko34077/devflow",
                    "DEVFLOW_TOKEN": "",
                },
                clear=True,
            ):
                self.assertEqual(cli.validate_event(event_path, output_path), 0)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "candidate=false\nvalid=false\nauthorized=false\nrepository_name=\n",
            )

    def test_validate_event_keeps_allowlisted_owner_request_flow(self):
        event = issue_event()
        api = Mock()
        api.get_issue.return_value = event["issue"]
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            output_path = Path(directory) / "github-output"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            with patch.dict(os.environ, {**OWNER_ENV, "DEVFLOW_TOKEN": "read-token"}, clear=True), patch.object(
                cli, "GitHubApi", return_value=api
            ):
                self.assertEqual(cli.validate_event(event_path, output_path), 0)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "candidate=true\nvalid=true\nauthorized=true\nrepository_name=example-repo\n",
            )

    def test_validate_event_does_not_comment_for_unlisted_initiator(self):
        event = issue_event(sender={"id": 123456789, "login": "other-user"})
        event["issue"]["body"] = "malformed request"
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            output_path = Path(directory) / "github-output"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DEVFLOW_EVENT_NAME": "issues",
                    "DEVFLOW_EVENT_ACTOR_ID": "123456789",
                    "DEVFLOW_EVENT_ACTOR_LOGIN": "other-user",
                    "DEVFLOW_EVENT_TRIGGERING_ACTOR": "other-user",
                    "DEVFLOW_EVENT_REPOSITORY": "kinoko34077/devflow",
                    "DEVFLOW_TOKEN": "untrusted-event-must-not-use-this",
                },
                clear=True,
            ), patch.object(cli, "_comment_validation_failure") as comment:
                self.assertEqual(cli.validate_event(event_path, output_path), 0)
            comment.assert_not_called()

    def test_execute_event_rejects_unlisted_initiator_before_token_access(self):
        event = issue_event(sender={"id": 123456789, "login": "other-user"})
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DEVFLOW_EVENT_NAME": "issues",
                    "DEVFLOW_EVENT_ACTOR_ID": "123456789",
                    "DEVFLOW_EVENT_ACTOR_LOGIN": "other-user",
                    "DEVFLOW_EVENT_TRIGGERING_ACTOR": "other-user",
                    "DEVFLOW_EVENT_REPOSITORY": "kinoko34077/devflow",
                },
                clear=True,
            ):
                with self.assertRaisesRegex(cli.EventError, "initiating actor"):
                    cli.execute_event(event_path)

    def test_execute_event_keeps_allowlisted_owner_flow_before_credential_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            event_path.write_text(json.dumps(issue_event()), encoding="utf-8")
            with patch.dict(os.environ, OWNER_ENV, clear=True):
                with self.assertRaisesRegex(cli.EventError, "DEVFLOW_TOKEN is required"):
                    cli.execute_event(event_path)


if __name__ == "__main__":
    unittest.main()
