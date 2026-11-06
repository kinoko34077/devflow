"""Offline R1 dry-run bridge tests; all GitHub mutation paths remain denied."""
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from tests.test_generated_artifact_rollout import (
    REPO, RECIPE, SHA, BRANCH, runner, params,
)
from tests.test_generated_artifact_rollout_admission import FakeGitHubReader, TEMPLATE
from tools import generated_artifact_rollout as rollout
from tools import generated_artifact_rollout_dryrun as dryrun
from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_writer import WritebackRejected


def source_files(tmp):
    root = pathlib.Path(tmp) / "source"
    for index, name in enumerate(rollout.select_fixed_recipe(REPO, RECIPE).outputs):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("{\"test\":" + str(index) + "}\n").encode())
    return root


def make_bundle(tmp):
    source = source_files(tmp)
    artifact_dir = pathlib.Path(tmp) / "artifact"
    rollout.package_from_fixed_source(REPO, RECIPE, runner(), source, artifact_dir, **params())
    return artifact_dir


def args(artifact_dir, api=None, *, mode="dry-run"):
    return {
        "api": api or FakeGitHubReader(),
        "env": {**runner(), "MODE": mode},
        "artifact_dir": artifact_dir,
        "repository": REPO, "recipe_id": RECIPE,
        "target_branch": BRANCH, "expected_head": SHA,
        "source_head": SHA, "devflow_sha": SHA, "devflow_checkout_sha": SHA,
        "trusted_template": TEMPLATE,
    }


class RolloutDryRunTests(unittest.TestCase):
    def run_preview(self, artifact, *, context=None, mode="dry-run", existing=None):
        api = context or FakeGitHubReader()
        p = rollout.fixed_policy(REPO, RECIPE, runner()["GITHUB_WORKFLOW_SHA"])
        old_files = existing if existing is not None else {
            path: b"OLD" for path in p["recipe"]["paths"]
        }
        with (
            patch("tools.generated_artifact_writer._read_target", return_value={
                "head": SHA, "tree_sha": "c" * 40, "pr_number": 11,
            }),
            patch("tools.generated_artifact_writer._read_files", return_value=old_files),
        ):
            result = dryrun.preview_authenticated(**args(artifact, api, mode=mode))
        return result, api

    def test_real_v1_archive_planner_through_get_only_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            result, api = self.run_preview(artifact)
            self.assertEqual(result["status"], "DRY_RUN")
            self.assertEqual(result["auth_status"], "AUTHENTICATED_READ_ONLY")
            self.assertEqual(len(result["changes"]), 2)
            self.assertEqual(result["target_head"], SHA)
            self.assertFalse(result["writes_performed"])
            self.assertFalse(result["writer_authorized"])
            self.assertFalse(result["ci_verified"])
            self.assertEqual(len(api.calls), 3)

    def test_existing_identical_bytes_only_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            source = pathlib.Path(tmp) / "source"
            old_files = {
                path: (source / path).read_bytes()
                for path in rollout.select_fixed_recipe(REPO, RECIPE).outputs
            }
            result, _ = self.run_preview(artifact, existing=old_files)
            self.assertEqual(result["status"], "NO_OP")
            self.assertFalse(result["writes_performed"])

    def test_write_mode_is_denied_before_independent_api_or_planner(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            reader = FakeGitHubReader()
            with self.assertRaises(ArtifactRejected):
                self.run_preview(artifact, context=reader, mode="write")
            self.assertEqual(reader.calls, [])

    def test_archive_digest_and_unapproved_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            original = (artifact / "manifest.json").read_bytes()
            manifest = json.loads(original)
            manifest["files"][0]["sha256"] = "0" * 64
            (artifact / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ArtifactRejected):
                self.run_preview(artifact)
            (artifact / "manifest.json").write_bytes(original)
            manifest = json.loads(original)
            manifest["files"][0]["path"] = "data/known/generated/evil.json"
            (artifact / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ArtifactRejected):
                self.run_preview(artifact)

    def test_missing_or_symlinked_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            archive = artifact / "artifact.zip"
            archive.unlink()
            with self.assertRaises(ArtifactRejected):
                self.run_preview(artifact)
            archive.symlink_to(artifact / "manifest.json")
            with self.assertRaises(ArtifactRejected):
                self.run_preview(artifact)

    def test_forbidden_post_and_patch_even_if_core_regresses(self):
        reader = FakeGitHubReader()
        bounded = dryrun._ReadOnlyApi(reader)
        with self.assertRaises(ArtifactRejected):
            bounded.post("/git/blobs", {"content": "payload"})
        with self.assertRaises(ArtifactRejected):
            bounded.patch("/git/refs/heads/test", {"sha": SHA, "force": False})
        self.assertEqual(reader.calls, [])


if __name__ == "__main__":
    unittest.main()
