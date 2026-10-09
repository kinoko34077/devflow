"""Security/regression tests for bounded GitHub Bootstrap HTTP diagnostics."""

import io
import json
import unittest
import urllib.error
from email.message import Message
from unittest import mock

from tools import github_api_http_diagnostics as diagnostics
from tools import repository_bootstrap as bootstrap


def github_headers(**headers):
    message = Message()
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    return message


def make_http_error(status, body, headers=None):
    return urllib.error.HTTPError(
        "https://api.github.com/repos/kinoko34077/fixture/contents/example",
        status,
        "error",
        headers or Message(),
        io.BytesIO(body),
    )


class GitHubErrorDiagnosticsTest(unittest.TestCase):
    def classify(self, status, message, **headers):
        return diagnostics.summarize_github_http_error(
            status,
            github_headers(**headers),
            json.dumps({"message": message}).encode("utf-8"),
        )

    def test_known_workflow_scope_failure(self):
        result = self.classify(
            403,
            "refusing to allow a Personal Access Token to create or update workflow "
            "'.github/workflows/test.yml' without workflow scope",
            X_Accepted_GitHub_Permissions="contents=write,workflows=write",
            X_GitHub_Request_Id="AA12:BB34:CC56",
        )
        self.assertIn("category=workflow_scope_denied", result)
        self.assertIn("accepted_permissions=contents=write,workflows=write", result)
        self.assertIn("request_id=AA12:BB34:CC56", result)

    def test_unknown_403_is_not_automatically_a_scope_error(self):
        result = self.classify(403, "Forbidden")
        self.assertEqual(result, "category=forbidden_unclassified")

    def test_integration_permission_denial(self):
        self.assertIn(
            "category=integration_permission_denied",
            self.classify(403, "Resource not accessible by personal access token"),
        )

    def test_branch_rules_denial(self):
        self.assertIn(
            "category=repository_policy_denied",
            self.classify(403, "Repository rule violations found for refs/heads/main"),
        )

    def test_primary_rate_limit_uses_authoritative_remaining(self):
        result = self.classify(
            403,
            "some other message",
            X_RateLimit_Remaining="0",
            X_RateLimit_Reset="1790000000",
            Retry_After="45",
        )
        self.assertIn("category=primary_rate_limited", result)
        self.assertIn("rate_remaining=0", result)
        self.assertIn("rate_reset_epoch=1790000000", result)
        self.assertIn("retry_after_seconds=45", result)

    def test_secondary_rate_limit(self):
        self.assertIn(
            "category=secondary_rate_limited",
            self.classify(403, "You have exceeded a secondary rate limit."),
        )

    def test_fallback_429(self):
        self.assertIn("category=rate_limited", self.classify(429, "Try again"))

    def test_accepted_permissions_preserve_alternative_semantics(self):
        result = self.classify(
            403,
            "Forbidden",
            X_Accepted_GitHub_Permissions="contents=write,workflows=write; contents=read",
        )
        self.assertIn(
            "accepted_permissions=contents=write,workflows=write;contents=read",
            result,
        )

    def test_reject_unrecognized_or_malicious_headers(self):
        result = self.classify(
            403,
            "Forbidden",
            X_Accepted_GitHub_Permissions="contents=write;token=ghp_secret",
            X_GitHub_Request_Id="ABC\\nAuthorization: Bearer secret",
            Retry_After="9;secret",
            X_RateLimit_Remaining="-1",
        )
        self.assertEqual(result, "category=forbidden_unclassified")

    def test_request_id_must_be_hex_groups_not_opaque_token(self):
        result = self.classify(
            403, "Forbidden", X_GitHub_Request_Id="A" * 64,
        )
        self.assertEqual(result, "category=forbidden_unclassified")

    def test_adapter_reads_only_bounded_error_body(self):
        class TrackingBuffer(io.BytesIO):
            def __init__(self, content):
                super().__init__(content)
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                return super().read(size)

        buffer = TrackingBuffer(
            b'{"message":"Forbidden"}' + b"z" * 6000 + b"secret"
        )
        exception = urllib.error.HTTPError(
            "https://api.github.com/repos/kinoko34077/fixture/contents/x",
            403, "error", Message(), buffer,
        )
        with mock.patch("tools.repository_bootstrap.urllib.request.urlopen", side_effect=exception):
            with self.assertRaises(bootstrap.GitHubApiError) as caught:
                bootstrap.GitHubApi("dummy-token").get_repository("kinoko34077/fixture")
        self.assertEqual(buffer.read_sizes, [diagnostics.MAX_ERROR_BODY_BYTES])
        self.assertIn("category=forbidden_unclassified", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))

    def test_never_echo_arbitrary_github_response(self):
        secret = "ghp_EXAMPLE_SECRET_DO_NOT_PRINT"
        data = json.dumps({
            "message": f"Forbidden: {secret}",
            "errors": [{"message": "Bearer " + secret, "code": "custom"}],
            "documentation_url": "https://example.invalid/?token=" + secret,
        }).encode("utf-8")
        result = diagnostics.summarize_github_http_error(
            403,
            github_headers(X_GitHub_Request_Id="PRIVATE-KEY:" + secret),
            data,
        )
        self.assertEqual(result, "category=forbidden_unclassified")
        self.assertNotIn(secret, result)

    def test_malformed_and_oversize_body_are_bounded(self):
        self.assertEqual(
            diagnostics.summarize_github_http_error(403, None, b"not-json"),
            "category=forbidden_unclassified",
        )
        payload = b"x" * diagnostics.MAX_ERROR_BODY_BYTES + b"SECRET"
        self.assertEqual(
            diagnostics.summarize_github_http_error(403, None, payload),
            "category=forbidden_unclassified",
        )

    def test_http_error_adapter_emits_only_safe_diagnostics(self):
        secret = "github_pat_secret_should_not_appear"
        headers = github_headers(
            X_GitHub_Request_Id="1234:ABCD:5678",
            X_Accepted_GitHub_Permissions="contents=write,workflows=write",
        )
        exception = make_http_error(
            403,
            json.dumps({"message": f"some unexpected text {secret}"}).encode("utf-8"),
            headers,
        )
        with mock.patch("tools.repository_bootstrap.urllib.request.urlopen", side_effect=exception):
            with self.assertRaises(bootstrap.GitHubApiError) as caught:
                bootstrap.GitHubApi("dummy-token").create_file(
                    "kinoko34077/fixture", ".github/workflows/receiver.yml",
                    "name: receiver\n", "seed workflow",
                )
        message = str(caught.exception)
        self.assertIn("HTTP 403", message)
        self.assertIn("category=forbidden_unclassified", message)
        self.assertIn("accepted_permissions=contents=write,workflows=write", message)
        self.assertIn("request_id=1234:ABCD:5678", message)
        self.assertNotIn(secret, message)
        self.assertNotIn("dummy-token", message)
        self.assertIsNone(caught.exception.__cause__)

    def test_allow_404_keeps_existing_contract(self):
        exception = make_http_error(404, b'{"message":"Not Found"}')
        with mock.patch("tools.repository_bootstrap.urllib.request.urlopen", side_effect=exception):
            result = bootstrap.GitHubApi("dummy-token").get_repository("kinoko34077/missing")
        self.assertIsNone(result)

    def test_unauthorized_and_validation_categories(self):
        self.assertIn("category=unauthorized", self.classify(401, "Bad credentials"))
        self.assertIn("category=validation_failed", self.classify(422, "Validation Failed"))


if __name__ == "__main__":
    unittest.main()
