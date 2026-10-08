"""S3 offline Git Data API adversarial tests: no network, no real token."""
import base64
import copy
import hashlib
import unittest

from tools.generated_artifact_writer import WritebackRejected, verified_writeback
from tools.generated_artifact_contract import ArtifactRejected
from tests.test_generated_artifact_contract import fixture, zip_bytes

HEAD = "b" * 40
DIST = "d" * 40
ROOT = "c" * 40
NEW_TREE = "e" * 40
NEW_HEAD = "f" * 40


class FakeGitHub:
    repository = "kinoko34077/example"

    def __init__(self, files, *, unchanged=False):
        self.files = dict(files)
        self.branch_head = HEAD
        self.protected = False
        self.repo_name = self.repository
        self.rulesets = []
        self.pr = True
        self.mode = "100644"
        self.parent_mode = "040000"
        self.truncated = False
        self.target_repo = self.repository
        self.head_repo = self.repository
        self.base_repo = self.repository
        self.extra_diff = False
        self.force_attempts = []
        self.calls = []
        self.reject_patch = False
        self.shift_before_patch = False
        self.tampered_current = False
        old_files = files if unchanged else {
            "dist/output.json": b"previous value",
            "dist/table.bin": b"previous binary",
        }
        self.objects = {}
        for path, data in old_files.items():
            sha = hashlib.sha1(path.encode() + data).hexdigest()
            self.objects[sha] = data
        self.first_blob_shas = {
            path: hashlib.sha1(path.encode() + data).hexdigest()
            for path, data in old_files.items()
        }
        self.commits = {
            HEAD: {"sha": HEAD, "tree": {"sha": ROOT}, "parents": [],
                   "message": "previous"}
        }
        self.current_tree = ROOT
        self.new_entries = None

    def get(self, path):
        self.calls.append(("GET", path))
        if path == "":
            return {"full_name": self.repo_name, "default_branch": "main"}
        if path.startswith("/branches/"):
            return {"commit": {"sha": self.branch_head}, "protected": self.protected}
        if path.startswith("/pulls?"):
            if not self.pr:
                return []
            return [{
                "state": "open",
                "head": {"ref": "artifact/pilot-1", "repo": {"full_name": self.head_repo}},
                "base": {"repo": {"full_name": self.base_repo}},
                "number": 300,
            }]
        if path == "/rulesets":
            return self.rulesets
        if path.startswith("/git/commits/"):
            return self.commits[path.rsplit("/", 1)[-1]]
        if path.startswith("/git/trees/"):
            sha = path.rsplit("/", 1)[-1]
            if sha in (ROOT, NEW_TREE):
                return {"truncated": self.truncated, "tree": [{"path": "dist", "type": "tree",
                                  "mode": self.parent_mode, "sha": DIST}]}
            if sha == DIST:
                return {"truncated": False, "tree": [
                    {"path": p.split("/")[1], "type": "blob", "mode": self.mode,
                     "sha": self.first_blob_shas[p] if self.new_entries is None
                         else self.new_entries[p]}
                    for p in sorted(self.files)
                ]}
        if path.startswith("/git/blobs/"):
            blob = self.objects[path.rsplit("/", 1)[-1]]
            return {"encoding": "base64", "content": base64.b64encode(blob).decode()}
        if path.startswith("/compare/"):
            files = [{"filename": p, "status": "modified"} for p in sorted(self.files)]
            if self.extra_diff:
                files.append({"filename": "src/hack.ts", "status": "modified"})
            return {"status": "ahead", "ahead_by": 1, "files": files}
        raise AssertionError("unexpected GET " + path)

    def post(self, path, payload):
        self.calls.append(("POST", path))
        if path == "/git/blobs":
            data = base64.b64decode(payload["content"])
            sha = hashlib.sha1(data).hexdigest()
            self.objects[sha] = data
            return {"sha": sha}
        if path == "/git/trees":
            assert payload["base_tree"] == ROOT, payload
            assert all(e["mode"] == "100644" for e in payload["tree"])
            self.new_entries = {
                e["path"]: e["sha"] for e in payload["tree"]
            }
            # All files in this test fixture are changed.
            assert set(self.new_entries) == set(self.files)
            return {"sha": NEW_TREE}
        if path == "/git/commits":
            assert payload["parents"] == [HEAD]
            assert payload["tree"] == NEW_TREE
            self.commits[NEW_HEAD] = {
                "sha": NEW_HEAD, "parents": [{"sha": HEAD}],
                "tree": {"sha": NEW_TREE}, "message": payload["message"],
            }
            return {"sha": NEW_HEAD}
        raise AssertionError("unexpected POST " + path)

    def patch(self, path, payload):
        self.calls.append(("PATCH", path))
        assert path == "/git/refs/heads/artifact/pilot-1"
        self.force_attempts.append(payload["force"])
        if self.reject_patch or self.branch_head != HEAD:
            raise WritebackRejected("non-force update rejected by branch movement")
        self.branch_head = payload["sha"]
        return {"ref": "refs/heads/artifact/pilot-1"}

    @property
    def mutation_count(self):
        return len([c for c in self.calls if c[0] in ("POST", "PATCH")])


class GeneratedArtifactWriterTests(unittest.TestCase):
    def setUp(self):
        self.policy, self.admission, self.manifest, self.files = fixture()
        self.zipped = zip_bytes(self.files)
        self.api = FakeGitHub(self.files)

    def invoke(self, *, dry_run=True, api=None, manifest=None, zipdata=None):
        return verified_writeback(
            api or self.api, self.policy, self.admission,
            manifest or self.manifest, zipdata or self.zipped, dry_run=dry_run
        )

    def test_dry_run_does_not_mutate_git(self):
        result = self.invoke()
        self.assertEqual(result["status"], "DRY_RUN")
        self.assertFalse(result["writes_performed"])
        self.assertEqual(result["target_head"], HEAD)
        self.assertEqual(self.api.mutation_count, 0)

    def test_write_is_exact_branch_nonforce_and_replay_noop(self):
        result = self.invoke(dry_run=False)
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(result["new_head"], NEW_HEAD)
        self.assertEqual(self.api.force_attempts, [False])
        before = self.api.mutation_count
        again = self.invoke(dry_run=False)
        self.assertEqual(again["status"], "NO_OP_REPLAY")
        self.assertFalse(again["writes_performed"])
        self.assertEqual(self.api.mutation_count, before)
        self.assertIs(again["ci_verified"], False)

    def test_identical_current_generated_bytes_is_noop(self):
        api = FakeGitHub(self.files, unchanged=True)
        result = self.invoke(api=api, dry_run=False)
        self.assertEqual(result["status"], "NO_OP")
        self.assertEqual(api.mutation_count, 0)

    def test_existing_special_modes_rejected_before_any_write(self):
        for mode in ("120000", "160000", "040000", "100755", None):
            with self.subTest(mode=mode):
                api = FakeGitHub(self.files)
                api.mode = mode
                with self.assertRaises(WritebackRejected):
                    self.invoke(api=api, dry_run=False)
                self.assertEqual(api.mutation_count, 0)

    def test_truncated_tree_listing_rejected_before_any_write(self):
        api = FakeGitHub(self.files)
        api.truncated = True
        with self.assertRaises(WritebackRejected):
            self.invoke(api=api, dry_run=False)
        self.assertEqual(api.mutation_count, 0)

    def test_unsafe_parent_path_rejected(self):
        api = FakeGitHub(self.files)
        api.parent_mode = "120000"
        with self.assertRaises(WritebackRejected):
            self.invoke(api=api, dry_run=False)
        self.assertEqual(api.mutation_count, 0)

    def test_protected_branch_or_unverified_rulesets_rejected(self):
        for protected, rules in [(True, []), (None, []), (False, [{"id": 1}]), (False, None)]:
            with self.subTest(protected=protected, rules=rules):
                api = FakeGitHub(self.files)
                api.protected = protected
                api.rulesets = rules
                with self.assertRaises(WritebackRejected):
                    self.invoke(api=api, dry_run=False)
                self.assertEqual(api.mutation_count, 0)

    def test_wrong_repository_or_pr_identity_rejected(self):
        for field, value in [
            ("repo_name", "kinoko34077/other"), ("pr", False),
            ("head_repo", "outsider/fork"), ("base_repo", "outsider/fork"),
        ]:
            with self.subTest(field=field):
                api = FakeGitHub(self.files)
                setattr(api, field, value)
                with self.assertRaises(WritebackRejected):
                    self.invoke(api=api, dry_run=False)
                self.assertEqual(api.mutation_count, 0)

    def test_moved_head_rejected_before_mutation(self):
        api = FakeGitHub(self.files)
        api.branch_head = "9" * 40
        api.commits[api.branch_head] = {
            "sha": api.branch_head, "tree": {"sha": ROOT},
            "parents": [{"sha": HEAD}], "message": "unrelated commit"
        }
        with self.assertRaises(WritebackRejected):
            self.invoke(api=api, dry_run=False)
        self.assertEqual(api.mutation_count, 0)

    def test_nonforce_push_race_rejected(self):
        api = FakeGitHub(self.files)
        api.reject_patch = True
        with self.assertRaises(WritebackRejected):
            self.invoke(api=api, dry_run=False)
        self.assertEqual(api.force_attempts, [False])
        self.assertEqual(api.branch_head, HEAD)

    def test_producer_payload_digest_mismatch_rejected_before_write(self):
        files = dict(self.files)
        files["dist/table.bin"] = b"not same"
        with self.assertRaises(ArtifactRejected):
            self.invoke(dry_run=False, zipdata=zip_bytes(files))
        self.assertEqual(self.api.mutation_count, 0)

    def test_replay_spoofed_extra_source_diff_rejected(self):
        self.invoke(dry_run=False)
        self.api.extra_diff = True
        with self.assertRaises(WritebackRejected):
            self.invoke(dry_run=False)


if __name__ == "__main__":
    unittest.main()
