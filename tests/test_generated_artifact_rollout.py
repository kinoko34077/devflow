"""Offline fail-closed tests of the bounded devflow#465 producer prototype."""
import json
import pathlib
import tempfile
import unittest
import zipfile

from tools import generated_artifact_rollout as rollout
from tools.generated_artifact_contract import ArtifactRejected, validate_and_plan

REPO = "kinoko34077/IDS-Composit"
RECIPE = "ids-known-merge-v0.2"
SHA = "a" * 40
CALLER_SHA = "b" * 40
BRANCH = "artifact/writeback-ids/pilot-1"


def runner(**updates):
    result = {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_ACTOR": "kinoko34077",
        "GITHUB_ACTOR_ID": "79015263",
        "GITHUB_TRIGGERING_ACTOR": "kinoko34077",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{REPO}/{rollout.CALLER_PATH}@refs/heads/main",
        "GITHUB_WORKFLOW_SHA": CALLER_SHA,
        "GITHUB_RUN_ID": "501",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    result.update(updates)
    return result


def params(**updates):
    result = {
        "target_branch": BRANCH,
        "expected_head": SHA,
        "source_head": SHA,
        "devflow_sha": SHA,
        "devflow_checkout_sha": SHA,
    }
    result.update(updates)
    return result


class FixedRegistryTests(unittest.TestCase):
    def test_exact_recipe_and_commands_without_freeform_shell(self):
        recipe = rollout.select_fixed_recipe(REPO, RECIPE)
        self.assertEqual(recipe.outputs, (
            "data/known/generated/known-index-v0.2.json",
            "data/known/reports/known-index-v0.2.json",
        ))
        self.assertEqual(rollout.fixed_commands(REPO, RECIPE), {
            "node_version": "22",
            "generate_npm_script": "known:merge",
            "verify_npm_script": "known:check:merge",
            "output_paths": list(recipe.outputs),
        })

    def test_unknown_repo_recipe_or_type_is_rejected(self):
        for repo, recipe in (
            ("kinoko34077/japanese-orthography", RECIPE),
            ("kinoko34077/kinotch-api", RECIPE),
            (REPO, "unknown"), (REPO, "ids-known-merge-v0.2;echo bad"),
            (None, RECIPE), (REPO, None),
        ):
            with self.subTest(repo=repo, recipe=recipe), self.assertRaises(ArtifactRejected):
                rollout.fixed_commands(repo, recipe)

    def test_policy_is_nonprivileged_static_2path_and_bounded(self):
        p = rollout.fixed_policy(REPO, RECIPE, CALLER_SHA)
        self.assertEqual(p["repository"], REPO)
        self.assertEqual(p["allowed_actors"], ["kinoko34077"])
        self.assertEqual(p["recipe"]["version"], "1")
        self.assertEqual(len(p["recipe"]["paths"]), 2)
        self.assertEqual(p["branch_prefix"], "artifact/writeback-ids/")
        self.assertEqual(p["limits"]["max_total_bytes"], 32 * 1024 * 1024)
        self.assertEqual(p["producer_workflow_ref"], f"{REPO}/{rollout.CALLER_PATH}@{CALLER_SHA}")

    def test_sha_is_exact_reviewable_commit_not_branch(self):
        for sha in ("main", "A" * 40, "a" * 39, "z" * 40, ""):
            with self.subTest(sha=sha), self.assertRaises(ArtifactRejected):
                rollout.fixed_policy(REPO, RECIPE, sha)


class ProducerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.policy = rollout.fixed_policy(REPO, RECIPE, CALLER_SHA)

    def admission(self, context=None, **overrides):
        return rollout.producer_admission(self.policy, context or runner(), **params(**overrides))

    def test_valid_low_trust_provenance(self):
        value = self.admission()
        self.assertEqual(value["recipe_id"], RECIPE)
        self.assertEqual(value["branch"], BRANCH)
        self.assertEqual(value["producer_run_id"], 501)

    def test_rejects_forged_runner_event_actor_ref_path_and_run(self):
        cases = [
            {"GITHUB_REPOSITORY": "kinoko34077/kinotch-api"},
            {"GITHUB_EVENT_NAME": "pull_request"},
            {"GITHUB_EVENT_NAME": "issue_comment"},
            {"GITHUB_ACTOR": "attacker"},
            {"GITHUB_TRIGGERING_ACTOR": "attacker"},
            {"GITHUB_REF": "refs/heads/artifact/writeback-ids/test"},
            {"GITHUB_WORKFLOW_REF": f"{REPO}/.github/workflows/untrusted.yml@refs/heads/main"},
            {"GITHUB_WORKFLOW_SHA": "c" * 40},
            {"GITHUB_RUN_ID": "0"},
            {"GITHUB_RUN_ATTEMPT": "01"},
        ]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ArtifactRejected):
                self.admission(runner(**change))

    def test_branch_head_and_helper_pin_fail_closed(self):
        variants = [
            {"target_branch": "main"},
            {"target_branch": "artifact/writeback-ids/../test"},
            {"target_branch": "artifact/writeback-ids/"},
            {"target_branch": "artifact/writeback-ids/fork/branch"},
            {"target_branch": "artifact/devflow384/test"},
            {"expected_head": "c" * 40},
            {"devflow_checkout_sha": "d" * 40},
            {"source_head": "refs/heads/main"},
        ]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ArtifactRejected):
                self.admission(**change)

    def test_mutated_policy_cannot_authorize_any_extra_path_or_limit(self):
        from copy import deepcopy
        policy = deepcopy(self.policy)
        policy["recipe"]["paths"].append("unexpected.json")
        with self.assertRaises(ArtifactRejected):
            rollout.producer_admission(policy, runner(), **params())


class PackagingTests(unittest.TestCase):
    def write_source(self, root):
        source = pathlib.Path(root) / "source"
        for index, path in enumerate(rollout.select_fixed_recipe(REPO, RECIPE).outputs):
            target = source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(("{\"index\":" + str(index) + "}\n").encode())
        return source

    def test_two_path_manifest_package_and_v1_planner_dryrun(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write_source(tmp)
            out = pathlib.Path(tmp) / "out"
            result = rollout.package_from_fixed_source(
                REPO, RECIPE, runner(), source, out, **params(),
            )
            self.assertEqual(result["status"], "PRODUCED_LOW_TRUST")
            self.assertIs(result["writer_authorized"], False)
            manifest = json.loads((out / "manifest.json").read_text())
            archive = (out / "artifact.zip").read_bytes()
            self.assertEqual(len(manifest["files"]), 2)
            with zipfile.ZipFile(out / "artifact.zip") as zipf:
                self.assertEqual(set(zipf.namelist()), set(rollout.select_fixed_recipe(REPO, RECIPE).outputs))
            p = rollout.fixed_policy(REPO, RECIPE, CALLER_SHA)
            a = rollout.producer_admission(p, runner(), **params())
            plan = validate_and_plan(
                p, a, manifest, archive, observed_head=SHA,
                existing_files={path: None for path in p["recipe"]["paths"]},
            )
            self.assertEqual(len(plan["changes"]), 2)

    def test_no_source_writes_and_destination_must_be_outside_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write_source(tmp)
            before = {name: (source / name).read_bytes() for name in rollout.select_fixed_recipe(REPO, RECIPE).outputs}
            with self.assertRaises(ArtifactRejected):
                rollout.package_from_fixed_source(
                    REPO, RECIPE, runner(), source, source / "out", **params(),
                )
            out = pathlib.Path(tmp) / "outputs"
            rollout.package_from_fixed_source(REPO, RECIPE, runner(), source, out, **params())
            after = {name: (source / name).read_bytes() for name in before}
            self.assertEqual(before, after)

    def test_missing_extra_symlink_and_executable_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.write_source(tmp)
            out = pathlib.Path(tmp) / "out"
            paths = rollout.select_fixed_recipe(REPO, RECIPE).outputs
            (source / paths[0]).unlink()
            with self.assertRaises((ArtifactRejected, OSError)):
                rollout.package_from_fixed_source(REPO, RECIPE, runner(), source, out, **params())
            (source / paths[0]).symlink_to(source / paths[1])
            with self.assertRaises(ArtifactRejected):
                rollout.package_from_fixed_source(REPO, RECIPE, runner(), source, out, **params())
            (source / paths[0]).unlink()
            (source / paths[0]).write_text("{}")
            (source / paths[0]).chmod(0o755)
            with self.assertRaises(ArtifactRejected):
                rollout.package_from_fixed_source(REPO, RECIPE, runner(), source, out, **params())

    def test_path_traversal_override_is_not_an_input(self):
        with self.assertRaises(TypeError):
            rollout.package_from_fixed_source(REPO, RECIPE, runner(), pathlib.Path("."), pathlib.Path(".."), output_paths=["../../secrets"])
        with self.assertRaises(ArtifactRejected):
            rollout.package_from_fixed_source(
                REPO, "other", runner(), pathlib.Path("."), pathlib.Path("out"), **params(),
            )


if __name__ == "__main__":
    unittest.main()
