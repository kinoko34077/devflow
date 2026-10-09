"""devflow#384 S3.3 Pilot entrypoint + reusable-workflow structure tests (offline)."""
import base64
import hashlib
import io
import json
import pathlib
import re
import tempfile
import unittest
import zipfile

from tools import generated_artifact_pilot as pilot
from tools.generated_artifact_contract import ArtifactRejected

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/generated-artifact-writeback.yml"
TEMPLATE = ROOT / "docs/operations/templates/verified-artifacts-pilot.yml"
DEVFLOW_SHA = "1" * 40
WORKFLOW_SHA = "2" * 40
HEAD = "3" * 40
RUN_ID = 4242
OUT = pilot.OUTPUTS[0]


def caller_text(sha=DEVFLOW_SHA):
    return TEMPLATE.read_text(encoding="utf-8").replace("<DEVFLOW_SHA>", sha)


def env(**overrides):
    base = {
        "DEVFLOW_SHA": DEVFLOW_SHA,
        "DEVFLOW_CHECKOUT_SHA": DEVFLOW_SHA,
        "EXPECTED_HEAD": HEAD,
        "TARGET_BRANCH": "artifact/devflow384/pilot-1",
        "MODE": "dry-run",
        "SOURCE_HEAD": HEAD,
        "GITHUB_REPOSITORY": pilot.REPO,
        "GITHUB_ACTOR": "kinoko34077",
        "GITHUB_TRIGGERING_ACTOR": "kinoko34077",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{pilot.REPO}/{pilot.CALLER_PATH}@refs/heads/main",
        "GITHUB_WORKFLOW_SHA": WORKFLOW_SHA,
        "GITHUB_RUN_ID": str(RUN_ID),
        "GITHUB_RUN_ATTEMPT": "1",
        "WRITER_TOKEN": "unused-in-tests",
    }
    base.update(overrides)
    return base


class FakeApi:
    """Records reads; delegates the write core to a stub to isolate the entrypoint."""

    repository = pilot.REPO

    def __init__(self, caller=None, run_overrides=None):
        self.caller = caller_text() if caller is None else caller
        self.run = {
            "id": RUN_ID, "run_attempt": 1, "event": "workflow_dispatch",
            "status": "in_progress", "head_sha": WORKFLOW_SHA, "head_branch": "main",
            "path": pilot.CALLER_PATH, "actor": {"login": "kinoko34077"},
            "repository": {"full_name": pilot.REPO}, "workflow_id": 77,
        }
        self.run.update(run_overrides or {})
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path == f"/actions/runs/{RUN_ID}":
            return dict(self.run)
        if path == "/actions/workflows/77":
            return {"id": 77, "path": pilot.CALLER_PATH}
        if path == f"/contents/{pilot.CALLER_PATH}?ref={WORKFLOW_SHA}":
            return {"type": "file", "encoding": "base64", "path": pilot.CALLER_PATH,
                    "content": base64.b64encode(self.caller.encode()).decode()}
        raise AssertionError("unexpected read " + path)


def produce_artifact(tmp, payload=b'{"ok":true}\n', **env_overrides):
    source = pathlib.Path(tmp) / "source"
    (source / pathlib.Path(OUT).parent).mkdir(parents=True)
    (source / OUT).write_bytes(payload)
    out = pathlib.Path(tmp) / "out"
    pilot.produce(env(**env_overrides), source, out)
    return out


class PilotPolicyTests(unittest.TestCase):
    def test_policy_is_fixed_single_repo_single_path(self):
        policy = pilot.pilot_policy(WORKFLOW_SHA)
        self.assertEqual(policy["repository"], "kinoko34077/japanese-orthography")
        self.assertEqual(policy["recipe"]["paths"], [OUT])
        self.assertEqual(policy["branch_prefix"], "artifact/devflow384/")
        self.assertIn("migration/tar-pattern-291", policy["forbidden_branches"])
        self.assertEqual(policy["limits"]["max_files"], 1)

    def test_policy_rejects_non_sha_workflow(self):
        for bad in ("main", "refs/heads/main", "2" * 39, "G" * 40):
            with self.assertRaises(ArtifactRejected):
                pilot.pilot_policy(bad)

    def test_recipe_script_is_fixed(self):
        self.assertEqual(pilot.RECIPE_NPM_SCRIPT, "generate:orthography-accounting")


class CallerContentTests(unittest.TestCase):
    def test_template_with_matching_pins_is_accepted(self):
        pilot.verify_caller_content(caller_text(), DEVFLOW_SHA)

    def test_pin_mismatch_rejected(self):
        with self.assertRaises(ArtifactRejected):
            pilot.verify_caller_content(caller_text(), "9" * 40)
        mixed = caller_text().replace(f"devflow_sha: {DEVFLOW_SHA}", "devflow_sha: " + "9" * 40)
        with self.assertRaises(ArtifactRejected):
            pilot.verify_caller_content(mixed, DEVFLOW_SHA)

    def test_branch_or_tag_pin_rejected(self):
        with self.assertRaises(ArtifactRejected):
            pilot.verify_caller_content(caller_text("main"), "main")

    def test_forbidden_triggers_secrets_and_commands_rejected(self):
        text = caller_text()
        variants = [
            text.replace("  workflow_dispatch:", "  pull_request_target:\n  workflow_dispatch:"),
            text.replace("  workflow_dispatch:", "  push:\n  workflow_dispatch:"),
            text.replace("    with:", "    secrets: inherit\n    with:"),
            text + "\n  extra:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
            text + "\n      - uses: actions/checkout@v7\n",
            text.replace("workflow_dispatch:", "workflow_dispatchx:"),
        ]
        for variant in variants:
            with self.subTest(variant=variant[-60:]):
                with self.assertRaises(ArtifactRejected):
                    pilot.verify_caller_content(variant, DEVFLOW_SHA)


class ProduceTests(unittest.TestCase):
    def test_produce_emits_manifest_bound_to_runner_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = produce_artifact(tmp)
            manifest = json.loads((out / pilot.MANIFEST_NAME).read_text())
            prov = manifest["provenance"]
            self.assertEqual(prov["producer_workflow_ref"], f"{pilot.REPO}/{pilot.CALLER_PATH}@{WORKFLOW_SHA}")
            self.assertEqual(prov["expected_head"], HEAD)
            self.assertEqual(prov["producer_run_id"], RUN_ID)
            with zipfile.ZipFile(out / pilot.ARCHIVE_NAME) as archive:
                self.assertEqual(archive.namelist(), [OUT])

    def test_produce_rejects_source_head_mismatch_and_bad_inputs(self):
        cases = [
            {"SOURCE_HEAD": "4" * 40},
            {"DEVFLOW_CHECKOUT_SHA": "5" * 40},
            {"TARGET_BRANCH": "main"},
            {"TARGET_BRANCH": "artifact/devflow384/"},
            {"MODE": "force"},
            {"EXPECTED_HEAD": "abc"},
        ]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ArtifactRejected):
                    produce_artifact(tmp, **case)


class WriteEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.captured = {}
        self._orig = pilot.verified_writeback

        def fake_writeback(api, policy, admission, manifest, archive, *, dry_run):
            self.captured.update(policy=policy, admission=admission, manifest=manifest,
                                 archive=archive, dry_run=dry_run)
            return {"status": "DRY_RUN" if dry_run else "COMMITTED"}

        pilot.verified_writeback = fake_writeback

    def tearDown(self):
        pilot.verified_writeback = self._orig

    def run_write(self, api=None, **env_overrides):
        with tempfile.TemporaryDirectory() as tmp:
            out = produce_artifact(tmp)
            return pilot.write(env(**env_overrides), out, api=api or FakeApi())

    def test_authenticated_dry_run_reaches_core_with_derived_admission(self):
        result = self.run_write()
        self.assertEqual(result["status"], "DRY_RUN")
        self.assertTrue(self.captured["dry_run"])
        self.assertEqual(self.captured["admission"]["producer_run_id"], RUN_ID)
        self.assertEqual(self.captured["policy"]["producer_workflow_ref"],
                         f"{pilot.REPO}/{pilot.CALLER_PATH}@{WORKFLOW_SHA}")

    def test_write_mode_is_only_from_explicit_input(self):
        self.run_write(MODE="write")
        self.assertFalse(self.captured["dry_run"])

    def test_untrusted_runner_or_run_metadata_rejected_before_core(self):
        cases = [
            ({}, {"GITHUB_ACTOR": "someone-else", "GITHUB_TRIGGERING_ACTOR": "someone-else"}),
            ({}, {"GITHUB_TRIGGERING_ACTOR": "someone-else"}),
            ({}, {"GITHUB_EVENT_NAME": "pull_request"}),
            ({}, {"GITHUB_REF": "refs/heads/artifact/devflow384/pilot-1"}),
            ({}, {"GITHUB_REPOSITORY": "kinoko34077/devflow"}),
            ({"head_sha": "9" * 40}, {}),
            ({"status": "completed"}, {}),
            ({"actor": {"login": "someone-else"}}, {}),
        ]
        for run_overrides, env_overrides in cases:
            with self.subTest(run=run_overrides, env=env_overrides):
                self.captured.clear()
                with self.assertRaises(ArtifactRejected):
                    self.run_write(api=FakeApi(run_overrides=run_overrides), **env_overrides)
                self.assertEqual(self.captured, {})

    def test_caller_content_mismatch_rejected_before_core(self):
        api = FakeApi(caller=caller_text("9" * 40))
        with self.assertRaises(ArtifactRejected):
            self.run_write(api=api)
        self.assertEqual(self.captured, {})

    def test_devflow_checkout_mismatch_rejected_before_any_read(self):
        api = FakeApi()
        with self.assertRaises(ArtifactRejected):
            self.run_write(api=api, DEVFLOW_CHECKOUT_SHA="7" * 40)
        self.assertEqual(api.paths, [])

    def test_symlinked_or_oversized_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = produce_artifact(tmp)
            target = out / pilot.ARCHIVE_NAME
            real = pathlib.Path(tmp) / "real.zip"
            target.rename(real)
            target.symlink_to(real)
            with self.assertRaises(ArtifactRejected):
                pilot.write(env(), out, api=FakeApi())
        with tempfile.TemporaryDirectory() as tmp:
            out = produce_artifact(tmp)
            (out / pilot.MANIFEST_NAME).write_bytes(b"x" * (64 * 1024 + 1))
            with self.assertRaises(ArtifactRejected):
                pilot.write(env(), out, api=FakeApi())


class ReusableWorkflowStructureTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        produce, write = self.text.split("\n  write:\n", 1)
        self.produce = produce.split("\n  produce:\n", 1)[1]
        self.write = write

    def test_only_workflow_call_and_empty_top_level_permissions(self):
        on_block = self.text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_call:", on_block)
        for forbidden in ("pull_request", "push:", "workflow_dispatch", "schedule", "workflow_run"):
            self.assertNotIn(forbidden, on_block)
        self.assertIn("\npermissions: {}\n", self.text)

    def test_job_permissions_are_separated(self):
        produce_perms = self.produce.split("permissions:", 1)[1].split("env:", 1)[0]
        self.assertIn("contents: read", produce_perms)
        self.assertNotIn("write", produce_perms)
        write_perms = self.write.split("permissions:", 1)[1].split("env:", 1)[0]
        self.assertIn("contents: write", write_perms)
        for line in write_perms.strip().splitlines():
            key, value = [part.strip() for part in line.split(":", 1)]
            if key != "contents":
                self.assertEqual(value, "read", line)

    def test_writer_job_never_executes_target_code(self):
        for forbidden in ("npm", "node", "actions/checkout", "setup-node", "pip install", "source"):
            self.assertNotIn(forbidden, self.write, forbidden)
        self.assertIn("generated_artifact_pilot import main", self.write)
        self.assertIn("python3 -I", self.write)

    def test_generate_canonical_validation_and_full_checks_precede_archive(self):
        # The source's check scripts are untrusted; only the read-only job
        # executes them. If any exit nonzero, shell -e stops before upload.
        recipe_pos = self.produce.index('npm run "$script"')
        accounting_pos = self.produce.index('npm run validate:orthography-accounting')
        full_pos = self.produce.index('npm run check')
        package_pos = self.produce.index('python3 -m tools.generated_artifact_pilot produce')
        upload_pos = self.produce.index('actions/upload-artifact@')
        self.assertLess(recipe_pos, accounting_pos)
        self.assertLess(accounting_pos, full_pos)
        self.assertLess(full_pos, package_pos)
        self.assertLess(package_pos, upload_pos)
        validation = self.produce.split(
            '- name: Validate generated accounting and full source checks (read-only)', 1
        )[1].split('- name: Package approved outputs (low-trust data)', 1)[0]
        self.assertIn('set -euo pipefail', validation)
        self.assertIn('working-directory: source', validation)
        self.assertIn('needs: produce', self.write)

    def test_no_unreviewed_source_commands_after_validation_in_write(self):
        self.assertNotIn('npm run check', self.write)
        self.assertNotIn('npm run validate:orthography-accounting', self.write)

    def test_token_only_in_writer_and_no_secrets(self):
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("github.token", self.produce)
        self.assertEqual(self.text.count("github.token"), 1)
        self.assertIn("persist-credentials: false", self.produce)

    def test_actions_are_pinned_to_full_shas(self):
        uses = re.findall(r"(?m)^\s*(?:- )?uses:\s*(\S+)", self.text)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")

    def test_inputs_are_not_interpolated_into_shell(self):
        for block in re.findall(r"run: \|\n((?:          .*\n?)+)", self.text):
            self.assertNotIn("${{", block)

    def test_devflow_helpers_fetched_at_pinned_sha_without_credentials(self):
        for job in (self.produce, self.write):
            self.assertIn('fetch -q --depth 1 https://github.com/kinoko34077/devflow.git "$DEVFLOW_SHA"', job)
            self.assertIn('test "$(git -C devflow rev-parse HEAD)" = "$DEVFLOW_SHA"', job)


if __name__ == "__main__":
    unittest.main()
