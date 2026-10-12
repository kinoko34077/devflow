"""Pure/offline authenticated-boundary tests for devflow#465 R1.

Only GET fakes. No GitHub token, workflow dispatch or writeback execution.
"""
import base64
import copy
import unittest

from tools import generated_artifact_rollout_admission as auth
from tools.generated_artifact_contract import ArtifactRejected
from tests.test_generated_artifact_rollout import (
    REPO, RECIPE, SHA, CALLER_SHA, BRANCH, runner,
)

TEMPLATE = auth.TEMPLATE.read_text("utf-8")


def env(**changes):
    value = runner()
    value["MODE"] = "dry-run"
    value.update(changes)
    return value


class FakeGitHubReader:
    repository = REPO

    def __init__(self, *, run=None, workflow=None, caller=None):
        self.calls = []
        self.run = {
            "id": 501, "run_attempt": 1, "event": "workflow_dispatch",
            "status": "in_progress", "head_sha": CALLER_SHA,
            "head_branch": "main", "path": auth.CALLER_PATH,
            "actor": {"login": "kinoko34077"},
            "triggering_actor": {"login": "kinoko34077"},
            "repository": {"full_name": REPO}, "workflow_id": 89,
        }
        self.run.update(run or {})
        self.workflow = {"id": 89, "path": auth.CALLER_PATH}
        self.workflow.update(workflow or {})
        canonical = auth.exact_caller_text(TEMPLATE, SHA)
        self.caller = canonical if caller is None else caller

    def get(self, path):
        self.calls.append(path)
        if path == "/actions/runs/501":
            return self.run
        if path.startswith("/actions/workflows/"):
            return self.workflow
        if path == f"/contents/{auth.CALLER_PATH}?ref={CALLER_SHA}":
            return {
                "type": "file", "path": auth.CALLER_PATH,
                "encoding": "base64",
                "content": base64.b64encode(self.caller.encode("utf-8")).decode("ascii"),
            }
        raise AssertionError("unexpected API read: " + path)


class TrustedCallerAndApiAdmissionTests(unittest.TestCase):
    def check(self, api=None, environment=None, **overrides):
        params = {
            "repository": REPO, "recipe_id": RECIPE,
            "target_branch": BRANCH, "expected_head": SHA, "source_head": SHA,
            "devflow_sha": SHA, "devflow_checkout_sha": SHA,
            "trusted_template": TEMPLATE,
        }
        params.update(overrides)
        return auth.attest_authenticated_readonly(
            api or FakeGitHubReader(), environment or env(), **params,
        )

    def test_positive_three_independent_rest_reads_and_no_write(self):
        api = FakeGitHubReader()
        result = self.check(api=api)
        self.assertEqual(result["status"], "AUTHENTICATED_READ_ONLY")
        self.assertFalse(result["writer_authorized"])
        self.assertEqual(result["policy"]["repository"], REPO)
        self.assertEqual(result["admission"]["producer_run_id"], 501)
        self.assertEqual(api.calls, [
            "/actions/runs/501",
            "/actions/workflows/89",
            f"/contents/{auth.CALLER_PATH}?ref={CALLER_SHA}",
        ])

    def test_caller_exact_bytes_not_substring_heuristics(self):
        original = auth.exact_caller_text(TEMPLATE, SHA)
        changes = [
            original.replace(f"@{SHA}", "@main"),
            original.replace(f"devflow_sha: {SHA}", "devflow_sha: " + "c" * 40),
            original + "\n",
            original + "  malicious:\n    run: echo hi\n",
            original.replace("workflow_dispatch:", "push:"),
            original.replace("type: choice", "type: string"),
            original.replace("contents: write", "contents: read"),
            original.replace("uses: kinoko34077/devflow", "uses: stranger/devflow"),
        ]
        for idx, altered in enumerate(changes):
            with self.subTest(idx=idx), self.assertRaises(ArtifactRejected):
                self.check(api=FakeGitHubReader(caller=altered))

    def test_template_requires_exact_two_pins(self):
        for bad in (TEMPLATE.replace("<DEVFLOW_SHA>", "main"),
                    TEMPLATE + "<DEVFLOW_SHA>",
                    "", None):
            with self.subTest(bad=repr(bad)[:20]), self.assertRaises(ArtifactRejected):
                auth.exact_caller_text(bad, SHA)

    def test_rest_actor_run_workflow_repository_and_status_mismatch(self):
        bad = [
            {"id": 502}, {"run_attempt": 2}, {"event": "pull_request"},
            {"status": "completed"}, {"head_sha": SHA},
            {"head_branch": "feature"}, {"path": "other.yml"},
            {"actor": {"login": "attacker"}}, {"triggering_actor": {"login": "attacker"}},
            {"repository": {"full_name": "stranger/repo"}},
            {"workflow_id": 90},
        ]
        for overrides in bad:
            with self.subTest(overrides=overrides), self.assertRaises(ArtifactRejected):
                self.check(api=FakeGitHubReader(run=overrides))
        for changed_workflow in ({"id": 90}, {"path": "other.yml"}):
            with self.subTest(workflow=changed_workflow), self.assertRaises(ArtifactRejected):
                self.check(api=FakeGitHubReader(workflow=changed_workflow))

    def test_rest_rerun_actor_missing_or_forged_is_rejected(self):
        with self.assertRaises(ArtifactRejected):
            self.check(api=FakeGitHubReader(run={"triggering_actor": None}))
        with self.assertRaises(ArtifactRejected):
            self.check(api=FakeGitHubReader(run={"triggering_actor": {"login": "attacker"}}))

    def test_runner_head_branch_context_and_mode_rejections(self):
        for change in (
            {"MODE": "write-replay-test"}, {"MODE": "delete"},
            {"GITHUB_REPOSITORY": "attacker/repo"},
            {"GITHUB_ACTOR": "attacker"}, {"GITHUB_TRIGGERING_ACTOR": "attacker"},
            {"GITHUB_WORKFLOW_SHA": "c" * 40},
        ):
            with self.subTest(change=change), self.assertRaises(ArtifactRejected):
                self.check(environment=env(**change))
        with self.assertRaises(ArtifactRejected):
            self.check(api=FakeGitHubReader(), target_branch="main")

    def test_repo_reader_identity_must_match_and_no_self_asserted_runner_admission(self):
        other = FakeGitHubReader()
        other.repository = "kinoko34077/kinotch-api"
        with self.assertRaises(ArtifactRejected):
            self.check(api=other)
        with self.assertRaises(ArtifactRejected):
            self.check(api=FakeGitHubReader(), devflow_checkout_sha="d" * 40)


if __name__ == "__main__":
    unittest.main()
