"""Auth boundary tests use independent synthetic REST metadata, no network."""
import copy
import unittest

from tests.test_generated_artifact_contract import fixture
from tools.generated_artifact_admission import attest_producer
from tools.generated_artifact_contract import ArtifactRejected

REPO = "kinoko34077/japanese-orthography"
PATH = ".github/workflows/verified-artifacts-pilot.yml"
SHA = "f" * 40


def args():
    policy, _, _, _ = fixture()
    policy["repository"] = REPO
    policy["recipe"] = {
        "id": "jo-orthography-accounting",
        "version": "1",
        "paths": ["data/reports/orthography-v2-source-accounting.json"],
    }
    policy["producer_workflow_ref"] = f"{REPO}/{PATH}@{SHA}"
    policy["branch_prefix"] = "artifact/devflow384-"
    runner = {
        "repository": REPO,
        "actor": "kinoko34077", "triggering_actor": "kinoko34077",
        "event": "workflow_dispatch",
        "ref": "refs/heads/main",
        "workflow_ref": f"{REPO}/{PATH}@refs/heads/main",
        "workflow_sha": SHA,
        "run_id": "37752814325",
        "run_attempt": "1",
    }
    run = {
        "id": 37752814325,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "status": "in_progress",
        "head_sha": SHA,
        "head_branch": "main",
        "path": PATH,
        "actor": {"login": "kinoko34077"},
        "repository": {"full_name": REPO},
        "workflow_id": 998,
    }
    workflow = {"id": 998, "path": PATH}
    return policy, runner, run, workflow


class GeneratedArtifactAdmissionTests(unittest.TestCase):
    def attempt(self, policy=None, runner=None, run=None, workflow=None, *, branch="artifact/devflow384-pilot-1"):
        p, ctx, r, w = args()
        return attest_producer(policy or p, runner or ctx, run or r,
                               workflow or w, target_branch=branch,
                               expected_head="b" * 40)

    def test_exact_runner_and_rest_metadata_admit_fixed_source_head(self):
        result = self.attempt()
        self.assertEqual(result["source_sha"], "b" * 40)
        self.assertEqual(result["producer_run_id"], 37752814325)
        self.assertEqual(result["producer_workflow_ref"], f"{REPO}/{PATH}@{SHA}")

    def test_no_false_actor_or_cross_repo(self):
        for kind, v in [("actor", "stranger"), ("repository", "stranger/another"),
                        ("triggering_actor", "stranger")]:
            with self.subTest(kind=kind):
                p, ctx, r, w = args()
                ctx[kind] = v
                with self.assertRaises(ArtifactRejected):
                    self.attempt(p, ctx, r, w)

    def test_fork_and_untrusted_trigger_are_not_admitted(self):
        for kind, value in [("event", "pull_request_target"),
                            ("event", "pull_request"), ("ref", "refs/heads/artifact/hijack"),
                            ("workflow_ref", f"{REPO}/{PATH}@refs/heads/evil")]:
            with self.subTest(kind=kind):
                p, ctx, r, w = args()
                ctx[kind] = value
                with self.assertRaises(ArtifactRejected):
                    self.attempt(p, ctx, r, w)

    def test_invalid_run_attempt_actor_head_status_or_workflow_denied(self):
        for key, value in [
            ("id", 15), ("run_attempt", 2), ("event", "pull_request"),
            ("head_sha", "a" * 40), ("status", "completed"),
            ("head_branch", "evil"), ("path", ".github/workflows/untrusted.yml"),
            ("actor", {"login": "attacker"}), ("repository", {"full_name": "evil/repo"}),
            ("workflow_id", 10),
        ]:
            with self.subTest(key=key):
                p, ctx, run, wf = args()
                run[key] = value
                with self.assertRaises(ArtifactRejected):
                    self.attempt(p, ctx, run, wf)

    def test_workflow_identity_mismatch_denied(self):
        p, ctx, run, wf = args()
        wf["path"] = ".github/workflows/untrusted.yml"
        with self.assertRaises(ArtifactRejected):
            self.attempt(p, ctx, run, wf)

    def test_unreviewed_workflow_sha_denied(self):
        p, ctx, run, wf = args()
        ctx["workflow_sha"] = "a" * 40
        run["head_sha"] = "a" * 40
        with self.assertRaises(ArtifactRejected):
            self.attempt(p, ctx, run, wf)

    def test_wrong_recipe_scope_or_branch_denied(self):
        for branch in ("main", "artifact/other", "feature/random"):
            with self.subTest(branch=branch):
                with self.assertRaises(ArtifactRejected):
                    self.attempt(branch=branch)
        p, ctx, run, wf = args()
        p["recipe"]["paths"] = ["src/change.py"]
        with self.assertRaises(ArtifactRejected):
            self.attempt(p, ctx, run, wf)

    def test_missing_or_malformed_context_denied(self):
        for key, value in [("run_id", "abc"), ("run_attempt", "0"), ("workflow_sha", ""),
                           ("actor", None)]:
            with self.subTest(key=key):
                p, ctx, run, wf = args()
                ctx[key] = value
                with self.assertRaises(ArtifactRejected):
                    self.attempt(p, ctx, run, wf)

    def test_unverified_workflow_metadata_denied(self):
        p, ctx, run, wf = args()
        with self.assertRaises(ArtifactRejected):
            self.attempt(p, ctx, run, None if False else {"id": 998, "path": "different"})


if __name__ == "__main__":
    unittest.main()
