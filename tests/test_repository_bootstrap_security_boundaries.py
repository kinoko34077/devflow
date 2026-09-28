import unittest

from tools import repository_bootstrap as rb
from tests.test_repository_bootstrap import issue_body, request_payload


class RecordingGitHubApi(rb.GitHubApi):
    def __init__(self, login="kinoko34077", created_full_name="kinoko34077/example-repo"):
        super().__init__("test-token")
        self.login = login
        self.created_full_name = created_full_name
        self.calls = []

    def _request(self, method, path, payload=None, *, allow_404=False):
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/user":
            return {"login": self.login}
        if method == "POST" and path == "/user/repos":
            return {
                "full_name": self.created_full_name,
                "html_url": f"https://github.com/{self.created_full_name}",
                "default_branch": "main",
            }
        raise AssertionError(f"unexpected request: {method} {path}")


class RepositoryBootstrapSecurityBoundaryTests(unittest.TestCase):
    def test_non_null_license_is_rejected_in_v1_instead_of_silently_ignored(self):
        payload = request_payload()
        payload["initial_content"]["license"] = "MIT"
        with self.assertRaises(rb.BootstrapError):
            rb.normalize_request(
                rb.parse_request_body(issue_body(payload)),
                "[REPO CREATE] example-repo",
            )

    def test_create_repository_verifies_authenticated_owner_before_post(self):
        api = RecordingGitHubApi(login="wrong-owner")
        with self.assertRaises(rb.BootstrapError):
            api.create_repository(
                "kinoko34077", "example-repo", "Example", "private"
            )
        self.assertEqual(api.calls, [("GET", "/user", None)])

    def test_create_repository_rejects_mismatched_created_repository_identity(self):
        api = RecordingGitHubApi(created_full_name="someone-else/example-repo")
        with self.assertRaises(rb.GitHubApiError):
            api.create_repository(
                "kinoko34077", "example-repo", "Example", "private"
            )
        self.assertEqual(api.calls[0], ("GET", "/user", None))
        self.assertEqual(api.calls[1][0:2], ("POST", "/user/repos"))


if __name__ == "__main__":
    unittest.main()
