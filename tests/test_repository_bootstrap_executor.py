import json
import unittest

from tools import repository_bootstrap as rb
from tests.test_repository_bootstrap import issue_body


class FakeApi:
    def __init__(self):
        self.repos = {}
        self.files = {}
        self.issues = {}
        self.comments = []
        self.sha_counter = 0
        self.fail_on = None

    def _maybe_fail(self, operation):
        if self.fail_on == operation:
            raise RuntimeError(f"forced {operation} failure")

    def get_repository(self, full_name):
        self._maybe_fail("get_repository")
        return self.repos.get(full_name)

    def create_repository(self, owner, name, description, visibility):
        self._maybe_fail("create_repository")
        full_name = f"{owner}/{name}"
        repo = {
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "default_branch": "main",
            "visibility": visibility,
        }
        self.repos[full_name] = repo
        return repo

    def get_file(self, full_name, path):
        self._maybe_fail(f"get_file:{path}")
        value = self.files.get((full_name, path))
        if value is None:
            return None
        return {"content": value, "sha": f"blob-{abs(hash((full_name, path, value)))}"}

    def create_file(self, full_name, path, content, message):
        self._maybe_fail(f"create_file:{path}")
        if (full_name, path) in self.files:
            raise AssertionError(f"unexpected overwrite of {path}")
        self.files[(full_name, path)] = content
        self.sha_counter += 1
        return {"commit_sha": f"{self.sha_counter:040x}"}

    def get_default_branch_name(self, full_name):
        self._maybe_fail("get_default_branch_name")
        return self.repos[full_name]["default_branch"]

    def get_default_branch_head(self, full_name):
        self._maybe_fail("get_default_branch_head")
        return f"{max(self.sha_counter, 1):040x}"

    def list_issues(self, full_name, state="all"):
        self._maybe_fail(f"list_issues:{full_name}")
        values = list(self.issues.get(full_name, []))
        if state == "open":
            values = [item for item in values if item.get("state", "open") == "open"]
        return values

    def create_issue(self, full_name, title, body):
        self._maybe_fail(f"create_issue:{full_name}")
        number = len(self.issues.setdefault(full_name, [])) + 1
        issue = {
            "number": number,
            "title": title,
            "body": body,
            "state": "open",
            "html_url": f"https://github.com/{full_name}/issues/{number}",
        }
        self.issues[full_name].append(issue)
        return issue

    def comment_issue(self, full_name, issue_number, body):
        self._maybe_fail("comment_issue")
        self.comments.append((full_name, issue_number, body))
        return {"html_url": f"https://github.com/{full_name}/issues/{issue_number}#comment"}


def normalized_request():
    return rb.normalize_request(
        rb.parse_request_body(issue_body()),
        "[REPO CREATE] example-repo",
    )


def context():
    return rb.BootstrapContext(
        request_ref="kinoko34077/devflow#181",
        request_url="https://github.com/kinoko34077/devflow/issues/181",
        devflow_repo="kinoko34077/devflow",
        request_issue_number=181,
        request_title="[REPO CREATE] example-repo",
        author_association="OWNER",
    )


def matching_provenance():
    return json.dumps(
        {
            "schema": "repository-bootstrap-provenance.v1",
            "request_ref": "kinoko34077/devflow#181",
            "request_url": "https://github.com/kinoko34077/devflow/issues/181",
            "repository": "kinoko34077/example-repo",
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


class RepositoryBootstrapExecutorTests(unittest.TestCase):
    def test_new_request_creates_repo_seed_issue_and_control(self):
        repo_api = FakeApi()
        devflow_api = FakeApi()
        executor = rb.BootstrapExecutor(repo_api, devflow_api)

        result = executor.execute(normalized_request(), context())

        self.assertIn("kinoko34077/example-repo", repo_api.repos)
        self.assertEqual(
            repo_api.files[("kinoko34077/example-repo", ".github/repository-bootstrap.json")],
            matching_provenance(),
        )
        self.assertEqual(
            repo_api.files[("kinoko34077/example-repo", "README.md")],
            "# example-repo\n",
        )
        owner_issues = repo_api.issues["kinoko34077/example-repo"]
        self.assertEqual(len(owner_issues), 1)
        self.assertIn(
            "<!-- repository-bootstrap:kinoko34077/devflow#181:issue:scope -->",
            owner_issues[0]["body"],
        )
        controls = devflow_api.issues["kinoko34077/devflow"]
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]["title"], "[REPO] example-repo")
        self.assertIn("## Audit SHA", controls[0]["body"])
        self.assertIn(result.head_sha, controls[0]["body"])
        self.assertIn("## Audit Ref", controls[0]["body"])
        self.assertIn("`main`", controls[0]["body"])
        self.assertIn(rb.CONTROL_START_MARKER, controls[0]["body"])
        self.assertEqual(
            rb.parse_control_provenance(controls[0]["body"]),
            {
                "schema": rb.CONTROL_PROVENANCE_SCHEMA,
                "request_ref": "kinoko34077/devflow#181",
                "request_url": "https://github.com/kinoko34077/devflow/issues/181",
                "repository": "kinoko34077/example-repo",
            },
        )
        self.assertEqual(result.repository_url, "https://github.com/kinoko34077/example-repo")
        self.assertEqual(len(result.issue_urls), 1)
        self.assertIsNotNone(result.control_url)
        self.assertTrue(any("Repository-Bootstrap-State: DONE" in c[2] for c in devflow_api.comments))

    def test_matching_provenance_retry_reuses_existing_resources(self):
        repo_api = FakeApi()
        devflow_api = FakeApi()
        full_name = "kinoko34077/example-repo"
        repo_api.repos[full_name] = {
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "default_branch": "main",
            "visibility": "private",
        }
        repo_api.files[(full_name, ".github/repository-bootstrap.json")] = matching_provenance()
        repo_api.files[(full_name, "README.md")] = "# user-edited content\n"
        marker = "<!-- repository-bootstrap:kinoko34077/devflow#181:issue:scope -->"
        repo_api.issues[full_name] = [
            {
                "number": 1,
                "title": "Initial scope",
                "body": f"{marker}\n\nDefine the initial scope.",
                "state": "closed",
                "html_url": f"https://github.com/{full_name}/issues/1",
            }
        ]
        devflow_api.issues["kinoko34077/devflow"] = [
            {
                "number": 999,
                "title": "[REPO] example-repo",
                "body": "## Repository\n\n`kinoko34077/example-repo`\n",
                "state": "open",
                "html_url": "https://github.com/kinoko34077/devflow/issues/999",
            }
        ]

        result = rb.BootstrapExecutor(repo_api, devflow_api).execute(
            normalized_request(), context()
        )

        self.assertEqual(repo_api.files[(full_name, "README.md")], "# user-edited content\n")
        self.assertEqual(len(repo_api.issues[full_name]), 1)
        self.assertEqual(len(devflow_api.issues["kinoko34077/devflow"]), 1)
        self.assertEqual(result.control_url, "https://github.com/kinoko34077/devflow/issues/999")

    def test_existing_repository_without_matching_provenance_fails_closed(self):
        repo_api = FakeApi()
        devflow_api = FakeApi()
        full_name = "kinoko34077/example-repo"
        repo_api.repos[full_name] = {
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "default_branch": "main",
            "visibility": "private",
        }

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repo_api, devflow_api).execute(
                normalized_request(), context()
            )

        self.assertEqual(caught.exception.stage, "REPOSITORY")
        self.assertEqual(caught.exception.safe_retry, "after-human-decision")
        self.assertNotIn((full_name, "README.md"), repo_api.files)
        self.assertTrue(any("Repository-Bootstrap-State: FAILED" in c[2] for c in devflow_api.comments))

    def test_duplicate_marked_owner_issues_fail_closed(self):
        repo_api = FakeApi()
        devflow_api = FakeApi()
        full_name = "kinoko34077/example-repo"
        repo_api.repos[full_name] = {
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "default_branch": "main",
            "visibility": "private",
        }
        repo_api.files[(full_name, ".github/repository-bootstrap.json")] = matching_provenance()
        marker = "<!-- repository-bootstrap:kinoko34077/devflow#181:issue:scope -->"
        repo_api.issues[full_name] = [
            {"number": 1, "title": "A", "body": marker, "state": "open", "html_url": "x"},
            {"number": 2, "title": "B", "body": marker, "state": "open", "html_url": "y"},
        ]

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repo_api, devflow_api).execute(normalized_request(), context())

        self.assertEqual(caught.exception.stage, "ISSUES")
        self.assertEqual(caught.exception.safe_retry, "after-human-decision")

    def test_duplicate_controls_fail_closed(self):
        repo_api = FakeApi()
        devflow_api = FakeApi()
        full_name = "kinoko34077/example-repo"
        repo_api.repos[full_name] = {
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "default_branch": "main",
            "visibility": "private",
        }
        repo_api.files[(full_name, ".github/repository-bootstrap.json")] = matching_provenance()
        for number in (1, 2):
            devflow_api.issues.setdefault("kinoko34077/devflow", []).append(
                {
                    "number": number,
                    "title": "[REPO] example-repo",
                    "body": "## Repository\n\n`kinoko34077/example-repo`\n",
                    "state": "open",
                    "html_url": f"https://github.com/kinoko34077/devflow/issues/{number}",
                }
            )

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repo_api, devflow_api).execute(normalized_request(), context())

        self.assertEqual(caught.exception.stage, "CONTROL")
        self.assertEqual(caught.exception.safe_retry, "after-human-decision")

    def test_partial_api_failure_reports_stage_resources_and_retry(self):
        repo_api = FakeApi()
        devflow_api = FakeApi()
        repo_api.fail_on = "create_issue:kinoko34077/example-repo"

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repo_api, devflow_api).execute(normalized_request(), context())

        failure = caught.exception
        self.assertEqual(failure.stage, "ISSUES")
        self.assertEqual(failure.safe_retry, "yes")
        self.assertIn("repository:https://github.com/kinoko34077/example-repo", failure.resources)
        self.assertTrue(any("Stage: ISSUES" in c[2] and "Safe-Retry: yes" in c[2] for c in devflow_api.comments))

    def test_untrusted_context_is_rejected_before_repository_mutation(self):
        repo_api = FakeApi()
        devflow_api = FakeApi()
        bad_context = rb.BootstrapContext(
            request_ref="kinoko34077/devflow#181",
            request_url="https://github.com/kinoko34077/devflow/issues/181",
            devflow_repo="kinoko34077/devflow",
            request_issue_number=181,
            request_title="[REPO CREATE] example-repo",
            author_association="CONTRIBUTOR",
        )

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repo_api, devflow_api).execute(normalized_request(), bad_context)

        self.assertEqual(caught.exception.stage, "VALIDATION")
        self.assertFalse(repo_api.repos)


if __name__ == "__main__":
    unittest.main()
