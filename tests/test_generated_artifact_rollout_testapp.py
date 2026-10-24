"""testapp#32 independent scratch-target admission; offline, no GitHub writes."""
import base64
import json
import pathlib
import tempfile
import unittest

from tools import generated_artifact_rollout as rollout
from tools import generated_artifact_rollout_admission as auth
from tools.generated_artifact_contract import ArtifactRejected

REPO = "kinoko34077/testapp"
RECIPE = "testapp-public-fixture-v1"
CALLER_SHA = "a" * 40
DEVFLOW_SHA = "b" * 40
TARGET = "artifact/writeback-testapp/e2e-20261012"
PATH = "data/writeback-e2e/generated.json"


def env(**changes):
    result = {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_ACTOR": "kinoko34077",
        "GITHUB_ACTOR_ID": "79015263",
        "GITHUB_TRIGGERING_ACTOR": "kinoko34077",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{REPO}/{rollout.CALLER_PATH}@refs/heads/main",
        "GITHUB_WORKFLOW_SHA": CALLER_SHA,
        "GITHUB_RUN_ID": "812",
        "GITHUB_RUN_ATTEMPT": "1",
        "MODE": "dry-run",
    }
    result.update(changes)
    return result


class TestappReader:
    repository = REPO
    def __init__(self, *, caller=None, run_change=None):
        self.calls = []
        self.run = {
            "id": 812, "run_attempt": 1, "event": "workflow_dispatch",
            "status": "in_progress", "head_sha": CALLER_SHA,
            "head_branch": "main", "path": rollout.CALLER_PATH,
            "actor": {"id": 79015263, "login": "kinoko34077"},
            "triggering_actor": {"id": 79015263, "login": "kinoko34077"},
            "repository": {"full_name": REPO}, "workflow_id": 34,
        }
        self.run.update(run_change or {})
        template = auth._TEMPLATES[REPO].read_text("utf-8")
        self.caller = auth.exact_caller_text(template, DEVFLOW_SHA) if caller is None else caller

    def get(self, path):
        self.calls.append(path)
        if path == "/actions/runs/812":
            return self.run
        if path == "/actions/workflows/34":
            return {"id": 34, "path": rollout.CALLER_PATH}
        if path == f"/contents/{rollout.CALLER_PATH}?ref={CALLER_SHA}":
            return {
                "type": "file", "encoding": "base64",
                "path": rollout.CALLER_PATH,
                "content": base64.b64encode(self.caller.encode()).decode(),
            }
        raise AssertionError("unexpected test API read")


def attest(api=None, context=None, **overrides):
    values = {
        "repository": REPO, "recipe_id": RECIPE,
        "target_branch": TARGET, "expected_head": DEVFLOW_SHA,
        "source_head": DEVFLOW_SHA, "devflow_sha": DEVFLOW_SHA,
        "devflow_checkout_sha": DEVFLOW_SHA,
    }
    values.update(overrides)
    return auth.attest_authenticated_readonly(
        api or TestappReader(), context or env(), **values,
    )


class TestappStaticAdmissionTests(unittest.TestCase):
    def test_testapp_recipe_and_provenance_are_separate_from_ids(self):
        r = rollout.select_fixed_recipe(REPO, RECIPE)
        self.assertEqual(r.outputs, (PATH,))
        self.assertEqual(r.node_version, "26.10.0")
        self.assertEqual(r.generate_npm_script, "generate:writeback-e2e")
        self.assertEqual(r.verify_npm_script, "verify:writeback-e2e")
        p = rollout.fixed_policy(REPO, RECIPE, CALLER_SHA)
        self.assertEqual(p["limits"]["max_total_bytes"], 64 * 1024)
        self.assertNotEqual(p["branch_prefix"], rollout.fixed_policy(
            "kinoko34077/IDS-Composit", "ids-known-merge-v0.2", CALLER_SHA,
        )["branch_prefix"])

    def test_independent_testapp_rest_admits_only_correct_static_template(self):
        api = TestappReader()
        result = attest(api=api)
        self.assertEqual(result["status"], "AUTHENTICATED_READ_ONLY")
        self.assertFalse(result["writer_authorized"])
        self.assertEqual(result["policy"]["repository"], REPO)
        self.assertEqual(result["admission"]["branch"], TARGET)
        self.assertEqual(len(api.calls), 3)

    def test_cross_repository_policy_caller_and_recipe_rejections(self):
        for changed in (
            {"repository": "kinoko34077/IDS-Composit"},
            {"recipe_id": "ids-known-merge-v0.2"},
            {"target_branch": "artifact/writeback-ids/fixture"},
            {"target_branch": "main"},
        ):
            with self.subTest(change=changed), self.assertRaises(ArtifactRejected):
                attest(**changed)
        ids_template = auth.TEMPLATE.read_text("utf-8")
        forged = auth.exact_caller_text(ids_template, DEVFLOW_SHA)
        with self.assertRaises(ArtifactRejected):
            attest(api=TestappReader(caller=forged))
        with self.assertRaises(ArtifactRejected):
            attest(context=env(GITHUB_REPOSITORY="kinoko34077/IDS-Composit"))
        with self.assertRaises(ArtifactRejected):
            attest(api=TestappReader(run_change={"repository": {"full_name": "other/repo"}}))

    def test_rest_rerun_actor_missing_or_forged_rejected(self):
        with self.assertRaises(ArtifactRejected):
            attest(api=TestappReader(run_change={"triggering_actor": None}))
        with self.assertRaises(ArtifactRejected):
            attest(api=TestappReader(run_change={"triggering_actor": {"login": "other"}}))

    def test_static_low_trust_one_output_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "source"
            file = source / PATH
            file.parent.mkdir(parents=True)
            file.write_bytes(b'{"fixture":"testapp"}\n')
            out = pathlib.Path(tmp) / "out"
            values = {
                "target_branch": TARGET, "expected_head": DEVFLOW_SHA,
                "source_head": DEVFLOW_SHA, "devflow_sha": DEVFLOW_SHA,
                "devflow_checkout_sha": DEVFLOW_SHA,
            }
            result = rollout.package_from_fixed_source(
                REPO, RECIPE, env(), source, out, **values,
            )
            self.assertEqual(result["status"], "PRODUCED_LOW_TRUST")
            self.assertFalse(result["writer_authorized"])
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual([x["path"] for x in manifest["files"]], [PATH])
            self.assertEqual(manifest["provenance"]["repository"], REPO)
            self.assertGreater((out / "artifact.zip").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
