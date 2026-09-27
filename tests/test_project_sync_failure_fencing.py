import unittest

from scripts import project_sync


class ProjectSyncTransportBoundaryTests(unittest.TestCase):
    def test_graphql_transport_timeout_is_normalized(self):
        def transport(url, headers, payload):
            raise TimeoutError("timed out")

        client = project_sync.GitHubGraphQL("project-token", transport=transport)
        with self.assertRaisesRegex(
            project_sync.APIError,
            "GitHub GraphQL transport failed: TimeoutError",
        ):
            client.query("query { viewer { login } }")

    def test_rest_transport_timeout_is_normalized(self):
        def transport(method, url, headers, payload):
            raise TimeoutError("timed out")

        client = project_sync.GitHubREST(
            "repo-token",
            "kinoko34077/devflow",
            transport=transport,
        )
        with self.assertRaisesRegex(
            project_sync.APIError,
            "GitHub REST transport failed: TimeoutError",
        ):
            client.get_issue(16)

    def test_graphql_non_object_response_is_rejected(self):
        def transport(url, headers, payload):
            return []

        client = project_sync.GitHubGraphQL("project-token", transport=transport)
        with self.assertRaisesRegex(
            project_sync.APIError,
            "GitHub GraphQL response was not an object",
        ):
            client.query("query { viewer { login } }")

    def test_run_sync_records_normalized_transport_failure_in_health(self):
        def transport(url, headers, payload):
            raise TimeoutError("timed out")

        class FakeREST:
            def __init__(self):
                self.body = None

            def find_issue_by_title(self, title):
                return {"number": 41, "title": title, "state": "closed"}

            def update_issue(self, number, body=None, state=None):
                if body is not None:
                    self.body = body
                return {"number": number, "title": project_sync.HEALTH_TITLE, "state": state or "closed"}

        cfg = project_sync.RuntimeConfig(
            "kinoko34077/devflow",
            "project-token",
            "repo-token",
        )
        rest = FakeREST()
        gql = project_sync.GitHubGraphQL("project-token", transport=transport)

        code = project_sync.run_sync(
            "verify",
            cfg,
            rest=rest,
            gql=gql,
            run_url="run",
        )

        self.assertEqual(code, 1)
        self.assertIn("## Result\nFAIL", rest.body)
        self.assertIn("GitHub GraphQL transport failed: TimeoutError", rest.body)


if __name__ == "__main__":
    unittest.main()
