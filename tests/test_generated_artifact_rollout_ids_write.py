"""Fail-closed IDS W1.4 boundary unit tests."""
import base64
import copy
import hashlib
import io
import unittest
from unittest.mock import patch
import zipfile

from tools import generated_artifact_rollout_ids_write as ids_write
from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import fixed_policy
from tools.generated_artifact_writer import verified_writeback
from tools.generated_artifact_rollout_ids_write import (
    REPOSITORY, RECIPE, OUTPUTS, NarrowIdsWriteApi,
    validate_target, validate_outputs, validate_policy, plan_ids_scoped_write,
)

HEAD = "a" * 40
BASE_TREE = "b" * 40
BLOB_SHA = "c" * 40
TREE_SHA = "d" * 40
COMMIT_SHA = "e" * 40

class FakeTransport:
    repository = REPOSITORY
    def post(self, *_):
        raise AssertionError("must never mutate")
    def patch(self, *_):
        raise AssertionError("must never mutate")


class RecordingTransport:
    repository = REPOSITORY
    branch = "artifact/writeback-ids/probe"

    def __init__(self):
        self.get_calls = []
        self.post_calls = []
        self.patch_calls = []
        self.branch_head = HEAD

    def get(self, path):
        self.get_calls.append(path)
        if path == f"/branches/{self.branch}":
            return {"protected": False, "commit": {"sha": self.branch_head}}
        if path == f"/git/commits/{HEAD}":
            return {"sha": HEAD, "tree": {"sha": BASE_TREE}, "parents": []}
        return {}

    def post(self, path, payload):
        self.post_calls.append((path, dict(payload)))
        if path == "/git/blobs":
            data = base64.b64decode(payload["content"], validate=True)
            sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            return {"sha": sha}
        return {"/git/trees": {"sha": TREE_SHA}, "/git/commits": {"sha": COMMIT_SHA}}[path]

    def patch(self, path, payload):
        self.patch_calls.append((path, dict(payload)))
        self.branch_head = payload["sha"]
        return {"ref": path}


def git_blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class IdsIntegrationTransport(RecordingTransport):
    """GitHub-shaped read model for one fixed IDS write through shared core."""

    data_tree = "6" * 40
    known_tree = "7" * 40
    generated_tree = "8" * 40
    reports_tree = "9" * 40

    def __init__(self, old_files):
        super().__init__()
        self.old_files = dict(old_files)
        self.blobs = {git_blob_sha(data): data for data in self.old_files.values()}
        generated_path, report_path = sorted(OUTPUTS)
        self.tree_nodes = {
            BASE_TREE: [{"path": "data", "mode": "040000", "type": "tree", "sha": self.data_tree}],
            self.data_tree: [{"path": "known", "mode": "040000", "type": "tree", "sha": self.known_tree}],
            self.known_tree: [
                {"path": "generated", "mode": "040000", "type": "tree", "sha": self.generated_tree},
                {"path": "reports", "mode": "040000", "type": "tree", "sha": self.reports_tree},
            ],
            self.generated_tree: [{
                "path": generated_path.rsplit("/", 1)[-1], "mode": "100644", "type": "blob",
                "sha": git_blob_sha(self.old_files[generated_path]),
            }],
            self.reports_tree: [{
                "path": report_path.rsplit("/", 1)[-1], "mode": "100644", "type": "blob",
                "sha": git_blob_sha(self.old_files[report_path]),
            }],
        }
        self.created_tree_entries = []

    def get(self, path):
        self.get_calls.append(path)
        if path == "":
            return {"full_name": REPOSITORY, "default_branch": "main"}
        if path == f"/branches/{self.branch}":
            return {"protected": False, "commit": {"sha": self.branch_head}}
        if path.startswith("/pulls?"):
            return [{
                "state": "open",
                "head": {"ref": self.branch, "repo": {"full_name": REPOSITORY}},
                "base": {"repo": {"full_name": REPOSITORY}},
                "number": 11,
            }]
        if path == "/rulesets":
            return []
        if path == f"/git/commits/{HEAD}":
            return {"sha": HEAD, "tree": {"sha": BASE_TREE}, "parents": []}
        if path.startswith("/git/trees/"):
            sha = path.rsplit("/", 1)[-1]
            return {"truncated": False, "tree": self.tree_nodes[sha]}
        if path.startswith("/git/blobs/"):
            data = self.blobs[path.rsplit("/", 1)[-1]]
            return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, payload):
        self.post_calls.append((path, dict(payload)))
        if path == "/git/blobs":
            data = base64.b64decode(payload["content"], validate=True)
            sha = git_blob_sha(data)
            self.blobs[sha] = data
            return {"sha": sha}
        if path == "/git/trees":
            self.created_tree_entries = list(payload["tree"])
            return {"sha": TREE_SHA}
        if path == "/git/commits":
            return {"sha": COMMIT_SHA}
        raise AssertionError(f"unexpected POST {path}")

class IdsBoundaryTests(unittest.TestCase):
    def test_fixed_scope(self):
        validate_target(REPOSITORY, RECIPE, "artifact/writeback-ids/probe", HEAD)
        for repo, recipe, branch, sha in [
            ("kinoko34077/testapp", RECIPE, "artifact/writeback-ids/probe", HEAD),
            (REPOSITORY, "other", "artifact/writeback-ids/probe", HEAD),
            (REPOSITORY, RECIPE, "main", HEAD),
            (REPOSITORY, RECIPE, "artifact/writeback-ids/probe", "bad"),
        ]:
            with self.assertRaises(ArtifactRejected):
                validate_target(repo, recipe, branch, sha)

    def test_target_rejects_git_invalid_ref_names(self):
        for branch in (
            "artifact/writeback-ids/probe..bad",
            "artifact/writeback-ids/probe.",
            "artifact/writeback-ids/probe.lock",
        ):
            with self.subTest(branch=branch), self.assertRaises(ArtifactRejected):
                validate_target(REPOSITORY, RECIPE, branch, HEAD)

    def test_output_validator_allows_only_changed_subset_of_fixed_recipe(self):
        one_path = next(iter(OUTPUTS))
        with patch.object(ids_write, "MAX_FILE_BYTES", 3), patch.object(ids_write, "MAX_TOTAL_BYTES", 5):
            validate_outputs({one_path: b"ok"})
            with self.assertRaises(ArtifactRejected):
                validate_outputs({})
            with self.assertRaises(ArtifactRejected):
                validate_outputs({"README.md": b"ok"})
            with self.assertRaises(ArtifactRejected):
                validate_outputs({one_path: b"four"})
            with self.assertRaises(ArtifactRejected):
                validate_outputs({path: b"123" for path in OUTPUTS})

    def test_policy_rejects_widening(self):
        from tools.generated_artifact_rollout import fixed_policy
        policy = fixed_policy(REPOSITORY, RECIPE, "a" * 40)
        validate_policy(policy)
        policy["recipe"]["paths"].append("unapproved.json")
        with self.assertRaises(ArtifactRejected):
            validate_policy(policy)

    def test_policy_pins_archive_and_expansion_limits(self):
        from tools.generated_artifact_rollout import fixed_policy
        policy = fixed_policy(REPOSITORY, RECIPE, HEAD)
        for key in ("max_archive_bytes", "max_expansion_ratio"):
            widened = copy.deepcopy(policy)
            widened["limits"][key] += 1
            with self.subTest(limit=key), self.assertRaises(ArtifactRejected):
                validate_policy(widened)

    def test_plan_rejects_effectful_mode_before_api(self):
        from pathlib import Path
        with self.assertRaises(ArtifactRejected):
            plan_ids_scoped_write(FakeTransport(), {"MODE": "write", "GITHUB_REPOSITORY": REPOSITORY}, Path("."),
                target_branch="artifact/writeback-ids/probe", expected_head="a" * 40,
                devflow_sha="a" * 40, devflow_checkout_sha="a" * 40)

    def test_write_is_dormant(self):
        api = NarrowIdsWriteApi(FakeTransport(), "artifact/writeback-ids/probe", "a" * 40)
        with self.assertRaises(ArtifactRejected):
            api.post("/git/blobs", {"content": "bad"})
        with self.assertRaises(ArtifactRejected):
            api.patch("/git/refs/heads/artifact/writeback-ids/probe", {"sha": HEAD, "force": False})
        with self.assertRaises(ArtifactRejected):
            api.get("/user")

    def test_get_rejects_noncanonical_and_traversal_routes_before_transport(self):
        transport = RecordingTransport()
        api = NarrowIdsWriteApi(transport, "artifact/writeback-ids/probe", HEAD)
        paths = (
            "/branches/main/../../user",
            "/branches/%2e%2e/user",
            "/actions/runs/12/../../user",
            "/git/commits/" + HEAD + "/../../user",
            "/compare/" + HEAD + "..." + HEAD + "/../user",
            "/pulls?state=open&head=wrong&extra=true",
            "/contents/.github/workflows/verified-artifacts-rollout.yml?ref=" + HEAD + "&extra=true",
        )
        for path in paths:
            with self.subTest(path=path), self.assertRaises(ArtifactRejected):
                api.get(path)
        self.assertEqual(transport.get_calls, [])

    def test_active_blob_requires_strict_base64_and_byte_limits(self):
        with patch.object(ids_write, "WRITER_ACTIVATED", True), \
             patch.object(ids_write, "MAX_FILE_BYTES", 3), \
             patch.object(ids_write, "MAX_TOTAL_BYTES", 6):
            for content in ("!!!!", base64.b64encode(b"four").decode("ascii")):
                transport = RecordingTransport()
                api = NarrowIdsWriteApi(transport, transport.branch, HEAD)
                api.get(f"/branches/{transport.branch}")
                api.get(f"/git/commits/{HEAD}")
                with self.subTest(content=content), self.assertRaises(ArtifactRejected):
                    api.post_blob_for_path(next(iter(OUTPUTS)), {"content": content, "encoding": "base64"})
                self.assertEqual(transport.post_calls, [])

    def test_active_tree_rejects_unapproved_output_path_before_post(self):
        transport = RecordingTransport()
        api = NarrowIdsWriteApi(transport, transport.branch, HEAD)
        with patch.object(ids_write, "WRITER_ACTIVATED", True):
            api.get(f"/branches/{transport.branch}")
            api.get(f"/git/commits/{HEAD}")
            blob = api.post_blob_for_path(next(iter(OUTPUTS)), {
                "content": base64.b64encode(b"ok").decode("ascii"),
                "encoding": "base64",
            })
            with self.assertRaises(ArtifactRejected):
                api.post("/git/trees", {
                    "base_tree": BASE_TREE,
                    "tree": [{"path": "README.md", "mode": "100644", "type": "blob", "sha": blob["sha"]}],
                })
        self.assertEqual([path for path, _ in transport.post_calls], ["/git/blobs"])

    def test_active_api_requires_verified_head_and_single_use_mutation_stages(self):
        transport = RecordingTransport()
        api = NarrowIdsWriteApi(transport, transport.branch, HEAD)
        first_path, second_path = sorted(OUTPUTS)
        first_payload = {"content": base64.b64encode(b"index-v2").decode("ascii"), "encoding": "base64"}
        second_payload = {"content": base64.b64encode(b"report-v2").decode("ascii"), "encoding": "base64"}
        with patch.object(ids_write, "WRITER_ACTIVATED", True):
            with self.assertRaises(ArtifactRejected):
                api.post_blob_for_path(first_path, first_payload)
            with self.assertRaises(ArtifactRejected):
                api.post("/git/blobs", first_payload)
            api.get(f"/branches/{transport.branch}")
            api.get(f"/git/commits/{HEAD}")
            first_blob = api.post_blob_for_path(first_path, first_payload)
            with self.assertRaises(ArtifactRejected):
                api.post_blob_for_path(first_path, first_payload)
            second_blob = api.post_blob_for_path(second_path, second_payload)
            tree_payload = {
                "base_tree": BASE_TREE,
                "tree": [
                    {"path": second_path, "mode": "100644", "type": "blob", "sha": second_blob["sha"]},
                    {"path": first_path, "mode": "100644", "type": "blob", "sha": first_blob["sha"]},
                ],
            }
            tree = api.post("/git/trees", tree_payload)
            with self.assertRaises(ArtifactRejected):
                api.post("/git/trees", tree_payload)
            commit_payload = {"message": "verified IDS output", "tree": tree["sha"], "parents": [HEAD]}
            commit = api.post("/git/commits", commit_payload)
            with self.assertRaises(ArtifactRejected):
                api.post("/git/commits", commit_payload)
            ref = f"/git/refs/heads/{transport.branch}"
            ref_payload = {"sha": commit["sha"], "force": False}
            api.patch(ref, ref_payload)
            with self.assertRaises(ArtifactRejected):
                api.patch(ref, ref_payload)
        self.assertEqual([path for path, _ in transport.post_calls], ["/git/blobs", "/git/blobs", "/git/trees", "/git/commits"])
        self.assertEqual(len(transport.patch_calls), 1)

    def test_active_api_rejects_swapped_blobs_between_approved_output_paths(self):
        transport = RecordingTransport()
        api = NarrowIdsWriteApi(transport, transport.branch, HEAD)
        first_path, second_path = sorted(OUTPUTS)
        with patch.object(ids_write, "WRITER_ACTIVATED", True):
            api.get(f"/branches/{transport.branch}")
            api.get(f"/git/commits/{HEAD}")
            first_blob = api.post_blob_for_path(first_path, {
                "content": base64.b64encode(b"index-v2").decode("ascii"), "encoding": "base64",
            })
            second_blob = api.post_blob_for_path(second_path, {
                "content": base64.b64encode(b"report-v2").decode("ascii"), "encoding": "base64",
            })
            with self.assertRaises(ArtifactRejected):
                api.post("/git/trees", {
                    "base_tree": BASE_TREE,
                    "tree": [
                        {"path": first_path, "mode": "100644", "type": "blob", "sha": second_blob["sha"]},
                        {"path": second_path, "mode": "100644", "type": "blob", "sha": first_blob["sha"]},
                    ],
                })
        self.assertEqual([path for path, _ in transport.post_calls], ["/git/blobs", "/git/blobs"])

    def test_active_commit_and_ref_update_require_validated_object_chain(self):
        transport = RecordingTransport()
        api = NarrowIdsWriteApi(transport, "artifact/writeback-ids/probe", HEAD)
        with patch.object(ids_write, "WRITER_ACTIVATED", True):
            with self.assertRaises(ArtifactRejected):
                api.post("/git/commits", {"message": "untrusted", "tree": TREE_SHA, "parents": [HEAD]})
            with self.assertRaises(ArtifactRejected):
                api.patch("/git/refs/heads/artifact/writeback-ids/probe", {"sha": TREE_SHA, "force": False})
        self.assertEqual(transport.post_calls, [])
        self.assertEqual(transport.patch_calls, [])

    def test_shared_writer_preserves_changed_output_path_through_validated_chain(self):
        transport = RecordingTransport()
        api = NarrowIdsWriteApi(transport, transport.branch, HEAD)
        first_path, second_path = sorted(OUTPUTS)
        with patch.object(ids_write, "WRITER_ACTIVATED", True):
            api.get(f"/branches/{transport.branch}")
            api.get(f"/git/commits/{HEAD}")
            first_blob = api.post_blob_for_path(first_path, {
                "content": base64.b64encode(b"index-v2").decode("ascii"), "encoding": "base64",
            })
            second_blob = api.post_blob_for_path(second_path, {
                "content": base64.b64encode(b"report-v2").decode("ascii"), "encoding": "base64",
            })
            tree = api.post("/git/trees", {
                "base_tree": BASE_TREE,
                "tree": [
                    {"path": first_path, "mode": "100644", "type": "blob", "sha": first_blob["sha"]},
                    {"path": second_path, "mode": "100644", "type": "blob", "sha": second_blob["sha"]},
                ],
            })
            commit = api.post("/git/commits", {
                "message": "verified IDS output",
                "tree": tree["sha"],
                "parents": [HEAD],
            })
            api.patch(f"/git/refs/heads/{transport.branch}", {"sha": commit["sha"], "force": False})
        self.assertEqual([path for path, _ in transport.post_calls], ["/git/blobs", "/git/blobs", "/git/trees", "/git/commits"])
        self.assertEqual(len(transport.patch_calls), 1)

    def test_shared_writer_integrates_fixed_ids_plan_with_changed_subset(self):
        branch = "artifact/writeback-ids/probe"
        workflow_sha = "9" * 40
        policy = fixed_policy(REPOSITORY, RECIPE, workflow_sha)
        report_path, index_path = sorted(OUTPUTS)
        outputs = {report_path: b"report-v1", index_path: b"index-v2"}
        old_files = {report_path: outputs[report_path], index_path: b"index-v1"}
        admission = {
            "repository": REPOSITORY, "actor": "kinoko34077", "branch": branch,
            "expected_head": HEAD, "source_sha": "f" * 40,
            "recipe_id": RECIPE, "recipe_version": "1",
            "producer_run_id": 123, "producer_run_attempt": 1,
            "producer_workflow_ref": policy["producer_workflow_ref"],
        }
        manifest = {
            "schema": "generated-artifacts.v1", "provenance": dict(admission),
            "files": [
                {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for path, data in sorted(outputs.items())
            ],
        }
        archive_io = io.BytesIO()
        with zipfile.ZipFile(archive_io, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, data in sorted(outputs.items()):
                archive.writestr(path, data)
        transport = IdsIntegrationTransport(old_files)
        class RecordingIdsWriteApi(NarrowIdsWriteApi):
            def __init__(self, *args):
                super().__init__(*args)
                self.bound_blob_paths = []

            def post_blob_for_path(self, path, payload):
                self.bound_blob_paths.append(path)
                return super().post_blob_for_path(path, payload)

        api = RecordingIdsWriteApi(transport, branch, HEAD)
        with patch.object(ids_write, "WRITER_ACTIVATED", True):
            result = verified_writeback(api, policy, admission, manifest, archive_io.getvalue(), dry_run=False)
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual([change["path"] for change in result["changes"]], [index_path])
        self.assertEqual([entry["path"] for entry in transport.created_tree_entries], [index_path])
        self.assertEqual(api.bound_blob_paths, [index_path])

if __name__ == "__main__":
    unittest.main()
