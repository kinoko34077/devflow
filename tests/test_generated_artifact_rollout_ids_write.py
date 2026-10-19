"""Fail-closed IDS W1.4 boundary unit tests."""
import unittest
from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout_ids_write import (
    REPOSITORY, RECIPE, OUTPUTS, NarrowIdsWriteApi,
    validate_target, validate_outputs, validate_policy,
)

class FakeTransport:
    repository = REPOSITORY
    def post(self, *_):
        raise AssertionError("must never mutate")
    def patch(self, *_):
        raise AssertionError("must never mutate")

class IdsBoundaryTests(unittest.TestCase):
    def test_fixed_scope(self):
        validate_target(REPOSITORY, RECIPE, "artifact/writeback-ids/probe", "a" * 40)
        for repo, recipe, branch, sha in [
            ("kinoko34077/testapp", RECIPE, "artifact/writeback-ids/probe", "a" * 40),
            (REPOSITORY, "other", "artifact/writeback-ids/probe", "a" * 40),
            (REPOSITORY, RECIPE, "main", "a" * 40),
            (REPOSITORY, RECIPE, "artifact/writeback-ids/probe", "bad"),
        ]:
            with self.assertRaises(ArtifactRejected):
                validate_target(repo, recipe, branch, sha)

    def test_two_outputs_only(self):
        validate_outputs({p: b"ok" for p in OUTPUTS})
        with self.assertRaises(ArtifactRejected):
            validate_outputs({next(iter(OUTPUTS)): b"ok"})
        with self.assertRaises(ArtifactRejected):
            validate_outputs({p: b"x" * (24 * 1024 * 1024 + 1) for p in OUTPUTS})
        with self.assertRaises(ArtifactRejected):
            validate_outputs({p: b"x" * (17 * 1024 * 1024) for p in OUTPUTS})

    def test_policy_rejects_widening(self):
        from tools.generated_artifact_rollout import fixed_policy
        policy = fixed_policy(REPOSITORY, RECIPE, "a" * 40)
        validate_policy(policy)
        policy["recipe"]["paths"].append("unapproved.json")
        with self.assertRaises(ArtifactRejected):
            validate_policy(policy)

    def test_write_is_dormant(self):
        api = NarrowIdsWriteApi(FakeTransport(), "artifact/writeback-ids/probe", "a" * 40)
        with self.assertRaises(ArtifactRejected):
            api.post("/git/blobs", {"content": "bad"})
        with self.assertRaises(ArtifactRejected):
            api.patch("/git/refs/heads/artifact/writeback-ids/probe", {"sha": "a"*40, "force": False})
        with self.assertRaises(ArtifactRejected):
            api.get("/user")

if __name__ == "__main__":
    unittest.main()
