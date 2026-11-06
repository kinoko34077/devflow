"""Offline A2 contract tests: no authorization or mutation from read-only preview."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from tests.test_generated_artifact_rollout import REPO, RECIPE, SHA, BRANCH, runner, params
from tests.test_generated_artifact_rollout_admission import FakeGitHubReader
from tests.test_generated_artifact_rollout_dryrun import make_bundle, args
from tools import generated_artifact_rollout as rollout
from tools import generated_artifact_rollout_dryrun as dryrun
from tools.operation_preflight_projection import (
    ProjectionRejected, SCHEMA, project_artifact_preview,
)

CATALOG_SHA = "f" * 40
REQUEST_ID = "req_a2_000001"


def trusted():
    policy = rollout.fixed_policy(REPO, RECIPE, runner()["GITHUB_WORKFLOW_SHA"])
    admission = rollout.producer_admission(policy, runner(), **params())
    return policy, admission


def native_preview():
    policy, admission = trusted()
    return {
        "schema": "generated-artifacts-plan.v1", "status": "DRY_RUN",
        "repository": REPO, "target_branch": BRANCH, "expected_head": SHA,
        "producer_run_id": admission["producer_run_id"],
        "manifest_sha256": "d" * 64, "file_count": len(policy["recipe"]["paths"]),
        "total_bytes": 100,
        "changes": [{"path": sorted(policy["recipe"]["paths"])[0],
                     "size": 20, "sha256": "e" * 64}],
        "writes_performed": False, "target_head": SHA, "ci_verified": False,
        "writer_authorized": False, "auth_status": "AUTHENTICATED_READ_ONLY",
    }


def project(data, *, policy=None, admission=None, request_id=REQUEST_ID, catalog_sha=CATALOG_SHA):
    p, a = trusted()
    return project_artifact_preview(
        json.dumps(data, sort_keys=True),
        trusted_policy=p if policy is None else policy,
        trusted_admission=a if admission is None else admission,
        request_id=request_id, catalog_source_sha=catalog_sha,
    )


class OperationPreflightProjectionTests(unittest.TestCase):
    def test_actual_existing_authenticated_readonly_preview_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = make_bundle(tmp)
            with (
                patch("tools.generated_artifact_writer._read_target", return_value={
                    "head": SHA, "tree_sha": "c" * 40, "pr_number": 11,
                }),
                patch("tools.generated_artifact_writer._read_files", return_value={
                    path: b"OLD" for path in trusted()[0]["recipe"]["paths"]
                }),
            ):
                original = dryrun.preview_authenticated(**args(
                    artifact_dir, FakeGitHubReader()
                ))
        policy, admission = trusted()
        evidence = project_artifact_preview(
            json.dumps(original), trusted_policy=policy, trusted_admission=admission,
            request_id=REQUEST_ID, catalog_source_sha=CATALOG_SHA,
        )
        self.assertEqual(evidence["schema"], SCHEMA)
        self.assertEqual(evidence["native_status"], "DRY_RUN")
        self.assertEqual(evidence["observed_head"], SHA)
        self.assertEqual(len(evidence["changes"]), 2)
        self.assertEqual(evidence["approved_paths"], sorted(policy["recipe"]["paths"]))
        self.assertEqual(len(evidence["diagnostic_sha256"]), 64)
        self.assertFalse(evidence["effect_authorized"])
        self.assertFalse(evidence["writes_performed"])
        self.assertTrue(evidence["requires_fresh_writer_revalidation"])
        self.assertEqual(evidence["trust_status"], "PROJECTION_ONLY_UNAUTHENTICATED")
        self.assertNotIn("token", json.dumps(evidence).lower())
        self.assertNotIn("writer_authorized", evidence)

    def test_valid_noop_is_nonauthorizing(self):
        v = native_preview()
        v.update(status="NO_OP", changes=[])
        result = project(v)
        self.assertEqual(result["native_status"], "NO_OP")
        self.assertFalse(result["effect_authorized"])

    def test_readonly_false_successes_denied(self):
        for key, value in (
            ("status", "COMMITTED"),
            ("status", "NO_OP_REPLAY"),
            ("status", "CLAIMED"),
            ("writes_performed", True),
            ("writer_authorized", True),
            ("ci_verified", True),
            ("auth_status", "SUCCESS"),
            ("schema", "operation-authorized.v1"),
            ("target_head", "b" * 40),
            ("expected_head", "b" * 40),
            ("producer_run_id", 502),
            ("producer_run_id", True),
            ("manifest_sha256", "xyz"),
            ("repository", "kinoko34077/testapp"),
            ("target_branch", "main"),
            ("target_branch", "artifact/writeback-ids/evil"),
            ("file_count", 1000),
            ("file_count", True),
            ("total_bytes", 1000000000),
            ("total_bytes", True),
            ("changes", []),
        ):
            with self.subTest(key=key, value=value):
                v = native_preview()
                v[key] = value
                with self.assertRaises(ProjectionRejected):
                    project(v)

    def test_noop_with_changes_and_duplicate_paths_denied(self):
        v = native_preview()
        v["status"] = "NO_OP"
        with self.assertRaises(ProjectionRejected):
            project(v)
        v = native_preview()
        v["changes"].append(copy.deepcopy(v["changes"][0]))
        with self.assertRaises(ProjectionRejected):
            project(v)

    def test_outside_allowed_path_and_bad_hash_or_size_denied(self):
        for key, value in (
            ("path", "secret/.env"),
            ("size", -1),
            ("size", True),
            ("size", 1000000000),
            ("sha256", "bad"),
        ):
            v = native_preview()
            v["changes"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ProjectionRejected):
                project(v)
        v = native_preview()
        v["total_bytes"] = 5  # changed bytes > whole archive
        with self.assertRaises(ProjectionRejected):
            project(v)

    def test_preview_json_extra_duplicate_keys_and_oversized_denied(self):
        p, a = trusted()
        v = native_preview()
        v["executor"] = "arbitrary.shell"
        with self.assertRaises(ProjectionRejected):
            project(v)
        raw = json.dumps(native_preview())
        duplicate = raw[:-1] + ',"schema":"generated-artifacts-plan.v1"}'
        with self.assertRaises(ProjectionRejected):
            project_artifact_preview(
                duplicate, trusted_policy=p, trusted_admission=a,
                request_id=REQUEST_ID, catalog_source_sha=CATALOG_SHA,
            )
        with self.assertRaises(ProjectionRejected):
            project_artifact_preview(
                raw + (" " * 131072), trusted_policy=p, trusted_admission=a,
                request_id=REQUEST_ID, catalog_source_sha=CATALOG_SHA,
            )

    def test_trusted_metadata_mismatch_and_invalid_catalog_denied(self):
        p, a = trusted()
        for key, value in (
            ("repository", "kinoko34077/testapp"),
            ("branch", "main"),
            ("expected_head", "b" * 40),
            ("actor", "outsider"),
            ("producer_workflow_ref", "other.yml"),
            ("recipe_id", "arbitrary"),
            ("producer_run_id", 999),
        ):
            with self.subTest(key=key):
                tampered = dict(a)
                tampered[key] = value
                with self.assertRaises(ProjectionRejected):
                    project(native_preview(), admission=tampered)
        bad_policy = copy.deepcopy(p)
        bad_policy["recipe"]["paths"][0] = "other-path.json"
        with self.assertRaises(ProjectionRejected):
            project(native_preview(), policy=bad_policy)
        for bad in ("f" * 39, "F" * 40, "x" * 40):
            with self.assertRaises(ProjectionRejected):
                project(native_preview(), catalog_sha=bad)
        with self.assertRaises(ProjectionRejected):
            project(native_preview(), request_id="x")

    def test_deterministic_diagnostic_digest_is_not_an_approval(self):
        v = native_preview()
        first = project(v)
        second = project(copy.deepcopy(v))
        self.assertEqual(first, second)
        v["changes"][0]["sha256"] = "a" * 64
        third = project(v)
        self.assertNotEqual(first["diagnostic_sha256"], third["diagnostic_sha256"])
        self.assertFalse(third["effect_authorized"])


if __name__ == "__main__":
    unittest.main()
