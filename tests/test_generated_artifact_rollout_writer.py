"""R1 non-activatable writer adapter contract tests, offline only."""
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from tests.test_generated_artifact_rollout import REPO, RECIPE, SHA
from tests.test_generated_artifact_rollout_admission import FakeGitHubReader
from tests.test_generated_artifact_rollout_dryrun import args, make_bundle
from tools.generated_artifact_contract import ArtifactRejected
from tools import generated_artifact_rollout_writer as dormant


class DormantWriterBoundaryTests(unittest.TestCase):
    def test_write_is_statistically_disabled_and_never_reads_or_mutates(self):
        self.assertIs(dormant.WRITE_ACTIVATED, False)
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            api = FakeGitHubReader()
            requested = args(artifact, api, mode="write")
            with self.assertRaisesRegex(ArtifactRejected, "not activated"):
                dormant.execute_reviewed_entry(**requested)
            self.assertEqual(api.calls, [])

    def test_dry_run_routes_through_accepted_core_and_remains_get_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            api = FakeGitHubReader()
            existing = {
                "data/known/generated/known-index-v0.2.json": b"old",
                "data/known/reports/known-index-v0.2.json": b"old",
            }
            with (
                patch("tools.generated_artifact_writer._read_target", return_value={
                    "head": SHA, "tree_sha": "c" * 40, "pr_number": 11,
                }),
                patch("tools.generated_artifact_writer._read_files", return_value=existing),
            ):
                result = dormant.execute_reviewed_entry(**args(artifact, api))
            self.assertEqual(result["status"], "DRY_RUN")
            self.assertEqual(result["authenticated_runner"], "AUTHENTICATED_READ_ONLY")
            self.assertEqual(result["writeback_enabled"], False)
            self.assertEqual(result["ci_verified"], False)
            self.assertFalse(result["writes_performed"])
            self.assertEqual(len(api.calls), 3)

    def test_other_unsafe_modes_and_actor_fail_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            api = FakeGitHubReader()
            for mode in ("write-replay-test", "delete", "", "WRITE"):
                with self.subTest(mode=mode), self.assertRaises(ArtifactRejected):
                    dormant.execute_reviewed_entry(**args(artifact, api, mode=mode))
            self.assertEqual(api.calls, [])

    def test_module_exports_no_runtime_write_enable_parameter(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = make_bundle(tmp)
            with self.assertRaises(TypeError):
                dormant.execute_reviewed_entry(**args(artifact), write_activated=True)


if __name__ == "__main__":
    unittest.main()
