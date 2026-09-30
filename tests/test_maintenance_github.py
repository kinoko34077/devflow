import unittest

try:
    from tools import maintenance_github as mg
except ImportError:
    mg = None


class MaintenanceGitHubTransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(mg, "maintenance_github module must exist")

    def test_transport_exposes_read_methods_only(self):
        transport = mg.GitHubReadTransport("secret")
        for name in ("post", "patch", "put", "delete", "update_issue", "merge_pr"):
            self.assertFalse(hasattr(transport, name), name)

    def test_transport_redacts_token_from_error(self):
        class Broken(mg.GitHubReadTransport):
            def _request_json(self, path):
                raise mg.GitHubReadError("request failed")
        with self.assertRaises(mg.GitHubReadError) as caught:
            Broken("super-secret-token").get_issue("o/r", 1)
        self.assertNotIn("super-secret-token", str(caught.exception))

    def test_collect_repository_preserves_source_failure(self):
        class Fake:
            def get_repository(self, repository):
                return {"full_name": repository, "default_branch": "main", "revision": "repo-v1"}
            def get_issue(self, repository, number):
                raise mg.GitHubReadError("unavailable")
        value = mg.collect_repository(Fake(), "o/r", "o/r#1", "2026-10-01T00:00:00Z")
        self.assertEqual(value["repository"], "o/r")
        self.assertIn("source_error", value)

    def test_collect_portfolio_is_repository_sorted(self):
        class Fake:
            def get_repository(self, repository):
                return {"full_name": repository, "default_branch": "main", "revision": "repo-v1"}
            def get_issue(self, repository, number):
                return {
                    "repository": repository,
                    "ref": f"{repository}#{number}",
                    "trusted": True,
                    "revision": f"issue-{number}",
                    "state": "OPEN",
                    "body": "",
                }
        controls = [
            {"repository": "z/r", "control_ref": "z/r#2"},
            {"repository": "a/r", "control_ref": "a/r#1"},
        ]
        values = mg.collect_portfolio(Fake(), controls, "2026-10-01T00:00:00Z")
        self.assertEqual([v["repository"] for v in values], ["a/r", "z/r"])


if __name__ == "__main__":
    unittest.main()
