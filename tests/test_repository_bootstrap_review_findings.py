import unittest

from tools import repository_bootstrap as rb
from tests.test_repository_bootstrap import issue_body, request_payload
from tests.test_repository_bootstrap_executor import FakeApi


class RepositoryBootstrapReviewFindingTests(unittest.TestCase):
    def test_unknown_contract_keys_fail_closed_at_every_object_level(self):
        mutations = []

        payload = request_payload()
        payload["unexpected_root"] = True
        mutations.append(payload)

        for section in (
            "repository",
            "classification",
            "bootstrap",
            "initial_content",
            "devflow",
        ):
            payload = request_payload()
            payload[section]["unexpected_key"] = True
            mutations.append(payload)

        payload = request_payload()
        payload["issues"][0]["unexpected_key"] = True
        mutations.append(payload)

        for payload in mutations:
            with self.subTest(payload=payload):
                with self.assertRaises(rb.BootstrapError):
                    rb.normalize_request(
                        rb.parse_request_body(issue_body(payload)),
                        "[REPO CREATE] example-repo",
                    )

    def test_control_lookup_uses_authoritative_issue_listing_not_search_index(self):
        class SearchLagApi(FakeApi):
            def find_issues_by_exact_title(self, full_name, title, state="open"):
                return []

        api = SearchLagApi()
        full_name = "kinoko34077/devflow"
        api.issues[full_name] = [
            {
                "number": 42,
                "title": "[REPO] example-repo",
                "body": "## Repository\n\n`kinoko34077/example-repo`\n",
                "state": "open",
                "html_url": "https://github.com/kinoko34077/devflow/issues/42",
            }
        ]

        matches = rb.BootstrapExecutor._find_exact_title(
            api, full_name, "[REPO] example-repo"
        )
        self.assertEqual([issue["number"] for issue in matches], [42])


if __name__ == "__main__":
    unittest.main()
