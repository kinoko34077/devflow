"""No-network contract tests for guarded local MCP release selection (#1111)."""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import devflow_mcp_release_manager as manager
from tools.devflow_mcp_catalog import publication_schema
from tools import devflow_mcp_stable_launcher as launcher


SHA_A = "a" * 40
SHA_B = "b" * 40


class StableLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.legacy = self.root / "old" / "tools" / "devflow_mcp.py"
        self.legacy.parent.mkdir(parents=True)
        self.legacy.write_text("print('legacy')\n", encoding="utf-8")

    def _release(self, sha):
        target = self.root / "releases" / sha / "tools" / "devflow_mcp.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print('release')\n", encoding="utf-8")
        return target

    def _marker(self, sha, previous=None):
        manager.write_marker(
            self.root, sha, previous,
            tree_sha256=manager.release_tree_digest(self.root / "releases" / sha),
            previous_tree_sha256=(
                manager.release_tree_digest(self.root / "releases" / previous)
                if previous is not None else None
            ),
        )

    def test_launcher_uses_only_selected_release_import_root(self):
        # Simulate the registered old checkout path using a real child process.
        # Neither GitHub nor actual credentials are used by this fixture.
        candidate = self._release(SHA_A)
        for script, label in ((self.legacy, "old"), (candidate, "new")):
            script.with_name("__init__.py").write_text("", encoding="utf-8")
            script.with_name("marker.py").write_text(
                f"LABEL = {label!r}\n", encoding="utf-8",
            )
            script.write_text(
                "import os\nfrom tools.marker import LABEL\n"
                f"assert LABEL == {label!r}\n"
                "assert os.environ['DFM_TEST_OTHER'] == 'keep'\n",
                encoding="utf-8",
            )
        with (patch.dict(os.environ, {
                  "PYTHONPATH": str(self.legacy.parent.parent),
                  "DFM_TEST_OTHER": "keep",
              }),
              patch.object(launcher, "release_root", return_value=self.root),
              patch.object(launcher.subprocess, "run", return_value=SimpleNamespace(
                  returncode=0, stdout="fixture-token",
              ))):
            old = launcher.launch_parameters("fixture-gh", str(self.legacy), root=self.root)
            self.assertEqual(old.version, "LEGACY")
            self._marker(SHA_A)
            new = launcher.launch_parameters("fixture-gh", str(self.legacy), root=self.root)
            self.assertEqual(new.version, SHA_A)
            self.assertEqual(new.parameters.env["PYTHONPATH"], str(candidate.parent.parent))
            self.assertEqual(os.environ["PYTHONPATH"], str(self.legacy.parent.parent))
        # Restore real subprocess.run before executing the fixture workers.
        for launch in (old, new):
            p = launch.parameters
            self.assertEqual(subprocess.run([p.command, *p.args], env=p.env,
                                            capture_output=True, timeout=10).returncode, 0)

    def test_invalid_release_never_requests_token(self):
        self._release(SHA_A)
        self._marker(SHA_A)
        (self.root / "releases" / SHA_A / "tools" / "devflow_mcp.py").write_text(
            "# modified", encoding="utf-8")
        with patch.object(launcher.subprocess, "run") as token:
            with self.assertRaisesRegex(ValueError, "contents changed"):
                launcher.launch_parameters("fixture-gh", str(self.legacy), root=self.root)
            token.assert_not_called()

    def test_no_marker_preserves_original_legacy_launch(self):
        self.assertEqual(
            launcher.selected_script(str(self.legacy), root=self.root),
            self.legacy,
        )

    def test_atomic_marker_picks_verified_sha_without_editing_config(self):
        candidate = self._release(SHA_A)
        self._marker(SHA_A)
        self.assertEqual(
            launcher.selected_script(str(self.legacy), root=self.root),
            candidate,
        )
        self.assertFalse(list(self.root.glob(".active-*.tmp")))

    def test_rejects_corrupt_marker_instead_of_launching_wrong_source(self):
        (self.root / "active.json").write_text(
            json.dumps({"schema_version": 1, "sha": "../../evil"}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            launcher.selected_script(str(self.legacy), root=self.root)
        (self.root / "active.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            launcher.selected_script(str(self.legacy), root=self.root)

    def test_launcher_rejects_in_root_release_alias(self):
        self._release(SHA_A)
        self._release(SHA_B)
        self._marker(SHA_B)
        redirect = self.root / "releases" / SHA_B
        shutil.rmtree(redirect)
        try:
            redirect.symlink_to(self.root / "releases" / SHA_A, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this platform")
        with self.assertRaisesRegex(ValueError, "redirected"):
            launcher.selected_script(str(self.legacy), root=self.root)


    def test_active_release_change_blocks_token_bearing_launch_and_update(self):
        script = self._release(SHA_A)
        sibling = script.with_name("agent_inbox.py")
        sibling.write_text("# trusted\n", encoding="utf-8")
        self._marker(SHA_A)
        sibling.write_text("# tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "contents changed"):
            launcher.selected_script(str(self.legacy), root=self.root)
        with patch.object(manager, "trusted_latest", return_value=SHA_A):
            with self.assertRaisesRegex(manager.ReleaseError, "differ"):
                manager.promote(
                    repo=self.root, python=Path("/fake/python"),
                    gh=Path("/fake/gh"), root=self.root, fallback=self.legacy,
                )

    def test_marker_schema_v1_is_rejected_before_token_lookup(self):
        self._release(SHA_A)
        (self.root / "active.json").write_text(
            json.dumps({"schema_version": 1, "sha": SHA_A}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "marker"):
            launcher.selected_script(str(self.legacy), root=self.root)

    def test_marker_requires_installed_release(self):
        target = self._release(SHA_A)
        self._marker(SHA_A)
        target.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            launcher.selected_script(str(self.legacy), root=self.root)


class ReleaseManagerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.legacy = self.root / "legacy.py"
        self.legacy.write_text("# old\n", encoding="utf-8")

    def _release(self, sha):
        target = self.root / "releases" / sha / "tools" / "devflow_mcp.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# safe\n", encoding="utf-8")
        return target

    def _runner(self):
        return {
            "repo": self.repo, "python": Path("/fake/python"),
            "gh": Path("/fake/gh"), "root": self.root, "fallback": self.legacy,
        }

    def _marker(self, sha, previous=None):
        manager.write_marker(
            self.root, sha, previous,
            tree_sha256=manager.release_tree_digest(self.root / "releases" / sha),
            previous_tree_sha256=(
                manager.release_tree_digest(self.root / "releases" / previous)
                if previous is not None else None
            ),
        )

    def test_missing_and_invalid_sha_rejected_without_state_change(self):
        with self.assertRaises(manager.ReleaseError):
            manager.write_marker(self.root, "unknown", None, tree_sha256="0" * 64)
        self.assertIsNone(manager.read_marker(self.root))
        with self.assertRaises(manager.ReleaseError):
            manager.write_marker(self.root, SHA_A, "../unsafe", tree_sha256="0" * 64, previous_tree_sha256="0" * 64)
        self.assertIsNone(manager.read_marker(self.root))

    def test_rollback_first_restores_legacy_without_deleting_release(self):
        self._release(SHA_A)
        self._marker(SHA_A)
        self.assertEqual(
            manager.rollback(self.root, self.legacy), "ROLLED_BACK_TO_LEGACY",
        )
        self.assertIsNone(manager.read_marker(self.root))
        self.assertTrue((self.root / "releases" / SHA_A).is_dir())
        self.assertEqual(manager.status(self.root), "HELD LEGACY")
        with patch.object(manager, "trusted_latest") as fetch:
            self.assertEqual(manager.promote(**self._runner()), "HELD LEGACY")
            fetch.assert_not_called()
        self.assertEqual(manager.resume_updates(self.root, self.legacy), "RESUMED LEGACY")
        self.assertEqual(manager.status(self.root), "LEGACY")

    def test_subsequent_rollback_switches_sha_and_retains_both(self):
        self._release(SHA_A)
        self._release(SHA_B)
        self._marker(SHA_B, SHA_A)
        self.assertEqual(manager.rollback(self.root, self.legacy), "ROLLED_BACK " + SHA_A)
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_A)
        self.assertEqual(manager.read_marker(self.root)["previous_sha"], SHA_B)
        self.assertTrue((self.root / "releases" / SHA_B).is_dir())
        self.assertEqual(manager.status(self.root), "HELD ACTIVE " + SHA_A)
        with patch.object(manager, "trusted_latest") as fetch:
            self.assertEqual(manager.promote(**self._runner()), "HELD ACTIVE " + SHA_A)
            self.assertEqual(manager.promote(**self._runner()), "HELD ACTIVE " + SHA_A)
            fetch.assert_not_called()

    def test_strips_only_narrative_schema_metadata(self):
        a = {"type": "object", "required": ["repository"], "description": "old",
             "properties": {"repository": {"type": "string", "title": "old"}}}
        b = {"type": "object", "required": ["repository"], "description": "new",
             "properties": {"repository": {"type": "string", "title": "new"}}}
        c = {"type": "object", "required": [], "properties":
             {"repository": {"type": "string"}}}
        self.assertEqual(publication_schema(a), publication_schema(b))
        self.assertNotEqual(publication_schema(a), publication_schema(c))

    def test_schema_property_names_and_literal_objects_are_never_dropped(self):
        old = {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "old hint"},
                "title": {"type": "string"},
                "examples": {"type": "array"},
                "payload": {"const": {"description": "a", "title": "source"}},
            },
            "required": ["description"],
            "description": "documentation only",
        }
        new = json.loads(json.dumps(old))
        new["description"] = "new documentation"
        new["properties"]["description"]["description"] = "new hint"
        self.assertEqual(publication_schema(old), publication_schema(new))
        new["properties"]["description"]["type"] = "integer"
        self.assertNotEqual(publication_schema(old), publication_schema(new))
        new = json.loads(json.dumps(old))
        new["properties"]["payload"]["const"]["description"] = "changed data"
        self.assertNotEqual(publication_schema(old), publication_schema(new))

    def test_existing_inactive_release_never_executes_under_trusted_sha(self):
        self._release(SHA_A)
        inactive = self._release(SHA_B)
        inactive.write_text("# unverified poison\n", encoding="utf-8")
        self._marker(SHA_A)
        def fresh_archive(_repo, _sha, destination):
            target = destination / "tools" / "devflow_mcp.py"
            target.parent.mkdir(parents=True)
            target.write_text("# verified rebuild\n", encoding="utf-8")
        with (patch.object(manager, "trusted_latest", return_value=SHA_B),
              patch.object(manager, "run", return_value=""),
              patch.object(manager, "source_archive", side_effect=fresh_archive),
              patch.object(manager, "registered_mcp_env", return_value={}),
              patch.object(manager, "smoke", return_value={"bootstrap_repository": {}}) as invoke,
              patch.object(manager, "run_unittests") as tests):
            with self.assertRaisesRegex(manager.ReleaseError, "differ"):
                manager.promote(**self._runner())
            invoke.assert_called_once()
            self.assertTrue(invoke.call_args.kwargs["full"])
            self.assertNotIn(inactive, [call.args[2] for call in invoke.call_args_list])
            tests.assert_called_once()
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_A)
        self.assertEqual(inactive.read_text(), "# unverified poison\n")

    def test_release_script_rejects_in_root_redirected_symlink(self):
        self._release(SHA_A)
        redirected = self.root / "releases" / SHA_B
        try:
            redirected.symlink_to(self.root / "releases" / SHA_A, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this platform")
        with self.assertRaisesRegex(manager.ReleaseError, "redirected"):
            manager.release_script(self.root, SHA_B)

    def test_release_gate_uses_only_exact_main_push_workflow_and_its_jobs(self):
        run = {"id": 45316024800, "head_sha": SHA_A, "head_branch": "main",
               "event": "push", "status": "completed", "conclusion": "success",
               "run_attempt": 1, "path": ".github/workflows/project-sync-tests.yml"}
        jobs = [
            {"name": name, "status": "completed", "conclusion": "success",
             "head_sha": SHA_A, "run_id": run["id"], "run_attempt": 1}
            for name in sorted(manager.REQUIRED_CHECKS)
        ]
        workflow_endpoint = (
            f"repos/{manager.REPOSITORY}/actions/workflows/project-sync-tests.yml/runs"
            f"?head_sha={SHA_A}&event=push&branch=main&per_page=100"
        )
        jobs_endpoint = (
            f"repos/{manager.REPOSITORY}/actions/runs/{run['id']}/jobs"
            "?filter=latest&per_page=100"
        )
        gh = Path("/fake/gh")
        # The actual commit had 327 unrelated check-runs; no broad check-runs
        # request is needed when using this existing workflow's own run/jobs.
        with patch.object(manager, "gh_json", side_effect=[
            {"total_count": 1, "workflow_runs": [run]},
            {"total_count": 2, "jobs": jobs},
        ]) as get:
            manager.github_gate(gh, SHA_A)
            self.assertEqual([c.args for c in get.call_args_list],
                             [(gh, workflow_endpoint), (gh, jobs_endpoint)])
        for invalid in (
            [],
            [{**run, "head_sha": SHA_B}],
            [{**run, "head_branch": "other"}],
            [{**run, "event": "pull_request"}],
            [{**run, "path": ".github/workflows/other.yml"}],
            [{**run, "status": "in_progress"}],
            [{**run, "conclusion": "failure"}],
            [run, {**run, "id": 456}],
        ):
            with self.subTest(invalid_run=invalid), patch.object(
                manager, "gh_json",
                return_value={"total_count": len(invalid), "workflow_runs": invalid},
            ) as get:
                with self.assertRaises(manager.ReleaseError):
                    manager.github_gate(gh, SHA_A)
                get.assert_called_once()
        for invalid in (
            [jobs[0]],
            [{**jobs[0], "head_sha": SHA_B}, jobs[1]],
            [{**jobs[0], "conclusion": "skipped"}, jobs[1]],
            [{**jobs[0], "run_id": 456}, jobs[1]],
            [{**jobs[0], "run_attempt": 2}, jobs[1]],
            [*jobs, {**jobs[0], "conclusion": "failure"}],
        ):
            with self.subTest(invalid_jobs=invalid), patch.object(
                manager, "gh_json", side_effect=[
                    {"total_count": 1, "workflow_runs": [run]},
                    {"total_count": len(invalid), "jobs": invalid},
                ],
            ):
                with self.assertRaises(manager.ReleaseError):
                    manager.github_gate(gh, SHA_A)
        with patch.object(manager, "gh_json", side_effect=[
            {"total_count": 1, "workflow_runs": [run]},
            {"total_count": 327, "jobs": jobs},
        ]):
            with self.assertRaises(manager.ReleaseError):
                manager.github_gate(gh, SHA_A)


    def test_registered_env_read_preserves_values_without_emitting_or_modifying_config(self):
        with tempfile.TemporaryDirectory() as home:
            user = Path(home)
            config = user / ".codex" / "config.toml"
            config.parent.mkdir()
            config.write_text(
                '[mcp_servers.kinotch_devflow]\n'
                'command = "/fake/python"\n'
                'args = ["/fake/launcher", "/fake/gh", "/fake/fallback"]\n'
                '[mcp_servers.kinotch_devflow.env]\n'
                'PYTHONPATH = "/allowed/repo"\n',
                encoding="utf-8",
            )
            with patch("pathlib.Path.home", return_value=user):
                env = manager.registered_mcp_env(
                    Path("/fake/python"), Path("/fake/fallback"),
                )
            self.assertEqual(env, {"PYTHONPATH": "/allowed/repo"})
            self.assertIn('command = "/fake/python"', config.read_text())
            original = config.read_text()
            for flag, accepted in (("-I", True), ("-c", False), ("-m", False)):
                with self.subTest(flag=flag):
                    config.write_text(original.replace('args = [', f'args = ["{flag}", '),
                                      encoding="utf-8")
                    before = config.read_bytes()
                    with patch("pathlib.Path.home", return_value=user):
                        if accepted:
                            self.assertEqual(manager.registered_mcp_env(
                                Path("/fake/python"), Path("/fake/fallback")), env)
                        else:
                            with self.assertRaises(manager.ReleaseError):
                                manager.registered_mcp_env(Path("/fake/python"),
                                                           Path("/fake/fallback"))
                    self.assertEqual(config.read_bytes(), before)



    def test_stdio_validation_uses_selected_script_root_not_registered_old_path(self):
        candidate = self._release(SHA_B)
        supplied_env = {"PYTHONPATH": str(self.legacy.parent), "DFM_TEST_OTHER": "keep"}
        observed = []
        @asynccontextmanager
        async def fake_stdio(server, **kwargs):
            observed.append(server)
            yield None, None

        class Session:
            def __init__(self, *args):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def initialize(self):
                pass

            async def list_tools(self):
                return SimpleNamespace(next_cursor=None, tools=[
                    SimpleNamespace(name=name, input_schema={"type": "object"})
                    for name in manager.REQUIRED_CALLS
                ])

        with (patch("mcp.client.stdio.stdio_client", fake_stdio),
              patch("mcp.ClientSession", Session)):
            result = asyncio.run(manager._stdio_test(
                Path("/fake/python"), candidate, "fixture-token",
                full=False, mcp_env=supplied_env,
            ))
        self.assertEqual(set(result), set(manager.REQUIRED_CALLS))
        self.assertEqual(observed[0].env["PYTHONPATH"], str(candidate.parent.parent.resolve()))
        self.assertEqual(observed[0].env["DFM_TEST_OTHER"], "keep")
        self.assertEqual(supplied_env["PYTHONPATH"], str(self.legacy.parent))

    def test_unit_validation_uses_staged_root_not_inherited_old_path(self):
        source = self.root / "stage"
        source.mkdir()
        with (patch.dict(os.environ, {"PYTHONPATH": str(self.legacy.parent)}),
              patch.object(manager.subprocess, "run", return_value=SimpleNamespace(
                  returncode=0,
              )) as invoke):
            manager.run_unittests(Path("/fake/python"), source)
        self.assertEqual(invoke.call_args.kwargs["env"]["PYTHONPATH"], str(source.resolve()))

    def test_staging_failure_does_not_promote_or_modify_old_release(self):
        old = self._release(SHA_A)
        self._marker(SHA_A)
        def fake_archive(_repo, _sha, destination):
            target = destination / "tools" / "devflow_mcp.py"
            target.parent.mkdir()
            target.write_text("# new\n", encoding="utf-8")
        with (patch.object(manager, "trusted_latest", return_value=SHA_B),
              patch.object(manager, "run", return_value=""),
              patch.object(manager, "source_archive", side_effect=fake_archive),
              patch.object(manager, "run_unittests", return_value=None),
              patch.object(manager, "registered_mcp_env", return_value={}),
              patch.object(manager, "smoke", side_effect=manager.ReleaseError("new MCP smoke failed"))):
            with self.assertRaises(manager.ReleaseError):
                manager.promote(**self._runner())
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_A)
        self.assertTrue(old.is_file())
        self.assertFalse((self.root / "releases" / SHA_B).exists())


    def test_partial_marker_failure_recovers_without_unverified_execution(self):
        self._release(SHA_A)
        self._marker(SHA_A)
        def fake_archive(_repo, _sha, destination):
            script = destination / "tools" / "devflow_mcp.py"
            script.parent.mkdir(parents=True)
            script.write_text("# rebuilt\n", encoding="utf-8")
        with (patch.object(manager, "trusted_latest", return_value=SHA_B),
              patch.object(manager, "run", return_value=""),
              patch.object(manager, "source_archive", side_effect=fake_archive),
              patch.object(manager, "run_unittests"),
              patch.object(manager, "registered_mcp_env", return_value={}),
              patch.object(manager, "smoke", return_value={"bootstrap_repository": {}})):
            with patch.object(manager, "write_marker", side_effect=OSError("locked")):
                with self.assertRaisesRegex(manager.ReleaseError, "activation incomplete"):
                    manager.promote(**self._runner())
            self.assertEqual(manager.read_marker(self.root)["sha"], SHA_A)
            retained = self.root / "releases" / SHA_B / "tools" / "devflow_mcp.py"
            self.assertEqual(retained.read_text(), "# rebuilt\n")
            with patch.object(manager.os, "replace", wraps=manager.os.replace) as replace:
                self.assertEqual(manager.promote(**self._runner()), "ACTIVATED " + SHA_B)
                self.assertEqual(len(replace.call_args_list), 1)
                self.assertEqual(Path(replace.call_args.args[1]), self.root / "active.json")
            self.assertEqual(manager.read_marker(self.root)["sha"], SHA_B)

    def test_rollback_rejects_modified_previously_verified_release(self):
        old = self._release(SHA_A)
        self._release(SHA_B)
        self._marker(SHA_B, SHA_A)
        old.write_text("# tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(manager.ReleaseError, "differ"):
            manager.rollback(self.root, self.legacy)
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_B)

    def test_rollback_then_repromotion_preserves_prior_process_source(self):
        self._release(SHA_A)
        prior = self._release(SHA_B)
        prior_bytes = prior.read_bytes()
        self._marker(SHA_B, SHA_A)
        self.assertEqual(manager.rollback(self.root, self.legacy), "ROLLED_BACK " + SHA_A)
        self.assertEqual(manager.resume_updates(self.root, self.legacy), "RESUMED ACTIVE " + SHA_A)

        def fresh_archive(_repo, _sha, destination):
            script = destination / "tools" / "devflow_mcp.py"
            script.parent.mkdir(parents=True)
            script.write_bytes(prior_bytes)

        with (patch.object(manager, "trusted_latest", return_value=SHA_B),
              patch.object(manager, "run", return_value=""),
              patch.object(manager, "source_archive", side_effect=fresh_archive),
              patch.object(manager, "run_unittests"),
              patch.object(manager, "registered_mcp_env", return_value={}),
              patch.object(manager, "smoke", return_value={"bootstrap_repository": {}}) as invoke,
              patch.object(manager.os, "replace", wraps=manager.os.replace) as replace):
            self.assertEqual(manager.promote(**self._runner()), "ACTIVATED " + SHA_B)
            self.assertEqual(len(replace.call_args_list), 1)
            self.assertEqual(Path(replace.call_args.args[1]), self.root / "active.json")
            self.assertNotIn(prior, [call.args[2] for call in invoke.call_args_list])
            invoke.assert_called_once()
            self.assertTrue(invoke.call_args.kwargs["full"])
        self.assertEqual(prior.read_bytes(), prior_bytes)

    def test_legacy_rollback_then_repromotion_preserves_original_release(self):
        prior = self._release(SHA_A)
        prior_bytes = prior.read_bytes()
        self._marker(SHA_A)
        self.assertEqual(manager.rollback(self.root, self.legacy), "ROLLED_BACK_TO_LEGACY")
        self.assertEqual(manager.resume_updates(self.root, self.legacy), "RESUMED LEGACY")

        def fresh_archive(_repo, _sha, destination):
            script = destination / "tools" / "devflow_mcp.py"
            script.parent.mkdir(parents=True)
            script.write_bytes(prior_bytes)

        with (patch.object(manager, "trusted_latest", return_value=SHA_A),
              patch.object(manager, "source_archive", side_effect=fresh_archive),
              patch.object(manager, "run_unittests"),
              patch.object(manager, "registered_mcp_env", return_value={}),
              patch.object(manager, "smoke", return_value={"bootstrap_repository": {}}),
              patch.object(manager.os, "replace", wraps=manager.os.replace) as replace):
            self.assertEqual(manager.promote(**self._runner()), "ACTIVATED " + SHA_A)
            self.assertEqual(len(replace.call_args_list), 1)
            self.assertEqual(Path(replace.call_args.args[1]), self.root / "active.json")
        self.assertEqual(prior.read_bytes(), prior_bytes)

    def test_failed_rollback_keeps_hold_even_when_marker_write_fails(self):
        self._release(SHA_A)
        self._release(SHA_B)
        self._marker(SHA_B, SHA_A)
        with patch.object(manager, "write_marker", side_effect=OSError("locked")):
            with self.assertRaises(manager.ReleaseError):
                manager.rollback(self.root, self.legacy)
        self.assertEqual(manager.status(self.root), "HELD ACTIVE " + SHA_B)
        with patch.object(manager, "trusted_latest") as fetch:
            self.assertEqual(manager.promote(**self._runner()), "HELD ACTIVE " + SHA_B)
            fetch.assert_not_called()

    def test_resume_rejects_tampered_active_release_without_clearing_hold(self):
        old = self._release(SHA_A)
        self._release(SHA_B)
        self._marker(SHA_B, SHA_A)
        manager.rollback(self.root, self.legacy)
        old.write_text("# modified\n", encoding="utf-8")
        with self.assertRaisesRegex(manager.ReleaseError, "differ"):
            manager.resume_updates(self.root, self.legacy)
        self.assertTrue(manager.updates_held(self.root))

    def test_empty_hold_file_is_still_held(self):
        (self.root / "updates.hold").touch()
        with patch.object(manager, "trusted_latest") as fetch:
            self.assertEqual(manager.promote(**self._runner()), "HELD LEGACY")
            fetch.assert_not_called()

    def test_launcher_and_manager_tree_digest_agree(self):
        script = self._release(SHA_A)
        script.with_name("module.py").write_text("# extra\n", encoding="utf-8")
        tree = self.root / "releases" / SHA_A
        self.assertEqual(manager.release_tree_digest(tree), launcher.release_tree_digest(tree))

    def test_successful_staging_atomically_selects_new_release(self):
        def fake_archive(_repo, _sha, destination):
            target = destination / "tools" / "devflow_mcp.py"
            target.parent.mkdir()
            target.write_text("# new\n", encoding="utf-8")
        with (patch.object(manager, "trusted_latest", return_value=SHA_A),
              patch.object(manager, "source_archive", side_effect=fake_archive),
              patch.object(manager, "run_unittests", return_value=None),
              patch.object(manager, "registered_mcp_env", return_value={}),
              patch.object(manager, "smoke", return_value={"bootstrap_repository": {}})):
            self.assertEqual(manager.promote(**self._runner()), "ACTIVATED " + SHA_A)
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_A)
        self.assertIsNone(manager.read_marker(self.root)["previous_sha"])
        self.assertTrue((self.root / "releases" / SHA_A / "tools" / "devflow_mcp.py").is_file())


if __name__ == "__main__":
    unittest.main()
