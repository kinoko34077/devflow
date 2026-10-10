"""#406: transient GraphQL retry, delayed Project membership and run diagnostics."""
import io
import json
import urllib.error
import unittest
from contextlib import redirect_stdout
from unittest import mock

from scripts import project_sync


class TransientRetryTests(unittest.TestCase):
    def test_http_504_retries_read_and_then_succeeds(self):
        failure = urllib.error.HTTPError(
            "https://api.github.com/graphql", 504, "Gateway Timeout", {},
            io.BytesIO(b"upstream gateway timeout"),
        )
        success = io.BytesIO(b'{"data":{"ok":true}}')
        with mock.patch.object(
            project_sync.urllib.request, "urlopen", side_effect=[failure, success]
        ) as urlopen, mock.patch.object(project_sync.time, "sleep") as sleep:
            self.assertEqual(project_sync.GitHubGraphQL("secret").query("query { viewer { login } }"), {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(project_sync.GRAPHQL_TRANSIENT_BACKOFF_SECONDS)

    def test_transient_fails_after_exactly_three_attempts(self):
        def always_fails(url, headers, payload):
            raise project_sync.TransientAPIError("HTTP 503 service unavailable")

        with mock.patch.object(project_sync.time, "sleep") as sleep:
            client = project_sync.GitHubGraphQL("secret", transport=always_fails)
            with self.assertRaisesRegex(project_sync.TransientAPIError, "503"):
                client.query("query { viewer { login } }")
        self.assertEqual(sleep.call_count, 2)

    def test_idempotent_field_update_retries_but_add_and_delete_do_not(self):
        operations = [
            ("mutation { updateProjectV2ItemFieldValue(input:{}) { projectV2Item { id } } }", 3),
            ("mutation { addProjectV2ItemById(input:{}) { item { id } } }", 1),
            ("mutation { deleteProjectV2Item(input:{}) { deletedItemId } }", 1),
            ("mutation { createProjectV2Field(input:{}) { projectV2Field { id } } }", 1),
        ]
        for document, expected in operations:
            with self.subTest(document=document):
                calls = []
                def transport(url, headers, payload):
                    calls.append(payload)
                    raise project_sync.TransientAPIError("HTTP 502")
                with mock.patch.object(project_sync.time, "sleep"):
                    with self.assertRaises(project_sync.TransientAPIError):
                        project_sync.GitHubGraphQL("secret", transport=transport).query(document)
                self.assertEqual(len(calls), expected)

    def test_non_transient_http_422_and_graphql_validation_never_retry(self):
        err = urllib.error.HTTPError(
            "https://api.github.com/graphql", 422, "Unprocessable", {},
            io.BytesIO(b"invalid text value"),
        )
        with mock.patch.object(project_sync.urllib.request, "urlopen", side_effect=err) as urlopen:
            with self.assertRaisesRegex(project_sync.APIError, "422"):
                project_sync.GitHubGraphQL("secret").query("query { viewer { login } }")
        self.assertEqual(urlopen.call_count, 1)

        calls = []
        def gql_errors(url, headers, payload):
            calls.append(1)
            return {"errors": [{"message": "Column value must be valid"}]}
        with self.assertRaisesRegex(project_sync.APIError, "Column value"):
            project_sync.GitHubGraphQL("secret", transport=gql_errors).query("query { viewer { login } }")
        self.assertEqual(len(calls), 1)

    def test_timeout_retries_queries_and_fails_closed_on_mutations(self):
        calls = []
        def timeout(url, headers, payload):
            calls.append(1)
            raise TimeoutError("timeout")
        with mock.patch.object(project_sync.time, "sleep") as sleep:
            with self.assertRaisesRegex(project_sync.APIError, "TimeoutError"):
                project_sync.GitHubGraphQL("secret", transport=timeout).query("query { node(id:\"X\") { id } }")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep.call_count, 2)
        calls.clear()
        with self.assertRaisesRegex(project_sync.APIError, "TimeoutError"):
            project_sync.GitHubGraphQL("secret", transport=timeout).query(
                "mutation { addProjectV2ItemById(input:{}) { item { id } } }"
            )
        self.assertEqual(len(calls), 1)


class MembershipReadbackTests(unittest.TestCase):
    class FakeREST:
        def __init__(self, issue, previous_health_body=""):
            self.issue = issue
            self.body = None
            self.previous_health_body = previous_health_body

        def list_labels(self, per_page=100):
            return [
                {"name": name}
                for name in project_sync.AUDIT_FRESHNESS_LABEL_SPECS
            ]

        def find_issue_by_title(self, title):
            return {
                "number": 41, "title": title, "state": "closed",
                "body": self.previous_health_body,
            }

        def get_issue(self, number):
            if number != self.issue["number"]:
                raise AssertionError("wrong issue")
            return self.issue

        def update_issue(self, number, body=None, state=None):
            if body is not None:
                self.body = body
            return {"number": number, "title": project_sync.HEALTH_TITLE, "state": state or "closed"}

    class FakeGQL:
        def __init__(self, visible_after):
            self.visible_after = visible_after
            self.reads = 0
            self.adds = []

        def get_project_identity(self, owner, number):
            return {"id": "P", "title": project_sync.PROJECT_TITLE, "public": False}

        def get_project_fields(self, project_id):
            fields = []
            for name in project_sync.EXPECTED_FIELDS:
                if name in project_sync.SELECT_OPTIONS:
                    fields.append({"id": name, "name": name, "kind": "single", "options": [
                        {"id": value, "name": value} for value in project_sync.SELECT_OPTIONS[name]
                    ]})
                else:
                    fields.append({"id": name, "name": name, "kind": "date" if name in project_sync.DATE_FIELDS else "text", "options": []})
            return fields

        def get_project_items(self, project_id):
            self.reads += 1
            if self.reads < self.visible_after:
                return []
            return [{"id": "I", "content_id": "SOURCE", "number": 406, "repository": project_sync.DEFAULT_REPOSITORY, "fields": {}}]

        def add_item(self, project_id, content_id):
            self.adds.append(content_id)
            return "I"

    def _run(self, visible_after, memory=None):
        issue = {
            "number": 406, "node_id": "SOURCE", "title": "[BUG] test",
            "state": "open", "author_association": "OWNER", "body": "",
        }
        prior = ""
        if memory:
            prior = project_sync.render_health_report(
                result="FAIL", mode="event-sync", project={},
                coverage={}, messages=[], run_url="older",
                unresolved_failures=memory,
            )
        rest = self.FakeREST(issue, previous_health_body=prior)
        gql = self.FakeGQL(visible_after)
        cfg = project_sync.RuntimeConfig(project_sync.DEFAULT_REPOSITORY, "secret-project", "secret-github")
        output = io.StringIO()
        with mock.patch.object(project_sync.time, "sleep") as sleep, redirect_stdout(output):
            code = project_sync.run_sync(
                "event-sync", cfg, rest=rest, gql=gql,
                event_issue=issue, run_url="run",
            )
        return code, rest, gql, sleep, output.getvalue()

    def test_delayed_visibility_converges_with_read_only_rechecks(self):
        code, rest, gql, sleep, log = self._run(visible_after=3)
        self.assertEqual(code, 0)
        self.assertEqual(gql.reads, 3)
        self.assertEqual(gql.adds, ["SOURCE"])
        self.assertEqual(sleep.call_count, 1)
        self.assertIn("## Result\nPASS", rest.body)
        self.assertIn("current_membership_drift=0", log)

    def test_persistent_absence_remains_failure_with_bounded_reads(self):
        code, rest, gql, sleep, log = self._run(visible_after=999)
        self.assertEqual(code, 1)
        self.assertEqual(gql.reads, 4)
        self.assertEqual(gql.adds, ["SOURCE"])
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("Project membership drift: 1", rest.body)
        self.assertIn("current_membership_drift=1", log)

    def test_clean_run_reports_retained_memory_separately_without_secret_values(self):
        state = {"24": {"mode": "event-sync", "run_url": "old", "message": "HTTP 504"}}
        code, rest, gql, sleep, log = self._run(visible_after=1, memory=state)
        self.assertEqual(code, 1)
        self.assertIn("current_errors=0", log)
        self.assertIn("current_membership_drift=0", log)
        self.assertIn("retained_failure_keys=24", log)
        self.assertIn("aggregate=FAIL", log)
        self.assertNotIn("secret-", log)
        self.assertIn("## Result\nFAIL", rest.body)
        self.assertIn("Unresolved Project sync failure memory remains", rest.body)


if __name__ == "__main__":
    unittest.main()
