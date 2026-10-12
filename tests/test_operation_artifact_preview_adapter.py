"""A3 acceptance: actual #465 preview -> shared A2 report; no effect rights."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from tests.test_generated_artifact_rollout import REPO, RECIPE, SHA, BRANCH
from tests.test_generated_artifact_rollout_admission import FakeGitHubReader
from tests.test_generated_artifact_rollout_dryrun import make_bundle, args
from tools.generated_artifact_contract import ArtifactRejected
from tools.operation_artifact_preview_adapter import (
    BUNDLE_SCHEMA, preview_and_project_authenticated,
)
from tools.operation_preflight_projection import ProjectionRejected

_REQUEST = "req_a3_00000001"
_CATALOG = "f" * 40


def call_parameters(artifact: pathlib.Path, reader: FakeGitHubReader | None = None):
    return {
        **args(artifact, reader or FakeGitHubReader()),
        "request_id": _REQUEST,
        "catalog_source_sha": _CATALOG,
    }


def execute(params, *, existing=None):
    # Native #465 validated read-only planning is real; fake GitHub target
    # uses the same registered recipe/current head as the accepted R1 tests.
    from tools.generated_artifact_rollout import fixed_policy
    from tests.test_generated_artifact_rollout import runner
    paths = fixed_policy(REPO, RECIPE, runner()["GITHUB_WORKFLOW_SHA"])["recipe"]["paths"]
    old_files = existing if existing is not None else {p: b"OLD" for p in paths}
    with (
        patch("tools.generated_artifact_writer._read_target", return_value={
            "head": SHA, "tree_sha": "c" * 40, "pr_number": 11,
        }),
        patch("tools.generated_artifact_writer._read_files", return_value=old_files),
    ):
        return preview_and_project_authenticated(**params)


class OperationArtifactPreviewAdapterTests(unittest.TestCase):
    def test_existing_readonly_preview_to_common_evidence_without_extra_gets(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            reader = FakeGitHubReader()
            report = execute(call_parameters(artifact, reader))
        self.assertEqual(reader.calls, [
            "/actions/runs/501",
            "/actions/workflows/89",
            "/contents/.github/workflows/verified-artifacts-rollout.yml?ref=" + "b"*40,
        ])
        self.assertEqual(report["schema"], BUNDLE_SCHEMA)
        self.assertEqual(report["native_preview"]["status"], "DRY_RUN")
        self.assertEqual(report["projection"]["native_status"], "DRY_RUN")
        self.assertEqual(report["projection"]["observed_head"], SHA)
        self.assertEqual(report["projection"]["request_id"], _REQUEST)
        self.assertFalse(report["effect_authorized"])
        self.assertTrue(report["requires_fresh_writer_revalidation"])
        self.assertFalse(report["native_preview"]["writer_authorized"])
        self.assertFalse(report["native_preview"]["writes_performed"])
        self.assertFalse(report["projection"]["effect_authorized"])
        self.assertEqual(report["projection"]["trust_status"], "PROJECTION_ONLY_UNAUTHENTICATED")
        self.assertNotIn("token", json.dumps(report).lower())

    def test_native_noop_remains_noop_not_commit_or_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            source = pathlib.Path(tmp) / "source"
            from tools.generated_artifact_rollout import select_fixed_recipe
            old_files = {
                p: (source / p).read_bytes()
                for p in select_fixed_recipe(REPO, RECIPE).outputs
            }
            reader = FakeGitHubReader()
            report = execute(call_parameters(artifact, reader), existing=old_files)
        self.assertEqual(report["native_preview"]["status"], "NO_OP")
        self.assertEqual(report["projection"]["native_status"], "NO_OP")
        self.assertFalse(report["projection"]["changes"])
        self.assertFalse(report["effect_authorized"])
        self.assertEqual(len(reader.calls), 3)

    def test_write_mode_denied_before_any_github_get_or_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            reader = FakeGitHubReader()
            params = call_parameters(artifact, reader)
            params["env"]["MODE"] = "write"
            with self.assertRaises(ArtifactRejected):
                execute(params)
            self.assertEqual(reader.calls, [])

    def test_forged_actor_run_source_workflow_branch_repo_rejected(self):
        for key, value in (
            ("GITHUB_ACTOR", "stranger"),
            ("GITHUB_TRIGGERING_ACTOR", "stranger"),
            ("GITHUB_RUN_ID", "502"),
            ("GITHUB_WORKFLOW_SHA", "a" * 40),
            ("GITHUB_REPOSITORY", "kinoko34077/testapp"),
        ):
            with self.subTest(field=key), tempfile.TemporaryDirectory() as tmp:
                reader = FakeGitHubReader()
                params = call_parameters(make_bundle(tmp), reader)
                params["env"][key] = value
                with self.assertRaises(ArtifactRejected):
                    execute(params)
        for key, value in (
            ("target_branch", "artifact/writeback-ids/malicious"),
            ("expected_head", "d" * 40),
            ("repository", "kinoko34077/testapp"),
            ("recipe_id", "arbitrary"),
            ("devflow_checkout_sha", "b" * 40),
        ):
            with self.subTest(field=key), tempfile.TemporaryDirectory() as tmp:
                params = call_parameters(make_bundle(tmp))
                params[key] = value
                with self.assertRaises((ArtifactRejected, ProjectionRejected)):
                    execute(params)

    def test_manifest_or_zip_tamper_rejected_by_native_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            path = pathlib.Path(artifact) / "manifest.json"
            m = json.loads(path.read_text())
            m["files"][0]["path"] = "data/known/generated/evil.json"
            path.write_text(json.dumps(m))
            with self.assertRaises(ArtifactRejected):
                execute(call_parameters(artifact))
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            path = pathlib.Path(artifact) / "artifact.zip"
            path.write_bytes(b"not-a-valid-archive")
            with self.assertRaises(ArtifactRejected):
                execute(call_parameters(artifact))

    def test_projection_contract_rejects_invalid_request_or_catalog(self):
        for key, value in (
            ("request_id", "x"),
            ("catalog_source_sha", "A" * 40),
            ("catalog_source_sha", "b" * 39),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                params = call_parameters(make_bundle(tmp))
                params[key] = value
                with self.assertRaises(ProjectionRejected):
                    execute(params)

    def test_readonly_denies_post_patch_even_if_native_does_not(self):
        from tools.generated_artifact_rollout_dryrun import _ReadOnlyApi
        reader = FakeGitHubReader()
        read = _ReadOnlyApi(reader)
        with self.assertRaises(ArtifactRejected):
            read.post("/git/commits", {"message": "unsafe"})
        with self.assertRaises(ArtifactRejected):
            read.patch("/git/refs/heads/other", {"sha": SHA, "force": False})
        self.assertEqual(reader.calls, [])

    def test_separate_writer_never_called_during_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            params = call_parameters(artifact)
            with patch(
                "tools.generated_artifact_rollout_testapp_write.execute_testapp_scoped_write",
                side_effect=AssertionError("writer must not run")
            ):
                report = execute(params)
            self.assertFalse(report["effect_authorized"])


if __name__ == "__main__":
    unittest.main()
