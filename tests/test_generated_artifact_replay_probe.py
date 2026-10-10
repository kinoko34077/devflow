"""Offline adversarial contract tests for #415 S3.6 replay acceptance."""
import unittest

from tools.generated_artifact_replay_probe import (
    ReplayProbeRejected, ReadOnlyReplayApi, probe_exact_replay,
)

OLD = "b" * 40
NEW = "c" * 40
OTHER = "d" * 40
BRANCH = "artifact/devflow384/replay-415"


class FakeApi:
    repository = "kinoko34077/japanese-orthography"

    def __init__(self):
        self.head = OLD
        self.parent = OLD
        self.mutations = []
        self.requests = []
        self.fail_read = False

    def get(self, path):
        self.requests.append(("GET", path))
        if self.fail_read:
            raise OSError("mock API failed")
        if path.startswith("/branches/"):
            return {"commit": {"sha": self.head}}
        if path == "/git/commits/" + NEW:
            return {"parents": [{"sha": self.parent}]}
        raise AssertionError(path)

    def post(self, path, data):
        self.mutations.append(("POST", path))

    def patch(self, path, data):
        self.mutations.append(("PATCH", path))


class ReplayProbeTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.policy = {"recipe": "fixed"}
        self.admission = {"branch": BRANCH, "expected_head": OLD,
                          "producer_run_id": 1234, "producer_run_attempt": 1}
        self.manifest = {"files": []}
        self.archive = b"fixed artifact bytes"
        self.calls = []

    def core(self, api, policy, admission, manifest, archive, *, dry_run):
        self.assertIs(policy, self.policy)
        self.assertIs(admission, self.admission)
        self.assertIs(manifest, self.manifest)
        self.assertIs(archive, self.archive)
        self.assertFalse(dry_run)
        self.calls.append(api)
        if len(self.calls) == 1:
            api.patch("/git/refs/heads/target", {"force": False})
            self.api.head = NEW
            return {"status": "COMMITTED", "writes_performed": True,
                    "previous_head": OLD, "new_head": NEW}
        return {"status": "NO_OP_REPLAY", "writes_performed": False,
                "target_head": NEW, "ci_verified": False}

    def invoke(self, core=None):
        return probe_exact_replay(self.api, self.policy, self.admission,
                                  self.manifest, self.archive,
                                  verified_writeback=core or self.core)

    def assert_failed_after_commit(self, action):
        with self.assertRaises(ReplayProbeRejected) as captured:
            action()
        self.assertTrue(captured.exception.first_committed)
        return captured.exception

    def test_positive_commit_and_read_only_replay(self):
        result = self.invoke()
        self.assertEqual(result["status"], "REPLAY_VERIFIED")
        self.assertEqual(result["first_status"], "COMMITTED")
        self.assertEqual(result["second_status"], "NO_OP_REPLAY")
        self.assertFalse(result["second_writes_performed"])
        self.assertFalse(result["ci_verified"])
        self.assertEqual(self.api.mutations, [("PATCH", "/git/refs/heads/target")])
        self.assertEqual(len(self.calls), 2)
        self.assertIsInstance(self.calls[1], ReadOnlyReplayApi)

    def test_first_noop_skips_second(self):
        def noop(api, *args, **kwargs):
            self.calls.append(api)
            return {"status": "NO_OP", "writes_performed": False}
        with self.assertRaises(ReplayProbeRejected) as captured:
            self.invoke(noop)
        self.assertFalse(captured.exception.first_committed)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.api.mutations, [])

    def test_first_claims_commit_without_write_flag(self):
        def broken(api, *args, **kwargs):
            return {"status": "COMMITTED", "writes_performed": False}
        with self.assertRaises(ReplayProbeRejected):
            self.invoke(broken)
        self.assertEqual(self.api.mutations, [])

    def test_malformed_commit_response_still_reports_recovery(self):
        def malformed(api, *args, **kwargs):
            self.api.head = NEW
            api.patch("/git/refs/heads/target", {})
            return {"status": "COMMITTED", "writes_performed": True,
                    "previous_head": OLD, "new_head": "invalid"}
        err = self.assert_failed_after_commit(lambda: self.invoke(malformed))
        self.assertEqual(err.previous_head, OLD)
        self.assertEqual(err.new_head, "invalid")
        self.assertEqual(len(self.api.mutations), 1)

    def test_wrong_expected_parent_rejected_after_commit(self):
        self.admission["expected_head"] = OTHER
        self.assert_failed_after_commit(self.invoke)
        self.assertEqual(len(self.calls), 1)

    def test_second_post_blocked_before_transport(self):
        def mutate(api, *args, **kwargs):
            if len(self.calls) == 0:
                return self.core(api, *args, **kwargs)
            api.post("/git/blobs", {"content": "unexpected"})
        self.assert_failed_after_commit(lambda: self.invoke(mutate))
        self.assertEqual(len(self.api.mutations), 1)

    def test_second_patch_blocked_before_transport(self):
        def mutate(api, *args, **kwargs):
            if len(self.calls) == 0:
                return self.core(api, *args, **kwargs)
            api.patch("/git/refs/heads/target", {"force": True})
        self.assert_failed_after_commit(lambda: self.invoke(mutate))
        self.assertEqual(len(self.api.mutations), 1)

    def test_third_party_moves_head_before_replay(self):
        def moved(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            if len(self.calls) == 1:
                self.api.head = OTHER
            return value
        self.assert_failed_after_commit(lambda: self.invoke(moved))
        self.assertEqual(len(self.calls), 1)

    def test_third_party_moves_head_after_replay(self):
        def moved(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            if len(self.calls) == 2:
                self.api.head = OTHER
            return value
        self.assert_failed_after_commit(lambda: self.invoke(moved))
        self.assertEqual(len(self.api.mutations), 1)

    def test_spoofed_parent_rejected(self):
        self.api.parent = OTHER
        self.assert_failed_after_commit(self.invoke)
        self.assertEqual(len(self.calls), 1)

    def test_wrong_replay_status_rejected(self):
        def wrong(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            if len(self.calls) == 2:
                value["status"] = "NO_OP"
            return value
        self.assert_failed_after_commit(lambda: self.invoke(wrong))

    def test_wrong_replay_target_sha_rejected(self):
        def wrong(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            if len(self.calls) == 2:
                value["target_head"] = OTHER
            return value
        self.assert_failed_after_commit(lambda: self.invoke(wrong))

    def test_second_write_flag_rejected(self):
        def wrong(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            if len(self.calls) == 2:
                value["writes_performed"] = True
            return value
        self.assert_failed_after_commit(lambda: self.invoke(wrong))

    def test_second_ci_claim_rejected(self):
        def wrong(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            if len(self.calls) == 2:
                value["ci_verified"] = True
            return value
        self.assert_failed_after_commit(lambda: self.invoke(wrong))

    def test_manifest_mutation_during_second_rejected(self):
        def mutate(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            if len(self.calls) == 2:
                self.manifest["forged"] = True
            return value
        self.assert_failed_after_commit(lambda: self.invoke(mutate))

    def test_policy_mutation_during_first_rejected(self):
        def mutate(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            self.policy["forged"] = True
            return value
        self.assert_failed_after_commit(lambda: self.invoke(mutate))
        self.assertEqual(len(self.calls), 1)

    def test_second_api_failure_after_commit_rejected(self):
        def fail(api, *args, **kwargs):
            value = self.core(api, *args, **kwargs)
            if len(self.calls) == 1:
                self.api.fail_read = True
            return value
        self.assert_failed_after_commit(lambda: self.invoke(fail))
        self.assertEqual(len(self.api.mutations), 1)


if __name__ == "__main__":
    unittest.main()
