import base64
import json
import unittest
from urllib.error import HTTPError

from tools import devflow_mcp_core
from tools import repository_projection
from tests.test_repository_bootstrap import issue_body, request_payload


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
    def __init__(self, issues, *, issues_by_repository=None, files=None, comments=None):
        self.issues = issues
        self.issues_by_repository = issues_by_repository or {}
        self.files = files or {}
        self.comments = comments or {}
        self.calls = []

    def list_issues(self, repository, state="open"):
        self.calls.append((repository, state))
        issues = self.issues_by_repository.get(repository, self.issues)
        if state == "open":
            return [issue for issue in issues if issue.get("state", "open") == "open"]
        if state == "closed":
            return [issue for issue in issues if issue.get("state") == "closed"]
        return list(issues)

    def get_issue(self, repository, issue_number):
        self.calls.append((repository, issue_number))
        issues = self.issues_by_repository.get(repository, self.issues)
        for issue in issues:
            if int(issue.get("number", 0)) == issue_number:
                return issue
        raise AssertionError("issue not found")

    def list_issue_comments(self, repository, issue_number):
        self.calls.append((repository, "comments", issue_number))
        return list(self.comments.get((repository, issue_number), []))

    def get_file(self, repository, path):
        self.calls.append((repository, "file", path))
        return self.files.get((repository, path))


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
            "title": devflow_mcp_core.HEALTH_TITLE,
            "html_url": "https://github.com/kinoko34077/devflow/issues/41",
            "state": "closed",
            "author_association": "OWNER",
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


    def test_repository_control_rejects_invalid_work_status_from_shared_contract(self):
        invalid = {
            **self.control,
            "body": self.control["body"].replace("`AUDITED`", "`IN_PROGRESS`", 1),
        }
        service = devflow_mcp_core.DevflowService(FakeReader([invalid]))
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "invalid Work Status"):
            service.get_repository_control("devflow")

    def test_repository_control_rejects_invalid_audit_depth_from_shared_contract(self):
        invalid = {
            **self.control,
            "body": self.control["body"]
            + "\n## Audit Depth\n\n`TARGETED`\n",
        }
        service = devflow_mcp_core.DevflowService(FakeReader([invalid]))
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "invalid Audit Depth"):
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


class BootstrapDerivedControlTrustTests(unittest.TestCase):
    repository = "kinoko34077/UniverseGenome"
    request_ref = "kinoko34077/devflow#313"
    request_url = "https://github.com/kinoko34077/devflow/issues/313"
    missing = object()

    def _request(
        self,
        *,
        association="OWNER",
        state="open",
        state_reason=None,
        name="UniverseGenome",
    ):
        payload = request_payload()
        payload["repository"] = {
            "owner": "kinoko34077",
            "name": name,
            "description": "test",
            "visibility": "private",
        }
        return {
            "number": 313,
            "title": f"[REPO CREATE] {name}",
            "repository_url": "https://api.github.com/repos/kinoko34077/devflow",
            "url": "https://api.github.com/repos/kinoko34077/devflow/issues/313",
            "html_url": "https://github.com/kinoko34077/devflow/issues/313",
            "state": state,
            "state_reason": state_reason,
            "author_association": association,
            "body": issue_body(payload),
        }

    def _control_body(self, *, request_ref=None, request_url=None):
        return (
            "## Repository\n\n`kinoko34077/UniverseGenome`\n\n"
            "## Detailed Current State\n\n"
            f"Repository was initialized through `{request_ref or self.request_ref}` using `repository-bootstrap.v1`. "
            "Accepted initial head is `7dfa6133767c6adab8d4bfadcfa366b5deff9249`.\n\n"
            "## Control Notes\n\n"
            f"Cross-repository routing summary only. Bootstrap request: {request_url or self.request_url}."
        )

    def _actual_legacy_control_body(self):
        return (
            "## Repository\n\n`kinoko34077/UniverseGenome`\n\n"
            "## Control Notes\n\n"
            f"Cross-repository routing summary only. Bootstrap request: {self.request_url}. "
            "Repository kind: `research`. Detailed technical truth belongs in `kinoko34077/UniverseGenome`."
        )

    def _done_comment(self, *, repository=None, control_number=314):
        target = repository or self.repository
        return {
            "body": (
                "Repository-Bootstrap-State: DONE\n"
                f"Repository: https://github.com/{target}\n"
                "Initial-Accepted-SHA: `7dfa6133767c6adab8d4bfadcfa366b5deff9249`\n"
                "Initial-Issue: https://github.com/kinoko34077/UniverseGenome/issues/1\n"
                f"Repository-Control: https://github.com/kinoko34077/devflow/issues/{control_number}"
            ),
            "author_association": "NONE",
            "user": {"login": "github-actions[bot]"},
            "performed_via_github_app": {"slug": "github-actions"},
        }

    def _provenance(self, *, repository=None, request_ref=None, request_url=None):
        return json.dumps(
            {
                "schema": "repository-bootstrap-provenance.v1",
                "request_ref": request_ref or self.request_ref,
                "request_url": request_url or self.request_url,
                "repository": repository or self.repository,
            },
            indent=2,
            sort_keys=True,
        ) + "\n"

    def _service(self, *, control=None, request=None, target_file=missing, comments=None):
        control = control or {
            "number": 314,
            "title": "[REPO] UniverseGenome",
            "html_url": "https://github.com/kinoko34077/devflow/issues/314",
            "state": "open",
            "author_association": "NONE",
            "body": self._control_body(),
        }
        request = request or self._request()
        files = {}
        if target_file is self.missing:
            files[(self.repository, ".github/repository-bootstrap.json")] = {
                "content": self._provenance()
            }
        elif target_file is not None:
            files[(self.repository, ".github/repository-bootstrap.json")] = {"content": target_file}
        reader = FakeReader(
            [],
            issues_by_repository={
                "kinoko34077/devflow": [control, request],
            },
            files=files,
            comments={("kinoko34077/devflow", 313): comments if comments is not None else [self._done_comment()]},
        )
        return devflow_mcp_core.DevflowService(reader)

    def test_existing_bootstrap_chain_accepts_legacy_generated_control(self):
        result = self._service().get_repository_control(self.repository)
        self.assertEqual(result["issue_number"], 314)
        self.assertEqual(result["repository"], self.repository)

    def test_completed_closed_bootstrap_request_remains_trusted(self):
        result = self._service(
            request=self._request(
                state="closed",
                state_reason="completed",
            )
        ).get_repository_control(self.repository)

        self.assertEqual(result["issue_number"], 314)

    def test_closed_not_planned_bootstrap_request_is_rejected(self):
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "No open Repository Control",
        ):
            self._service(
                request=self._request(
                    state="closed",
                    state_reason="not_planned",
                )
            ).get_repository_control(self.repository)

    def test_closed_request_without_state_reason_is_rejected(self):
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "No open Repository Control",
        ):
            self._service(
                request=self._request(
                    state="closed",
                    state_reason=None,
                )
            ).get_repository_control(self.repository)

    def test_closed_request_with_unknown_state_reason_is_rejected(self):
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "No open Repository Control",
        ):
            self._service(
                request=self._request(
                    state="closed",
                    state_reason="mystery",
                )
            ).get_repository_control(self.repository)

    def test_closed_completed_request_without_terminal_done_is_rejected(self):
        with self.assertRaisesRegex(
            devflow_mcp_core.DevflowMCPError,
            "No open Repository Control",
        ):
            self._service(
                request=self._request(
                    state="closed",
                    state_reason="completed",
                ),
                comments=[],
            ).get_repository_control(self.repository)

    def test_existing_bootstrap_chain_accepts_actual_legacy_control_notes_shape(self):
        control = {
            "number": 314,
            "title": "[REPO] UniverseGenome",
            "html_url": "https://github.com/kinoko34077/devflow/issues/314",
            "state": "open",
            "author_association": "NONE",
            "body": self._actual_legacy_control_body(),
        }
        result = self._service(control=control).get_repository_control(self.repository)
        self.assertEqual(result["issue_number"], 314)

    def test_list_managed_repositories_accepts_verified_bootstrap_control(self):
        self.assertEqual(
            devflow_mcp_core.DevflowService(self._service().reader).list_managed_repositories(),
            [self.repository],
        )

    def test_arbitrary_bot_control_is_rejected(self):
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control"):
            self._service(comments=[]).get_repository_control(self.repository)

    def test_untrusted_request_author_is_rejected(self):
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control"):
            self._service(request=self._request(association="CONTRIBUTOR")).get_repository_control(self.repository)

    def test_request_and_target_provenance_mismatch_is_rejected(self):
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control"):
            self._service(target_file=self._provenance(repository="kinoko34077/OtherRepo")).get_repository_control(self.repository)

    def test_missing_target_provenance_is_rejected(self):
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control"):
            self._service(target_file=None).get_repository_control(self.repository)

    def test_non_terminal_request_is_rejected(self):
        provisioning = {
            "body": "Repository-Bootstrap-State: PROVISIONING\nRequest: kinoko34077/devflow#313",
            "author_association": "NONE",
        }
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control"):
            self._service(comments=[provisioning]).get_repository_control(self.repository)

    def test_user_forged_done_comment_is_rejected(self):
        forged = self._done_comment()
        forged["user"] = {"login": "kinoko34077"}
        forged.pop("performed_via_github_app")
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control"):
            self._service(comments=[forged]).get_repository_control(self.repository)

    def test_malformed_control_provenance_is_rejected(self):
        control = {
            "number": 314,
            "title": "[REPO] UniverseGenome",
            "html_url": "https://github.com/kinoko34077/devflow/issues/314",
            "state": "open",
            "author_association": "NONE",
            "body": self._control_body().replace("repository-bootstrap.v1", "repository-bootstrap.v0"),
        }
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No open Repository Control"):
            self._service(control=control).get_repository_control(self.repository)

    def test_duplicate_derived_controls_remain_ambiguous(self):
        first = {
            "number": 314,
            "title": "[REPO] UniverseGenome",
            "html_url": "https://github.com/kinoko34077/devflow/issues/314",
            "state": "open",
            "author_association": "NONE",
            "body": self._control_body(),
        }
        second = {**first, "number": 315, "html_url": "https://github.com/kinoko34077/devflow/issues/315"}
        reader = FakeReader(
            [],
            issues_by_repository={"kinoko34077/devflow": [first, second, self._request()]},
            files={(self.repository, ".github/repository-bootstrap.json"): {"content": self._provenance()}},
            comments={
                ("kinoko34077/devflow", 313): [
                    self._done_comment(control_number=314),
                    self._done_comment(control_number=315),
                ]
            },
        )
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "found 2"):
            devflow_mcp_core.DevflowService(reader).get_repository_control(self.repository)

    def test_reader_can_fetch_comments_and_text_files(self):
        encoded = base64.b64encode(self._provenance().encode()).decode()

        def transport(url, headers):
            if "/issues/313/comments?" in url:
                return [self._done_comment()]
            if "/contents/.github/repository-bootstrap.json" in url:
                return {"type": "file", "content": encoded}
            raise AssertionError(url)

        reader = devflow_mcp_core.GitHubReader(transport=transport)
        self.assertEqual(reader.list_issue_comments("kinoko34077/devflow", 313)[0]["body"].splitlines()[0], "Repository-Bootstrap-State: DONE")
        self.assertEqual(reader.get_file(self.repository, ".github/repository-bootstrap.json")["content"], self._provenance())


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


class ObservedIssueIdentityTests(unittest.TestCase):
    """devflow#154 P1: exact Issue reads must match the observed object identity."""

    def _issue(self, **overrides):
        issue = {
            "number": 7,
            "title": "Owner task",
            "state": "open",
            "body": "## Next Action\n\ncontinue\n",
            "repository_url": "https://api.github.com/repos/kinoko34077/SynTrail-LM",
            "html_url": "https://github.com/kinoko34077/SynTrail-LM/issues/7",
        }
        issue.update(overrides)
        return issue

    def _reader(self, issue):
        return devflow_mcp_core.GitHubReader(token="", transport=lambda url, headers: issue)

    def test_matching_identity_is_returned(self):
        service = devflow_mcp_core.DevflowService(self._reader(self._issue()))
        result = service.get_issue("SynTrail-LM", 7)
        self.assertEqual(result["repository"], "kinoko34077/SynTrail-LM")
        self.assertEqual(result["issue_number"], 7)

    def test_non_github_repository_url_fails_closed(self):
        issue = self._issue(
            repository_url="https://evil.example/repos/kinoko34077/SynTrail-LM",
        )
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "does not match requested"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_noncanonical_repository_url_path_fails_closed(self):
        issue = self._issue(
            repository_url="https://api.github.com/prefix/repos/kinoko34077/SynTrail-LM",
        )
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "does not match requested"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_conflicting_html_url_identity_fails_closed(self):
        issue = self._issue(
            html_url="https://github.com/other/repo/issues/7",
        )
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "does not match requested"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_non_default_repository_url_port_fails_closed(self):
        issue = self._issue(
            repository_url="https://api.github.com:8443/repos/kinoko34077/SynTrail-LM",
        )
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "does not match requested"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_conflicting_api_issue_number_fails_closed(self):
        issue = self._issue(
            url="https://api.github.com/repos/kinoko34077/SynTrail-LM/issues/8",
        )
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "does not match requested"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_malformed_repository_object_fails_closed(self):
        issue = self._issue(repository={})
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "does not match requested"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_repository_match_is_case_insensitive(self):
        reader = self._reader(self._issue(repository_url="https://api.github.com/repos/kinoko34077/syntrail-lm"))
        self.assertEqual(reader.get_issue("kinoko34077/SynTrail-LM", 7)["number"], 7)

    def test_mismatched_repository_fails_closed(self):
        reader = self._reader(self._issue(repository_url="https://api.github.com/repos/other/elsewhere"))
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "does not match requested"):
            reader.get_issue("kinoko34077/SynTrail-LM", 7)

    def test_missing_repository_url_fails_closed(self):
        issue = self._issue()
        del issue["repository_url"]
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "<missing>"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_mismatched_number_fails_closed(self):
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "number 8"):
            self._reader(self._issue(number=8)).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_missing_number_is_not_filled_from_request(self):
        issue = self._issue()
        del issue["number"]
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "number None"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_pull_request_is_rejected(self):
        issue = self._issue(pull_request={"url": "x"})
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "pull request"):
            self._reader(issue).get_issue("kinoko34077/SynTrail-LM", 7)

    def test_service_checks_identity_even_with_custom_reader(self):
        class Reader:
            def get_issue(self, repository, issue_number):
                return {"number": 7, "repository_url": "https://api.github.com/repos/other/x", "body": ""}

        with self.assertRaises(devflow_mcp_core.DevflowMCPError):
            devflow_mcp_core.DevflowService(Reader()).get_issue("SynTrail-LM", 7)

    def test_default_transport_rejects_redirected_final_url(self):
        from unittest import mock

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return "https://api.github.com/repositories/1/issues/9?token=leak"

            def read(self):
                raise AssertionError("body must not be consumed after a redirect")

        with mock.patch("urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(devflow_mcp_core.DevflowMCPError) as ctx:
                devflow_mcp_core._default_transport(
                    "https://api.github.com/repos/kinoko34077/devflow/issues/7",
                    {"Authorization": "Bearer secret"},
                )
        message = str(ctx.exception)
        self.assertIn("redirected", message)
        self.assertNotIn("leak", message)
        self.assertNotIn("secret", message)


class RepositoryProjectionServiceTests(unittest.TestCase):
    repository = "kinoko34077/example"

    def _control(self):
        return {
            "number": 77,
            "title": "[REPO] example",
            "html_url": "https://github.com/kinoko34077/devflow/issues/77",
            "state": "open",
            "author_association": "OWNER",
            "body": (
                "## Repository\n\n`kinoko34077/example`\n\n"
                "## Work Status\n\n`AUDITED`\n\n"
                "## Repository State\n\n`ACTIVE`\n\n"
                "## Priority\n\n`P2`\n\n"
                "## Risk\n\n`LOW`\n\n"
                "## Type\n\n`INFRA`\n\n"
                "## Audit SHA\n\n`abc123`\n"
            ),
        }

    def _task(self, number=1):
        body = (
            repository_projection.ISSUE_METADATA_BEGIN
            + "\n"
            + '{"schema_version":1,"record_role":"TASK","type":"BUG",'
            + '"work_status":"READY_FOR_IMPLEMENTATION","scope_ready":true,'
            + '"requires_user_confirmation":false,"external_wait":false}'
            + "\n"
            + repository_projection.ISSUE_METADATA_END
        )
        return {
            "number": number,
            "title": "Fix projection",
            "state": "open",
            "body": body,
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-02T00:00:00Z",
            "html_url": f"https://github.com/{self.repository}/issues/{number}",
        }

    def _service(self, local_issues):
        control = self._control()
        reader = FakeReader(
            [control],
            issues_by_repository={
                "kinoko34077/devflow": [control],
                self.repository: local_issues,
            },
        )
        return devflow_mcp_core.DevflowService(reader), reader

    def test_get_repository_projection_returns_live_shadow_model(self):
        service, reader = self._service([self._task()])
        result = service.get_repository_projection(self.repository)
        self.assertEqual(result["authority"], "SHADOW_READ_ONLY")
        self.assertEqual(result["repository"], self.repository)
        self.assertEqual(result["source_status"], "OK")
        self.assertEqual(result["counts"]["machine_tasks"], 1)
        self.assertEqual(
            result["actionable_refs"],
            ["kinoko34077/example#1"],
        )
        self.assertIn((self.repository, "open"), reader.calls)

    def test_get_repository_projection_source_failure_is_explicit_and_safe(self):
        control = self._control()

        class Reader(FakeReader):
            def list_issues(inner_self, repository, state="open"):
                if repository == self.repository:
                    raise devflow_mcp_core.DevflowMCPError("GitHub unavailable")
                return super().list_issues(repository, state)

        reader = Reader(
            [control],
            issues_by_repository={"kinoko34077/devflow": [control]},
        )
        service = devflow_mcp_core.DevflowService(reader)
        result = service.get_repository_projection(self.repository)
        self.assertEqual(result["source_status"], "ERROR")
        self.assertIn("GitHub unavailable", result["source_error"])
        self.assertEqual(result["actionable_refs"], [])
        self.assertEqual(result["issues"], [])

    def test_portfolio_projection_aggregates_managed_repositories_read_only(self):
        second = "kinoko34077/second"
        control1 = self._control()
        control2 = {
            **self._control(),
            "number": 78,
            "title": "[REPO] second",
            "html_url": "https://github.com/kinoko34077/devflow/issues/78",
            "body": self._control()["body"].replace(
                "kinoko34077/example",
                second,
            ),
        }
        reader = FakeReader(
            [control1, control2],
            issues_by_repository={
                "kinoko34077/devflow": [control1, control2],
                self.repository: [self._task(1)],
                second: [],
            },
        )
        service = devflow_mcp_core.DevflowService(reader)
        result = service.get_portfolio_projection()
        self.assertEqual(result["authority"], "SHADOW_READ_ONLY")
        self.assertEqual(result["summary"]["repositories"], 2)
        self.assertEqual(result["summary"]["source_ok"], 2)
        self.assertEqual(result["summary"]["machine_tasks"], 1)
        self.assertEqual(
            [item["repository"] for item in result["repositories"]],
            [self.repository, second],
        )



class SyncHealthTrustTests(unittest.TestCase):
    """devflow#154 P2: Sync Health selection applies the trusted-author policy."""

    def _health(self, number, association, state="open", result="PASS"):
        return {
            "number": number,
            "title": devflow_mcp_core.HEALTH_TITLE,
            "state": state,
            "author_association": association,
            "body": f"## Result\n\n{result}\n",
        }

    def _service(self, issues):
        return devflow_mcp_core.DevflowService(FakeReader(issues))

    def test_outsider_only_health_is_unavailable(self):
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, r"No trusted Sync Health.*\[5\]"):
            self._service([self._health(5, "NONE")]).get_sync_health()

    def test_missing_association_is_untrusted(self):
        issue = self._health(5, "OWNER")
        del issue["author_association"]
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "No trusted Sync Health"):
            self._service([issue]).get_sync_health()

    def test_trusted_plus_outsider_selects_trusted_and_reports_ignored(self):
        result = self._service([
            self._health(41, "OWNER"),
            self._health(900, "CONTRIBUTOR", result="FAIL"),
        ]).get_sync_health()
        self.assertEqual(result["issue_number"], 41)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["ignored_untrusted_candidates"], [900])

    def test_open_trusted_preferred_over_closed_trusted_history(self):
        result = self._service([
            self._health(30, "OWNER", state="closed", result="FAIL"),
            self._health(41, "OWNER"),
        ]).get_sync_health()
        self.assertEqual(result["issue_number"], 41)

    def test_two_open_trusted_candidates_remain_ambiguous(self):
        with self.assertRaisesRegex(devflow_mcp_core.DevflowMCPError, "found 2"):
            self._service([self._health(41, "OWNER"), self._health(42, "MEMBER")]).get_sync_health()


if __name__ == "__main__":
    unittest.main()
