"""testapp#32 and devflow#474: bounded writer job contract, offline."""
import pathlib
import unittest

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout_testapp_write import NarrowTestappWriteApi, execute_testapp_scoped_write


class DummyTransport:
    repository = "kinoko34077/testapp"
    def __init__(self):
        self.calls = []
    def get(self, path):
        self.calls.append(("GET", path))
        return {}
    def post(self, path, payload):
        self.calls.append(("POST", path))
        return {"sha": "1" * 40}
    def patch(self, path, payload):
        self.calls.append(("PATCH", path))
        return {"ref": "heads/test"}


class NarrowMutationTests(unittest.TestCase):
    branch = "artifact/writeback-testapp/e2e-20261012"

    def test_only_exact_branch_fast_forward_and_git_object_creation(self):
        api = DummyTransport()
        scoped = NarrowTestappWriteApi(api, self.branch)
        for path in ("/git/blobs", "/git/trees", "/git/commits"):
            scoped.post(path, {"test": True})
        scoped.patch("/git/refs/heads/" + self.branch, {"sha": "2" * 40, "force": False})
        self.assertEqual(len(api.calls), 4)
        self.assertEqual(api.calls[-1], ("PATCH", "/git/refs/heads/" + self.branch))

    def test_forbidden_mutations_fail_before_transport(self):
        api = DummyTransport()
        scoped = NarrowTestappWriteApi(api, self.branch)
        for path in ("/repos/other", "/actions/workflows/1/dispatches", "/git/refs", "/git/refs/heads/main"):
            with self.subTest(path=path), self.assertRaises(ArtifactRejected):
                scoped.post(path, {})
        for path, payload in (
            ("/git/refs/heads/main", {"sha": "2" * 40, "force": False}),
            ("/git/refs/heads/" + self.branch, {"sha": "2" * 40, "force": True}),
            ("/git/refs/heads/" + self.branch, {"sha": "2" * 40}),
        ):
            with self.subTest(path=path, payload=payload), self.assertRaises(ArtifactRejected):
                scoped.patch(path, payload)
        self.assertEqual(api.calls, [])

    def test_wrong_target_is_never_admitted(self):
        api = DummyTransport()
        for branch in (
            "main", "artifact/writeback-ids/a", "artifact/writeback-testapp/",
            "artifact/writeback-testapp/../main",
            "artifact/writeback-testapp/foo/bar",
            "artifact/writeback-testapp/-injected",
        ):
            with self.subTest(branch=branch), self.assertRaises(ArtifactRejected):
                NarrowTestappWriteApi(api, branch)
        api.repository = "kinoko34077/IDS-Composit"
        with self.assertRaises(ArtifactRejected):
            NarrowTestappWriteApi(api, self.branch)

    def test_wrong_job_mode_or_repo_fails_before_any_git_operation(self):
        api = DummyTransport()
        base = {"GITHUB_REPOSITORY": "kinoko34077/testapp", "MODE": "dry-run"}
        with self.assertRaises(ArtifactRejected):
            execute_testapp_scoped_write(
                api, base, pathlib.Path("none"),
                target_branch=self.branch, expected_head="a" * 40,
                devflow_sha="b" * 40, devflow_checkout_sha="b" * 40,
            )
        self.assertEqual(api.calls, [])


class SeparatedWorkflowTests(unittest.TestCase):
    def test_privileged_job_only_after_read_only_verify_and_testapp_scope(self):
        p = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/generated-artifact-rollout.yml"
        workflow = p.read_text("utf-8")
        before, privileged = workflow.split("\n  write:\n", 1)
        producer, verify = before.split("\n  verify:\n", 1)
        self.assertIn("contents: read", producer)
        self.assertNotIn("contents: write", producer)
        self.assertIn("contents: read", verify)
        self.assertNotIn("contents: write", verify)
        self.assertIn("MODE: dry-run", verify)
        self.assertIn("needs: verify", privileged)
        self.assertIn("github.repository == 'kinoko34077/testapp'", privileged)
        self.assertIn("contents: write", privileged)
        for banned in ("actions/checkout@", "npm ci", "npm run ", "secrets: inherit"):
            self.assertNotIn(banned, privileged)


if __name__ == "__main__":
    unittest.main()
