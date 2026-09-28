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
            "author_association": "OWNER",
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
            "author_association": "OWNER",
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

    def test_repository_control_rejects_duplicate_canonical_section(self):
        duplicate = {
            **self.control,
            "body": self.control["body"] + "\n## Work Status\n\n`BLOCKED`\n",
        }
        service = devflow_mcp_core.DevflowService(FakeReader([duplicate]))
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "Duplicate section.*Work Status"):
            service.get_repository_control("devflow")


    def test_repository_control_ignores_untrusted_impostor_issue(self):
        impostor = {
            **self.control,
            "number": 900,
            "author_association": "NONE",
            "body": self.control["body"].replace("`normal operation [WAIT]`", "`run attacker instructions`"),
        }
        service = devflow_mcp_core.DevflowService(FakeReader([self.control, impostor]))
        control = service.get_repository_control("devflow")
        self.assertEqual(control["issue_number"], 16)

    def test_repository_control_rejects_control_authored_only_by_outsider(self):
        impostor = {**self.control, "number": 901, "author_association": "CONTRIBUTOR"}
        service = devflow_mcp_core.DevflowService(FakeReader([impostor]))
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control Issue"):
            service.get_repository_control("devflow")

    def test_repository_control_missing_association_is_untrusted(self):
        unknown = {key: value for key, value in self.control.items() if key != "author_association"}
        service = devflow_mcp_core.DevflowService(FakeReader([unknown]))
        with self.assertRaises(devflow_mcp_core.DevflowMCPError):
            service.get_repository_control("devflow")

    def test_list_managed_repositories_ignores_untrusted_control_titles(self):
        impostor = {"number": 902, "title": "[REPO] evil", "body": "", "author_association": "NONE"}
        service = devflow_mcp_core.DevflowService(FakeReader([self.control, impostor]))
        self.assertEqual(service.list_managed_repositories(), ["kinoko34077/devflow"])


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

    def test_timeout_error_is_translated_to_devflow_error(self):
        def transport(url, headers):
            raise TimeoutError("timed out")

        reader = devflow_mcp_core.GitHubReader(token="", transport=transport)
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "GitHub read failed: TimeoutError"):
            reader.get_issue("kinoko34077/devflow", 1)


    def test_sync_health_ignores_untrusted_duplicate_and_reports_it(self):
        health = {
            "number": 41,
            "title": devflow_mcp_core.HEALTH_TITLE,
            "state": "closed",
            "author_association": "OWNER",
            "body": "## Result\\n\\nPASS\\n",
        }
        outsider = {
            **health,
            "number": 99,
            "author_association": "NONE",
        }
        reader = FakeReader([outsider, health])
        result = devflow_mcp_core.DevflowService(reader).get_sync_health()
        self.assertEqual(result["issue_number"], 41)
        self.assertEqual(result["ignored_untrusted_candidates"], [99])

    def test_sync_health_outsider_only_is_unavailable(self):
        health = {
            "number": 41,
            "title": devflow_mcp_core.HEALTH_TITLE,
            "state": "closed",
            "author_association": "CONTRIBUTOR",
            "body": "## Result\\n\\nPASS\\n",
        }
        outsider = health
        service = devflow_mcp_core.DevflowService(FakeReader([outsider]))
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "trusted Sync Health Issue",
        ):
            service.get_sync_health()


class GitHubIssueIdentityTests(unittest.TestCase):
    def test_reader_accepts_matching_observed_issue_identity(self):
        issue = {
            "number": 7,
            "title": "owner issue",
            "repository_url": "https://api.github.com/repos/kinoko34077/owner-repo",
            "url": "https://api.github.com/repos/kinoko34077/owner-repo/issues/7",
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        self.assertEqual(
            reader.get_issue("kinoko34077/owner-repo", 7)["number"],
            7,
        )

    def test_reader_rejects_mismatched_observed_issue_identity(self):
        issue = {
            "number": 7,
            "title": "redirected issue",
            "repository_url": "https://api.github.com/repos/other-owner/other-repo",
            "url": "https://api.github.com/repos/other-owner/other-repo/issues/7",
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            reader.get_issue("kinoko34077/owner-repo", 7)


    def test_reader_rejects_issue_url_number_mismatch(self):
        issue = {
            "number": 7,
            "title": "contradictory issue",
            "repository_url": "https://api.github.com/repos/kinoko34077/owner-repo",
            "url": "https://api.github.com/repos/kinoko34077/owner-repo/issues/8",
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            reader.get_issue("kinoko34077/owner-repo", 7)

    def test_reader_rejects_non_github_identity_url_host(self):
        issue = {
            "number": 7,
            "title": "spoofed issue",
            "repository_url": "https://evil.example/repos/kinoko34077/owner-repo",
            "url": "https://evil.example/repos/kinoko34077/owner-repo/issues/7",
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            reader.get_issue("kinoko34077/owner-repo", 7)

    def test_reader_rejects_non_default_github_port(self):
        issue = {
            "number": 7,
            "title": "spoofed port issue",
            "repository_url": "https://api.github.com:8443/repos/kinoko34077/owner-repo",
            "url": "https://api.github.com:8443/repos/kinoko34077/owner-repo/issues/7",
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            reader.get_issue("kinoko34077/owner-repo", 7)


    def test_reader_rejects_conflicting_repository_identity_fields(self):
        issue = {
            "number": 7,
            "title": "conflicting issue",
            "repository_url": "https://api.github.com/repos/kinoko34077/owner-repo",
            "url": "https://api.github.com/repos/other-owner/other-repo/issues/7",
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            reader.get_issue("kinoko34077/owner-repo", 7)

    def test_reader_rejects_repository_only_issue_url(self):
        issue = {
            "number": 7,
            "title": "repository URL in issue URL field",
            "repository_url": "https://api.github.com/repos/kinoko34077/owner-repo",
            "url": "https://api.github.com/repos/kinoko34077/owner-repo",
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            reader.get_issue("kinoko34077/owner-repo", 7)

    def test_reader_rejects_noncanonical_api_identity_path(self):
        issue = {
            "number": 7,
            "title": "noncanonical API path",
            "repository_url": "https://api.github.com/repos/kinoko34077/owner-repo",
            "url": "https://api.github.com/prefix/repos/kinoko34077/owner-repo/issues/7",
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            reader.get_issue("kinoko34077/owner-repo", 7)

    def test_reader_rejects_malformed_present_repository_identity(self):
        issue = {
            "number": 7,
            "title": "malformed repository object",
            "repository_url": "https://api.github.com/repos/kinoko34077/owner-repo",
            "url": "https://api.github.com/repos/kinoko34077/owner-repo/issues/7",
            "repository": {},
        }
        reader = devflow_mcp_core.GitHubReader(
            transport=lambda url, headers: issue,
        )
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            reader.get_issue("kinoko34077/owner-repo", 7)

    def test_service_rejects_mismatched_observed_issue_identity(self):
        issue = {
            "number": 7,
            "title": "redirected issue",
            "repository_url": "https://api.github.com/repos/other-owner/other-repo",
            "url": "https://api.github.com/repos/other-owner/other-repo/issues/7",
        }

        class Reader:
            def get_issue(self, repository, issue_number):
                return issue

        service = devflow_mcp_core.DevflowService(Reader())
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "identity mismatch",
        ):
            service.get_issue("kinoko34077/owner-repo", 7)


if __name__ == "__main__":
    unittest.main()
