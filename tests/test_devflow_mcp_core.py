import unittest
from urllib.error import HTTPError

from tools import devflow_mcp_core


class DevflowMCPParsingTests(unittest.TestCase):
    def test_normalize_repository_accepts_short_and_full_names(self):
        self.assertEqual(
            devflow_mcp_core.normalize_repository("SynTrail-LM"),
            "kinoko34077/SynTrail-LM",
        )
        self.assertEqual(
            devflow_mcp_core.normalize_repository("kinoko34077/devflow"),
            "kinoko34077/devflow",
        )

    def test_normalize_repository_rejects_blank_name(self):
        with self.assertRaises(devflow_mcp_core.DevflowMCPError):
            devflow_mcp_core.normalize_repository("   ")

    def test_parse_sections_reads_h2_scalar_sections(self):
        body = "## Work Status\n\n`AUDITED`\n\n## Next Action\n\n[WAIT]\n"
        self.assertEqual(
            devflow_mcp_core.parse_sections(body),
            {"Work Status": "AUDITED", "Next Action": "[WAIT]"},
        )


class FakeReader:
    def __init__(self, issues):
        self.issues = issues
        self.calls = []

    def list_issues(self, repository, state="open"):
        self.calls.append((repository, state))
        return list(self.issues)

    def get_issue(self, repository, issue_number):
        self.calls.append((repository, issue_number))
        for issue in self.issues:
            if int(issue.get("number", 0)) == issue_number:
                return issue
        raise AssertionError("issue not found")


class DevflowMCPServiceTests(unittest.TestCase):
    def setUp(self):
        self.control = {
            "number": 16,
            "title": "[REPO] devflow",
            "html_url": "https://github.com/kinoko34077/devflow/issues/16",
            "state": "open",
            "body": (
                "## Repository\n\n`kinoko34077/devflow`\n\n"
                "## Work Status\n\n`AUDITED`\n\n"
                "## Repository State\n\n`ACTIVE`\n\n"
                "## Audit SHA\n\n`abc123`\n\n"
                "## Active Work\n\n#41 Sync Health\n\n"
                "## Next Action\n\n`normal operation [WAIT]`\n\n"
                "## Canonical Entry Points\n\n- Agent start: `AGENTS.md`\n\n"
                "## Detailed Current State\n\nOperational.\n\n"
                "## Control Notes\n\nKeep open.\n"
            ),
        }
        self.health = {
            "number": 41,
            "title": devflow_mcp_core.HEALTH_TITLE,
            "html_url": "https://github.com/kinoko34077/devflow/issues/41",
            "state": "closed",
            "body": "## Result\n\nPASS\n\n## Mode\n\nevent-sync\n",
        }

    def test_repository_control_uses_exact_title_match(self):
        reader = FakeReader([
            {**self.control, "number": 99, "title": "[REPO] devflow-old"},
            self.control,
        ])
        service = devflow_mcp_core.DevflowService(reader)
        result = service.get_repository_control("devflow")
        self.assertEqual(result["issue_number"], 16)
        self.assertEqual(result["repository"], "kinoko34077/devflow")

    def test_bootstrap_returns_live_control_fields_and_read_order(self):
        service = devflow_mcp_core.DevflowService(FakeReader([self.control]))
        result = service.bootstrap_repository("kinoko34077/devflow")
        self.assertEqual(result["work_status"], "AUDITED")
        self.assertEqual(result["repository_state"], "ACTIVE")
        self.assertEqual(result["audit_sha"], "abc123")
        self.assertEqual(result["canonical_entry_points"], "- Agent start: `AGENTS.md`")
        self.assertEqual(result["read_order"][0], "devflow/AGENTS.md")
        self.assertIn("owning repository", result["authority"])

    def test_list_managed_repositories_ignores_non_control_issues(self):
        service = devflow_mcp_core.DevflowService(
            FakeReader([self.control, {"number": 61, "title": "Work Order: x", "body": ""}])
        )
        self.assertEqual(service.list_managed_repositories(), ["kinoko34077/devflow"])

    def test_sync_health_reads_closed_health_issue_from_all_states(self):
        reader = FakeReader([self.health])
        service = devflow_mcp_core.DevflowService(reader)
        result = service.get_sync_health()
        self.assertEqual(result["result"], "PASS")
        self.assertIn((devflow_mcp_core.DEVFLOW_REPOSITORY, "all"), reader.calls)

    def test_missing_control_fails_without_guessing(self):
        service = devflow_mcp_core.DevflowService(FakeReader([]))
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control"):
            service.get_repository_control("missing-repo")


class GitHubReadOnlyClientTests(unittest.TestCase):
    def test_reader_uses_get_only_transport_and_bearer_token(self):
        calls = []

        def transport(url, headers):
            calls.append((url, headers))
            return [{"number": 1, "title": "x"}]

        reader = devflow_mcp_core.GitHubReader(token="secret", transport=transport)
        result = reader.list_issues("kinoko34077/devflow")
        self.assertEqual(result[0]["number"], 1)
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret")
        self.assertNotIn("method", calls[0][1])

    def test_http_access_error_mentions_token_for_private_or_inaccessible_repo(self):
        def transport(url, headers):
            raise HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

        reader = devflow_mcp_core.GitHubReader(token="", transport=transport)
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "GITHUB_TOKEN"):
            reader.get_issue("kinoko34077/private-repo", 1)


if __name__ == "__main__":
    unittest.main()
