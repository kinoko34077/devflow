import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import repository_bootstrap as cli
from tests.test_repository_bootstrap import issue_body
from tools.repository_bootstrap import (
    BootstrapError,
    BootstrapResult,
    GitHubApi,
    GitHubApiError,
)


OWNER = {"id": 79015263, "login": "kinoko34077"}
OWNER_EVENT_ENV = {
    "DEVFLOW_EVENT_NAME": "issues",
    "DEVFLOW_EVENT_ACTOR_ID": "79015263",
    "DEVFLOW_EVENT_ACTOR_LOGIN": "kinoko34077",
    "DEVFLOW_EVENT_TRIGGERING_ACTOR": "kinoko34077",
    "DEVFLOW_EVENT_REPOSITORY": "kinoko34077/devflow",
}
REPOSITORY = "kinoko34077/devflow"
ISSUE_URL = f"https://github.com/{REPOSITORY}/issues/975"
UPDATED_AT = "2026-11-07T05:00:00Z"


def issue_event():
    return {
        "action": "opened",
        "issue": {
            "id": 975000,
            "number": 975,
            "html_url": ISSUE_URL,
            "state": "open",
            "updated_at": UPDATED_AT,
            "title": "[REPO CREATE] example-repo",
            "body": issue_body(),
            "author_association": "OWNER",
            "user": OWNER,
        },
        "repository": {"full_name": REPOSITORY},
        "sender": OWNER,
    }


class FakeIssueReadApi:
    def __init__(self, issue):
        self.issue = issue
        self.reads = []

    def get_issue(self, repository, number):
        self.reads.append((repository, number))
        if isinstance(self.issue, Exception):
            raise self.issue
        return self.issue


class RepositoryBootstrapStaleEventTests(unittest.TestCase):
    def write_event(self, directory, event):
        path = Path(directory) / "event.json"
        path.write_text(json.dumps(event), encoding="utf-8")
        return path

    def test_validate_rejects_stale_body_and_revision_without_comment(self):
        event = issue_event()
        current = {
            **event["issue"],
            "body": "request changed after this event was created",
            "updated_at": "2026-11-07T05:01:00Z",
        }
        api = FakeIssueReadApi(current)
        with tempfile.TemporaryDirectory() as directory:
            event_path = self.write_event(directory, event)
            output_path = Path(directory) / "github-output"
            with patch.dict(os.environ, {**OWNER_EVENT_ENV, "DEVFLOW_TOKEN": "read-token"}, clear=True), patch.object(
                cli, "GitHubApi", return_value=api
            ), patch.object(cli, "_comment_validation_failure") as comment:
                self.assertEqual(cli.validate_event(event_path, output_path), 0)
            comment.assert_not_called()
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "candidate=false\nvalid=false\nauthorized=false\nrepository_name=\n",
            )
        self.assertEqual(api.reads, [(REPOSITORY, 975)])

    def test_validate_rejects_closed_current_issue_without_comment(self):
        event = issue_event()
        api = FakeIssueReadApi({**event["issue"], "state": "closed"})
        with tempfile.TemporaryDirectory() as directory:
            event_path = self.write_event(directory, event)
            output_path = Path(directory) / "github-output"
            with patch.dict(os.environ, {**OWNER_EVENT_ENV, "DEVFLOW_TOKEN": "read-token"}, clear=True), patch.object(
                cli, "GitHubApi", return_value=api
            ), patch.object(cli, "_comment_validation_failure") as comment:
                self.assertEqual(cli.validate_event(event_path, output_path), 0)
            comment.assert_not_called()
            self.assertIn("candidate=false", output_path.read_text(encoding="utf-8"))
        self.assertEqual(api.reads, [(REPOSITORY, 975)])

    def test_execute_rejects_stale_or_closed_issue_before_bootstrap_secret_or_executor(self):
        event = issue_event()
        current_issues = (
            ("closed", {**event["issue"], "state": "closed"}, "closed"),
            (
                "edited",
                {
                    **event["issue"],
                    "body": "request changed after this event was created",
                    "updated_at": "2026-11-07T05:01:00Z",
                },
                "revision differs",
            ),
        )

        class TrackingEnvironment(dict):
            def __init__(self, values):
                super().__init__(values)
                self.secret_reads = []

            def get(self, key, default=None):
                if key == "REPOSITORY_BOOTSTRAP_TOKEN":
                    self.secret_reads.append(key)
                return super().get(key, default)

        for name, current, expected_error in current_issues:
            with self.subTest(name=name):
                api = FakeIssueReadApi(current)
                environment = TrackingEnvironment(
                    {
                        **OWNER_EVENT_ENV,
                        "DEVFLOW_TOKEN": "read-token",
                        "REPOSITORY_BOOTSTRAP_TOKEN": "must-not-be-read",
                    }
                )
                with tempfile.TemporaryDirectory() as directory:
                    event_path = self.write_event(directory, event)
                    with patch.object(cli.os, "environ", environment), patch.object(
                        cli, "GitHubApi", return_value=api
                    ), patch.object(cli, "BootstrapExecutor") as executor:
                        with self.assertRaisesRegex(cli.EventError, expected_error):
                            cli.execute_event(event_path)
                executor.assert_not_called()
                self.assertEqual(environment.secret_reads, [])
                self.assertEqual(api.reads, [(REPOSITORY, 975)])

    def test_execute_fails_closed_when_current_issue_cannot_be_read(self):
        event = issue_event()
        api = FakeIssueReadApi(GitHubApiError("GET /issues/975 failed"))
        secret_reads = []

        class TrackingEnvironment(dict):
            def get(self, key, default=None):
                if key == "REPOSITORY_BOOTSTRAP_TOKEN":
                    secret_reads.append(key)
                return super().get(key, default)

        environment = TrackingEnvironment(
            {
                **OWNER_EVENT_ENV,
                "DEVFLOW_TOKEN": "read-token",
                "REPOSITORY_BOOTSTRAP_TOKEN": "must-not-be-read",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            event_path = self.write_event(directory, event)
            with patch.object(cli.os, "environ", environment), patch.object(
                cli, "GitHubApi", return_value=api
            ), patch.object(cli, "BootstrapExecutor") as executor:
                with self.assertRaisesRegex(cli.EventError, "revalidation failed"):
                    cli.execute_event(event_path)
        executor.assert_not_called()
        self.assertEqual(secret_reads, [])
        self.assertEqual(api.reads, [(REPOSITORY, 975)])

    def test_github_issue_reader_is_repository_scoped_and_rejects_invalid_numbers(self):
        api = GitHubApi("test-token")
        current = {"id": 975000, "number": 975, "state": "open"}
        with patch.object(api, "_request", return_value=current) as request:
            self.assertEqual(api.get_issue(REPOSITORY, 975), current)
        request.assert_called_once_with("GET", "/repos/kinoko34077/devflow/issues/975")
        for invalid in (0, -1, True, "975"):
            with self.subTest(issue_number=invalid):
                with self.assertRaises(BootstrapError):
                    api.get_issue(REPOSITORY, invalid)

    def test_execute_allows_unchanged_open_snapshot_retry(self):
        event = issue_event()
        api = FakeIssueReadApi({**event["issue"], "state": "open"})
        result = BootstrapResult(
            repository_url="https://github.com/kinoko34077/example-repo",
            head_sha="a" * 40,
            issue_urls=(),
            control_url=None,
            resources=(),
        )
        with tempfile.TemporaryDirectory() as directory:
            event_path = self.write_event(directory, event)
            with patch.dict(
                os.environ,
                {
                    **OWNER_EVENT_ENV,
                    "DEVFLOW_TOKEN": "read-token",
                    "REPOSITORY_BOOTSTRAP_TOKEN": "bootstrap-token",
                },
                clear=True,
            ), patch.object(cli, "GitHubApi", return_value=api), patch.object(
                cli, "BootstrapExecutor"
            ) as executor:
                executor.return_value.execute.return_value = result
                self.assertEqual(cli.execute_event(event_path), 0)
        self.assertEqual(api.reads, [(REPOSITORY, 975), (REPOSITORY, 975)])
        executor.return_value.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
