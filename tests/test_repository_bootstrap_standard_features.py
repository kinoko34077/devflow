from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.test_repository_bootstrap import issue_body
from tests.test_repository_bootstrap_executor import FakeApi, context
from tools import repository_bootstrap as rb
from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import select_fixed_recipe


ROOT = Path(__file__).resolve().parents[1]
FEATURES_PATH = ".devflow/standard-features.json"
NATIVE_PATH = ".github/workflows/kinotch-repo-command.yml"
ROLLOUT_CALLER_PATH = ".github/workflows/verified-artifacts-rollout.yml"
DEVFLOW_SHA = "a" * 40


def request(features=None):
    payload = rb.parse_request_body(issue_body())
    if features is not None:
        payload["bootstrap"]["standard_features"] = features
    payload["bootstrap"].pop("repo_native_dispatch", None)
    return rb.normalize_request(payload, "[REPO CREATE] example-repo")


def context_with_sha(sha=DEVFLOW_SHA):
    value = context()
    # Keep the RED contract independent of the production dataclass extension.
    object.__setattr__(value, "devflow_sha", sha)
    return value


class BootstrapStandardFeatureTests(unittest.TestCase):
    def test_generated_artifact_feature_requires_and_installs_existing_receiver(self):
        req = request(["repo_native_dispatch", "generated-artifact-writeback"])
        self.assertTrue(req.repo_native_dispatch)
        self.assertTrue(req.generated_artifact_writeback)

        repository, devflow = FakeApi(), FakeApi()
        result = rb.BootstrapExecutor(repository, devflow).execute(req, context())
        manifest = repository.files[("kinoko34077/example-repo", FEATURES_PATH)]

        self.assertEqual(json.loads(manifest), rb.standard_feature_manifest(req))
        self.assertIn(("kinoko34077/example-repo", NATIVE_PATH), repository.files)
        self.assertIn(f"file:{FEATURES_PATH}", result.resources)
        feature = json.loads(manifest)["features"][0]
        self.assertEqual(feature["id"], "generated-artifact-writeback")
        self.assertEqual(feature["dry_run_caller"], ROLLOUT_CALLER_PATH)
        self.assertEqual(feature["no_output"], {
            "status": "NOT_APPLICABLE", "reason": "NO_GENERATED_OUTPUT"
        })
        self.assertEqual(feature["writer"], "tools.generated_artifact_writer.verified_writeback")
        self.assertFalse(feature["effectful_write"]["enabled_by_bootstrap"])
        self.assertTrue(feature["effectful_write"]["dry_run_enabled_by_bootstrap"])
        done = [body for _, _, body in devflow.comments]
        self.assertTrue(any(
            "Generated-Artifact-Writeback: NOT_APPLICABLE/NO_GENERATED_OUTPUT" in body
            for body in done
        ))

    def test_standard_feature_seeds_pinned_read_only_rollout_caller(self):
        req = request(["repo_native_dispatch", "generated-artifact-writeback"])
        repository = FakeApi()

        rb.BootstrapExecutor(repository, FakeApi()).execute(req, context_with_sha())

        caller = repository.files[("kinoko34077/example-repo", ROLLOUT_CALLER_PATH)]
        self.assertEqual(caller.count(DEVFLOW_SHA), 2)
        self.assertIn("options: [dry-run]", caller)
        self.assertIn("contents: read", caller)
        self.assertIn("actions: read", caller)
        self.assertIn("pull-requests: read", caller)
        self.assertNotIn("contents: write", caller)
        self.assertIn("generated-artifact-rollout.yml@" + DEVFLOW_SHA, caller)

    def test_standard_caller_retry_preserves_its_original_pin(self):
        req = request(["repo_native_dispatch", "generated-artifact-writeback"])
        repository = FakeApi()
        executor = rb.BootstrapExecutor(repository, FakeApi())

        executor.execute(req, context_with_sha(DEVFLOW_SHA))
        original = repository.files[("kinoko34077/example-repo", ROLLOUT_CALLER_PATH)]
        executor.execute(req, context_with_sha("b" * 40))

        self.assertEqual(repository.files[("kinoko34077/example-repo", ROLLOUT_CALLER_PATH)], original)

    def test_changed_standard_caller_fails_closed_without_overwrite(self):
        req = request(["repo_native_dispatch", "generated-artifact-writeback"])
        repository = FakeApi()
        executor = rb.BootstrapExecutor(repository, FakeApi())
        executor.execute(req, context_with_sha())
        key = ("kinoko34077/example-repo", ROLLOUT_CALLER_PATH)
        repository.files[key] += "\n# local change\n"

        with self.assertRaises(rb.BootstrapFailure) as caught:
            executor.execute(req, context_with_sha())

        self.assertEqual(caught.exception.stage, "SEED")
        self.assertIn("local change", repository.files[key])

    def test_missing_or_invalid_bootstrap_sha_fails_before_repository_creation(self):
        req = request(["repo_native_dispatch", "generated-artifact-writeback"])
        repository = FakeApi()

        with self.assertRaises(rb.BootstrapError):
            rb.BootstrapExecutor(repository, FakeApi()).execute(req, context_with_sha("main"))

        self.assertEqual(repository.repos, {})

    def test_legacy_v1_request_does_not_gain_standard_features(self):
        req = request()
        self.assertFalse(req.repo_native_dispatch)
        self.assertFalse(req.generated_artifact_writeback)
        repository = FakeApi()
        rb.BootstrapExecutor(repository, FakeApi()).execute(req, context())
        self.assertNotIn(("kinoko34077/example-repo", FEATURES_PATH), repository.files)
        self.assertNotIn(("kinoko34077/example-repo", NATIVE_PATH), repository.files)

    def test_standard_feature_retry_is_idempotent(self):
        req = request(["repo_native_dispatch", "generated-artifact-writeback"])
        repository, devflow = FakeApi(), FakeApi()
        rb.BootstrapExecutor(repository, devflow).execute(req, context())
        prior = dict(repository.files)
        rb.BootstrapExecutor(repository, devflow).execute(req, context())
        self.assertEqual(repository.files, prior)

    def test_existing_feature_manifest_mismatch_fails_closed(self):
        req = request(["repo_native_dispatch", "generated-artifact-writeback"])
        repository, devflow = FakeApi(), FakeApi()
        rb.BootstrapExecutor(repository, devflow).execute(req, context())
        repository.files[("kinoko34077/example-repo", FEATURES_PATH)] = "{\"edited\":true}"
        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(req, context())
        self.assertEqual(caught.exception.stage, "SEED")
        self.assertEqual(repository.files[("kinoko34077/example-repo", FEATURES_PATH)], "{\"edited\":true}")

    def test_feature_list_rejects_duplicates_unknown_ids_and_missing_receiver(self):
        for features in (
            [],
            ["repo_native_dispatch"],
            ["repo_native_dispatch", "repo_native_dispatch"],
            ["generated-artifact-writeback", "unknown"],
            ["generated-artifact-writeback"],
        ):
            payload = rb.parse_request_body(issue_body())
            payload["bootstrap"]["standard_features"] = features
            payload["bootstrap"].pop("repo_native_dispatch", None)
            with self.subTest(features=features), self.assertRaises(rb.BootstrapError):
                rb.normalize_request(payload, "[REPO CREATE] example-repo")

    def test_explicit_legacy_alias_must_match_feature_list(self):
        payload = rb.parse_request_body(issue_body())
        payload["bootstrap"]["repo_native_dispatch"] = False
        payload["bootstrap"]["standard_features"] = ["repo_native_dispatch"]
        with self.assertRaises(rb.BootstrapError):
            rb.normalize_request(payload, "[REPO CREATE] example-repo")

    def test_standard_feature_points_only_to_existing_fixed_writer_route(self):
        req = request(["repo_native_dispatch", "generated-artifact-writeback"])
        feature = rb.standard_feature_manifest(req)["features"][0]
        self.assertEqual(
            select_fixed_recipe("kinoko34077/testapp", "testapp-public-fixture-v1").outputs,
            ("data/writeback-e2e/generated.json",),
        )
        with self.assertRaises(ArtifactRejected):
            select_fixed_recipe("kinoko34077/example-repo", "testapp-public-fixture-v1")
        self.assertEqual(
            feature["recipe_registry"], "tools.generated_artifact_rollout.select_fixed_recipe"
        )
        self.assertEqual(
            feature["writer"], "tools.generated_artifact_writer.verified_writeback"
        )

    def test_published_feature_schemas_are_valid_json_and_forbid_bootstrap_write_grants(self):
        bootstrap_schema = json.loads(
            (ROOT / "schemas/repository-bootstrap.v1.schema.json").read_text(encoding="utf-8")
        )
        manifest_schema = json.loads(
            (ROOT / "schemas/devflow-standard-features.v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertFalse(bootstrap_schema["additionalProperties"])
        self.assertEqual(
            bootstrap_schema["properties"]["bootstrap"]["properties"]["standard_features"]["items"]["enum"],
            ["repo_native_dispatch", "generated-artifact-writeback"],
        )
        feature_properties = manifest_schema["$defs"]["feature"]["properties"]
        self.assertEqual(feature_properties["dry_run_caller"]["const"], ROLLOUT_CALLER_PATH)
        self.assertIs(feature_properties["effectful_write"]["properties"]["dry_run_enabled_by_bootstrap"]["const"], True)
        feature = manifest_schema["$defs"]["feature"]["properties"]["effectful_write"]["properties"]
        self.assertIs(feature["enabled_by_bootstrap"]["const"], False)
        self.assertIs(feature["dry_run_enabled_by_bootstrap"]["const"], True)
        self.assertIs(feature["human_gate_required"]["const"], True)

    def test_issue_and_cross_repository_manual_define_separate_finite_lifecycle(self):
        root = Path(__file__).resolve().parents[1]
        issue_manual = (root / "docs/operations/REPOSITORY_ISSUE_MANUAL.md").read_text(encoding="utf-8")
        cross_spec = (root / "docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md").read_text(encoding="utf-8")
        bootstrap_spec = (root / "docs/spec/REPOSITORY_BOOTSTRAP.md").read_text(encoding="utf-8")
        self.assertIn("new managed repositories receive the standard path", issue_manual)
        self.assertIn("do not keep it open", issue_manual)
        self.assertIn("separate rollout Issue", cross_spec)
        self.assertIn("finite reviewable waves", cross_spec)
        self.assertIn("bootstrap.standard_features", bootstrap_spec)
        self.assertIn("NOT_APPLICABLE/NO_GENERATED_OUTPUT", bootstrap_spec)


if __name__ == "__main__":
    unittest.main()
