"""devflow#1050: fixed admission for the private Bootstrap writer E2E."""
import pathlib
import unittest

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import (
    fixed_commands, fixed_policy, producer_admission, select_fixed_recipe,
)
from tools import generated_artifact_rollout_admission as rollout_admission
from tools.generated_artifact_rollout_admission import (
    attest_authenticated_readonly, exact_caller_text,
)
from tools import generated_artifact_rollout_testapp_write as testapp_writer


REPOSITORY = "kinoko34077/devflow-writeback-bootstrap-e2e-20261118"
RECIPE = "bootstrap-writeback-e2e-v1"
CALLER_SHA = "b" * 40


class BootstrapE2ERecipeTests(unittest.TestCase):
    def test_exact_repo_recipe_has_one_fixed_small_output_and_commands(self):
        recipe = select_fixed_recipe(REPOSITORY, RECIPE)
        self.assertEqual(recipe.branch_prefix, "artifact/writeback-bootstrap-e2e/")
        self.assertEqual(recipe.outputs, ("data/writeback-e2e/generated.json",))
        self.assertEqual(fixed_commands(REPOSITORY, RECIPE), {
            "node_version": "22",
            "generate_npm_script": "generate:writeback-e2e",
            "verify_npm_script": "verify:writeback-e2e",
            "output_paths": ["data/writeback-e2e/generated.json"],
        })
        policy = fixed_policy(REPOSITORY, RECIPE, CALLER_SHA)
        self.assertEqual(policy["repository"], REPOSITORY)
        self.assertEqual(policy["recipe"]["paths"], ["data/writeback-e2e/generated.json"])
        self.assertEqual(policy["limits"]["max_file_bytes"], 64 * 1024)
        self.assertEqual(policy["limits"]["max_total_bytes"], 64 * 1024)

    def test_repo_and_recipe_pair_is_not_a_caller_controlled_extension(self):
        for repository, recipe in (
            ("kinoko34077/testapp", RECIPE),
            (REPOSITORY, "testapp-public-fixture-v1"),
            (REPOSITORY, "bootstrap-writeback-e2e-v1;echo bad"),
            ("attacker/devflow-writeback-bootstrap-e2e-20261118", RECIPE),
        ):
            with self.subTest(repository=repository, recipe=recipe), self.assertRaises(ArtifactRejected):
                select_fixed_recipe(repository, recipe)

    def test_private_e2e_caller_path_is_pinned_as_recipe_data(self):
        recipe = select_fixed_recipe(REPOSITORY, RECIPE)
        caller_path = getattr(recipe, "caller_path", None)
        self.assertEqual(caller_path, ".github/workflows/bootstrap-writeback-e2e.yml")
        policy = fixed_policy(REPOSITORY, RECIPE, CALLER_SHA)
        self.assertEqual(
            policy["producer_workflow_ref"],
            f"{REPOSITORY}/{caller_path}@{CALLER_SHA}",
        )
        runner = {
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_ACTOR": "kinoko34077",
            "GITHUB_ACTOR_ID": "79015263",
            "GITHUB_TRIGGERING_ACTOR": "kinoko34077",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{caller_path}@refs/heads/main",
            "GITHUB_WORKFLOW_SHA": CALLER_SHA,
            "GITHUB_RUN_ID": "501",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        admission = producer_admission(
            policy, runner, target_branch="artifact/writeback-bootstrap-e2e/pilot-1",
            expected_head=CALLER_SHA, source_head=CALLER_SHA,
            devflow_sha=CALLER_SHA, devflow_checkout_sha=CALLER_SHA,
        )
        self.assertEqual(admission["recipe_id"], RECIPE)

    def test_e2e_caller_template_is_exact_repo_scoped_and_writer_only(self):
        self.assertIn(REPOSITORY, rollout_admission._TEMPLATES)
        path = rollout_admission._TEMPLATES[REPOSITORY]
        self.assertEqual(path.name, "verified-artifacts-rollout-bootstrap-e2e.yml")
        template = path.read_text("utf-8")
        self.assertEqual(template.count("<DEVFLOW_SHA>"), 2)
        self.assertIn("github.repository == '" + REPOSITORY + "'", template)
        self.assertIn("recipe_id: bootstrap-writeback-e2e-v1", template)
        self.assertIn("mode: write", template)
        self.assertIn("contents: write", template)
        self.assertNotIn("inputs.recipe_id", template)

        pinned = exact_caller_text(template, CALLER_SHA)
        self.assertEqual(pinned.count(CALLER_SHA), 2)
        self.assertNotIn("<DEVFLOW_SHA>", pinned)

    def test_independent_attestation_reads_the_recipe_specific_caller_path(self):
        recipe = select_fixed_recipe(REPOSITORY, RECIPE)
        template = rollout_admission._TEMPLATES[REPOSITORY].read_text("utf-8")
        caller = exact_caller_text(template, CALLER_SHA)

        class Reader:
            repository = REPOSITORY

            def __init__(self):
                self.calls = []
                self.run = {
                    "id": 501, "run_attempt": 1, "event": "workflow_dispatch",
                    "status": "in_progress", "head_sha": CALLER_SHA,
                    "head_branch": "main", "path": recipe.caller_path,
                    "actor": {"id": 79015263, "login": "kinoko34077"},
                    "triggering_actor": {"id": 79015263, "login": "kinoko34077"},
                    "repository": {"full_name": REPOSITORY}, "workflow_id": 61,
                }

            def get(self, path):
                self.calls.append(path)
                if path == "/actions/runs/501":
                    return self.run
                if path == "/actions/workflows/61":
                    return {"id": 61, "path": recipe.caller_path}
                if path == f"/contents/{recipe.caller_path}?ref={CALLER_SHA}":
                    import base64
                    return {
                        "type": "file", "encoding": "base64",
                        "path": recipe.caller_path,
                        "content": base64.b64encode(caller.encode()).decode(),
                    }
                raise AssertionError("unexpected E2E admission read: " + path)

        reader = Reader()
        result = attest_authenticated_readonly(
            reader,
            {
                "GITHUB_REPOSITORY": REPOSITORY,
                "GITHUB_ACTOR": "kinoko34077",
                "GITHUB_ACTOR_ID": "79015263",
                "GITHUB_TRIGGERING_ACTOR": "kinoko34077",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{recipe.caller_path}@refs/heads/main",
                "GITHUB_WORKFLOW_SHA": CALLER_SHA,
                "GITHUB_RUN_ID": "501",
                "GITHUB_RUN_ATTEMPT": "1",
                "MODE": "write",
            },
            repository=REPOSITORY, recipe_id=RECIPE,
            target_branch="artifact/writeback-bootstrap-e2e/pilot-1",
            expected_head=CALLER_SHA, source_head=CALLER_SHA,
            devflow_sha=CALLER_SHA, devflow_checkout_sha=CALLER_SHA,
        )
        self.assertEqual(result["status"], "AUTHENTICATED_READ_ONLY")
        self.assertFalse(result["writer_authorized"])
        self.assertIn(f"/contents/{recipe.caller_path}?ref={CALLER_SHA}", reader.calls)

    def test_shared_writer_job_allows_only_the_two_fixed_repo_recipe_pairs(self):
        from pathlib import Path
        workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/generated-artifact-rollout.yml"
        workflow = workflow_path.read_text("utf-8")
        _, writer = workflow.split("\n  write:\n", 1)
        self.assertIn("github.repository == '" + REPOSITORY + "'", writer)
        self.assertIn("inputs.recipe_id == 'bootstrap-writeback-e2e-v1'", writer)
        self.assertIn("tools.generated_artifact_rollout_bootstrap_e2e_write", writer)
        self.assertIn("MODE: dry-run", workflow.split("\n  verify:\n", 1)[1].split("\n  write:\n", 1)[0])

    def test_bootstrap_and_testapp_wrappers_share_the_registered_bounded_adapter(self):
        shared = getattr(testapp_writer, "NarrowRegisteredWriteApi", None)
        self.assertIsNotNone(shared, "testapp adapter should reuse the shared narrow API")
        from tools import generated_artifact_rollout_bootstrap_e2e_write as bootstrap_writer

        self.assertTrue(issubclass(testapp_writer.NarrowTestappWriteApi, shared))
        self.assertTrue(issubclass(bootstrap_writer.NarrowBootstrapE2EWriteApi, shared))

        class Transport:
            repository = REPOSITORY

            def __init__(self):
                self.calls = []

            def get(self, path):
                self.calls.append(("GET", path))
                return {}

            def post(self, path, payload):
                self.calls.append(("POST", path))
                return {"sha": "1" * 40}

            def patch(self, path, payload):
                self.calls.append(("PATCH", path))
                return {"ref": "heads/test"}

        branch = "artifact/writeback-bootstrap-e2e/pilot-1"
        transport = Transport()
        api = bootstrap_writer.NarrowBootstrapE2EWriteApi(transport, branch)
        for path in ("/git/blobs", "/git/trees", "/git/commits"):
            api.post(path, {})
        api.patch("/git/refs/heads/" + branch, {"sha": "2" * 40, "force": False})
        self.assertEqual(len(transport.calls), 4)
        for path in ("/git/refs", "/git/refs/heads/main", "/actions/workflows/1/dispatches"):
            with self.subTest(path=path), self.assertRaises(ArtifactRejected):
                api.post(path, {})
        for invalid in ("main", "artifact/writeback-testapp/x", "artifact/writeback-bootstrap-e2e/../main"):
            with self.subTest(branch=invalid), self.assertRaises(ArtifactRejected):
                bootstrap_writer.NarrowBootstrapE2EWriteApi(transport, invalid)

    def test_bootstrap_writer_rejects_other_repository_or_nonwrite_job_before_api_reads(self):
        from tools import generated_artifact_rollout_bootstrap_e2e_write as bootstrap_writer

        class ObserveOnly:
            repository = REPOSITORY

            def __init__(self):
                self.calls = []

            def get(self, path):
                self.calls.append(path)
                return {}

        api = ObserveOnly()
        branch = "artifact/writeback-bootstrap-e2e/pilot-1"
        for env in (
            {"GITHUB_REPOSITORY": REPOSITORY, "MODE": "dry-run", "GITHUB_EVENT_NAME": "workflow_dispatch"},
            {"GITHUB_REPOSITORY": "kinoko34077/testapp", "MODE": "write", "GITHUB_EVENT_NAME": "workflow_dispatch"},
            {"GITHUB_REPOSITORY": REPOSITORY, "MODE": "write", "GITHUB_EVENT_NAME": "pull_request"},
        ):
            with self.subTest(env=env), self.assertRaises(ArtifactRejected):
                bootstrap_writer.execute_bootstrap_e2e_scoped_write(
                    api, env, pathlib.Path("unused"),
                    target_branch=branch, expected_head="a" * 40,
                    devflow_sha="b" * 40, devflow_checkout_sha="b" * 40,
                )
            self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
