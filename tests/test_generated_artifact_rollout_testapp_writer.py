"""R2 testapp-only effectful boundary regression, never contacts GitHub."""
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from tools.generated_artifact_contract import ArtifactRejected
from tools import generated_artifact_rollout as rollout
from tools import generated_artifact_rollout_testapp_writer as writer
from tests.test_generated_artifact_rollout_testapp import (
    REPO, RECIPE, TARGET, PATH, CALLER_SHA, DEVFLOW_SHA,
    TestappReader, env,
)


def prepared_artifact(tmp):
    source = pathlib.Path(tmp) / "source"
    target = source / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"schema":"synthetic-public-fixture"}\n', encoding="utf-8")
    destination = pathlib.Path(tmp) / "artifact"
    rollout.package_from_fixed_source(
        REPO, RECIPE, env(), source, destination,
        target_branch=TARGET, expected_head=DEVFLOW_SHA,
        source_head=DEVFLOW_SHA, devflow_sha=DEVFLOW_SHA,
        devflow_checkout_sha=DEVFLOW_SHA,
    )
    return destination


def kw(artifact, reader=None, **modifications):
    parameters = {
        "api": reader or TestappReader(),
        "env": env(MODE="write"),
        "artifact_dir": artifact,
        "repository": REPO, "recipe_id": RECIPE, "target_branch": TARGET,
        "expected_head": DEVFLOW_SHA, "source_head": DEVFLOW_SHA,
        "devflow_sha": DEVFLOW_SHA, "devflow_checkout_sha": DEVFLOW_SHA,
    }
    parameters.update(modifications)
    return parameters


class TestappRestrictedWriteApiTests(unittest.TestCase):
    def test_only_three_git_object_posts_and_exact_noforce_scratch_patch(self):
        class Transport:
            repository = REPO
            def __init__(self):
                self.calls = []
            def post(self, path, payload):
                self.calls.append(("POST", path, payload))
                return {"sha": "a" * 40}
            def patch(self, path, payload):
                self.calls.append(("PATCH", path, payload))
                return {"ref": path}
            def get(self, path):
                return {}
        transport = Transport()
        api = writer.RestrictedTestappWriteApi(transport)
        for path in ("/git/blobs", "/git/trees", "/git/commits"):
            api.post(path, {})
        good = {"force": False, "sha": "a" * 40}
        api.patch("/git/refs/heads/" + TARGET, good)
        self.assertEqual(len(transport.calls), 4)
        for path in ("/git/refs", "/issues", "/dispatches", "/actions/workflows/1/dispatches"):
            with self.subTest(path=path), self.assertRaises(ArtifactRejected):
                api.post(path, {})
        for path in ("/git/refs/heads/main", "/git/refs/heads/artifact/writeback-ids/1"):
            with self.subTest(path=path), self.assertRaises(ArtifactRejected):
                api.patch(path, good)
        for bad in ({"sha": "a" * 40, "force": True}, {"sha": "invalid", "force": False},
                    {"sha": "a" * 40, "force": False, "extra": "unsafe"}):
            with self.subTest(bad=bad), self.assertRaises(ArtifactRejected):
                api.patch("/git/refs/heads/" + TARGET, bad)

    def test_other_repository_is_unrepresentable(self):
        reader = TestappReader()
        reader.repository = "kinoko34077/IDS-Composit"
        with self.assertRaises(ArtifactRejected):
            writer.RestrictedTestappWriteApi(reader)

    def test_github_rest_auth_then_single_old_v1_core_with_noforce_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = prepared_artifact(tmp)
            reader = TestappReader()
            invocation = {}
            def existing_core(api, policy, admission, manifest, zip_bytes, *, dry_run):
                invocation.update(
                    repo=api.repository, api=api, policy=policy,
                    admission=admission, manifest=manifest, zip_bytes=zip_bytes,
                    dry_run=dry_run,
                )
                return {"status": "COMMITTED", "writes_performed": True, "new_head": "c" * 40}
            with patch.object(writer, "verified_writeback", side_effect=existing_core):
                out = writer.testapp_write(**kw(artifact, reader=reader))
            self.assertEqual(out["status"], "COMMITTED")
            self.assertFalse(out["ci_verified"])
            self.assertEqual(invocation["repo"], REPO)
            self.assertEqual(invocation["policy"]["recipe"]["paths"], [PATH])
            self.assertEqual(invocation["admission"]["producer_run_id"], 812)
            self.assertFalse(invocation["dry_run"])
            self.assertEqual(reader.calls, [
                "/actions/runs/812", "/actions/workflows/34",
                f"/contents/{rollout.CALLER_PATH}?ref={CALLER_SHA}",
            ])
            self.assertEqual(len(invocation["zip_bytes"]) > 0, True)

    def test_mode_repo_recipe_branch_and_context_rejected_without_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = prepared_artifact(tmp)
            changes = [
                {"env": env(MODE="dry-run")},
                {"env": env(MODE="write-replay-test")},
                {"repository": "kinoko34077/IDS-Composit"},
                {"recipe_id": "ids-known-merge-v0.2"},
                {"target_branch": "main"},
                {"target_branch": "artifact/writeback-testapp/different"},
                {"env": env(MODE="write", GITHUB_REPOSITORY="kinoko34077/IDS-Composit")},
            ]
            for change in changes:
                with self.subTest(change=change):
                    reader = TestappReader()
                    with self.assertRaises(ArtifactRejected):
                        writer.testapp_write(**kw(artifact, reader=reader, **change))
                    self.assertEqual(reader.calls, [])

    def test_archive_tampering_is_rejected_before_git_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = prepared_artifact(tmp)
            manifest = json.loads((artifact / "manifest.json").read_text())
            manifest["files"][0]["sha256"] = "0" * 64
            (artifact / "manifest.json").write_text(json.dumps(manifest))
            reader = TestappReader()
            # The reviewed v1 core must still reject modified manifest/ZIP.
            from tools.generated_artifact_contract import validate_and_plan
            with self.assertRaises(ArtifactRejected):
                validate_and_plan(
                    rollout.fixed_policy(REPO, RECIPE, CALLER_SHA),
                    rollout.producer_admission(
                        rollout.fixed_policy(REPO, RECIPE, CALLER_SHA),
                        env(), target_branch=TARGET,
                        expected_head=DEVFLOW_SHA, source_head=DEVFLOW_SHA,
                        devflow_sha=DEVFLOW_SHA, devflow_checkout_sha=DEVFLOW_SHA,
                    ),
                    manifest, (artifact / "artifact.zip").read_bytes(),
                    observed_head=DEVFLOW_SHA,
                    existing_files={PATH: b"old"},
                )


if __name__ == "__main__":
    unittest.main()
