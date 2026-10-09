"""Autoseeded repository-native Actions receiver has no per-repo admin setup."""
import unittest
from pathlib import Path

from tests.test_repository_bootstrap import issue_body
from tests.test_repository_bootstrap_executor import FakeApi, context
from tools import repository_bootstrap as rb


ROOT = Path(__file__).resolve().parents[1]
PATH = ".github/workflows/kinotch-repo-command.yml"


def request(*, enabled: bool, managed: bool = True):
    payload = rb.parse_request_body(issue_body())
    payload["bootstrap"]["devflow_managed"] = managed
    payload["bootstrap"]["repo_native_dispatch"] = enabled
    return rb.normalize_request(payload, "[REPO CREATE] example-repo")


class RepoNativeBootstrapTests(unittest.TestCase):
    def test_new_managed_repo_has_read_only_receiver_without_manual_settings(self):
        repository = FakeApi()
        result = rb.BootstrapExecutor(repository, FakeApi()).execute(request(enabled=True), context())
        seeded = repository.files[("kinoko34077/example-repo", PATH)]
        self.assertEqual(seeded, (ROOT / "templates/bootstrap/kinotch-repo-command.yml").read_text())
        self.assertIn("issue_comment:", seeded)
        self.assertIn("github.event.comment.body == '/kinotch status'", seeded)
        self.assertIn("github.event.issue.user.login == 'kinoko34077'", seeded)
        self.assertIn("github.event.issue.pull_request == null", seeded)
        self.assertIn("permissions: {}", seeded)
        self.assertNotIn("actions: read", seeded)
        self.assertNotIn("actions: write", seeded)
        self.assertNotIn("${{ github.event.comment.body }}", seeded)
        self.assertIn(f"file:{PATH}", result.resources)

    def test_legacy_request_retains_minimal_seed(self):
        repository = FakeApi()
        rb.BootstrapExecutor(repository, FakeApi()).execute(
            rb.normalize_request(rb.parse_request_body(issue_body()), "[REPO CREATE] example-repo"),
            context(),
        )
        self.assertNotIn(("kinoko34077/example-repo", PATH), repository.files)

    def test_opt_in_retries_are_idempotent(self):
        repository, devflow = FakeApi(), FakeApi()
        rb.BootstrapExecutor(repository, devflow).execute(request(enabled=True), context())
        prior = dict(repository.files)
        rb.BootstrapExecutor(repository, devflow).execute(request(enabled=True), context())
        self.assertEqual(repository.files, prior)

    def test_existing_receiver_is_never_overwritten(self):
        repository, devflow = FakeApi(), FakeApi()
        rb.BootstrapExecutor(repository, devflow).execute(request(enabled=True), context())
        repository.files[("kinoko34077/example-repo", PATH)] = "user edits\n"
        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(request(enabled=True), context())
        self.assertEqual(caught.exception.stage, "SEED")
        self.assertEqual(repository.files[("kinoko34077/example-repo", PATH)], "user edits\n")

    def test_workflow_scope_denial_halts_before_issues_and_control(self):
        repository, devflow = FakeApi(), FakeApi()
        repository.fail_on = f"create_file:{PATH}"
        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(
                request(enabled=True), context()
            )
        self.assertEqual(caught.exception.stage, "SEED")
        self.assertEqual(caught.exception.safe_retry, "after-human-decision")
        self.assertEqual(repository.files.get(("kinoko34077/example-repo", "README.md")), "# example-repo\\n")
        self.assertNotIn(("kinoko34077/example-repo", PATH), repository.files)
        self.assertEqual(repository.issues, {})
        self.assertEqual(devflow.issues, {})
        self.assertFalse(any("Repository-Bootstrap-State: DONE" in body
                             for _, _, body in devflow.comments))

    def test_receiver_cannot_be_installed_on_unmanaged_repo(self):
        with self.assertRaises(rb.BootstrapError):
            request(enabled=True, managed=False)

    def test_untrusted_or_malformed_flags_are_rejected(self):
        for value in ("true", 1, None, {}, []):
            payload = rb.parse_request_body(issue_body())
            payload["bootstrap"]["repo_native_dispatch"] = value
            with self.assertRaises(rb.BootstrapError):
                rb.normalize_request(payload, "[REPO CREATE] example-repo")


if __name__ == "__main__":
    unittest.main()
