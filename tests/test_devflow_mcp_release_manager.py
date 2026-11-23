"""No-network contract tests for guarded local MCP release selection (#1111)."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools import devflow_mcp_release_manager as manager
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

    def test_subsequent_rollback_switches_sha_and_retains_both(self):
        self._release(SHA_A)
        self._release(SHA_B)
        self._marker(SHA_B, SHA_A)
        self.assertEqual(manager.rollback(self.root, self.legacy), "ROLLED_BACK " + SHA_A)
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_A)
        self.assertEqual(manager.read_marker(self.root)["previous_sha"], SHA_B)
        self.assertTrue((self.root / "releases" / SHA_B).is_dir())

    def test_strips_only_narrative_schema_metadata(self):
        a = {"type": "object", "required": ["repository"], "description": "old",
             "properties": {"repository": {"type": "string", "title": "old"}}}
        b = {"type": "object", "required": ["repository"], "description": "new",
             "properties": {"repository": {"type": "string", "title": "new"}}}
        c = {"type": "object", "required": [], "properties":
             {"repository": {"type": "string"}}}
        self.assertEqual(manager._compatible_schema(a), manager._compatible_schema(b))
        self.assertNotEqual(manager._compatible_schema(a), manager._compatible_schema(c))

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
        self.assertEqual(manager._compatible_schema(old), manager._compatible_schema(new))
        new["properties"]["description"]["type"] = "integer"
        self.assertNotEqual(manager._compatible_schema(old), manager._compatible_schema(new))
        new = json.loads(json.dumps(old))
        new["properties"]["payload"]["const"]["description"] = "changed data"
        self.assertNotEqual(manager._compatible_schema(old), manager._compatible_schema(new))

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
            self.assertEqual(manager.promote(**self._runner()), "ACTIVATED " + SHA_B)
            self.assertEqual(invoke.call_count, 2)
            tests.assert_called_once()
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_B)
        self.assertEqual(inactive.read_text(), "# verified rebuild\n")
        self.assertEqual(len(list((self.root / "releases").glob(".quarantine-" + SHA_B + "-*"))), 1)

    def test_release_script_rejects_in_root_redirected_symlink(self):
        self._release(SHA_A)
        redirected = self.root / "releases" / SHA_B
        try:
            redirected.symlink_to(self.root / "releases" / SHA_A, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this platform")
        with self.assertRaisesRegex(manager.ReleaseError, "redirected"):
            manager.release_script(self.root, SHA_B)

    def test_release_gate_requires_actual_success_from_github_actions_and_exact_sha(self):
        success = [
            {"name": name, "status": "completed", "conclusion": "success",
             "head_sha": SHA_A, "app": {"slug": "github-actions"}}
            for name in manager.REQUIRED_CHECKS
        ]
        with patch.object(manager, "gh_json", return_value={
            "total_count": 2, "check_runs": success,
        }):
            manager.github_gate(Path("/fake/gh"), SHA_A)
        for invalid in (
            [success[0]],
            [{**success[0], "head_sha": SHA_B}, success[1]],
            [{**success[0], "conclusion": "skipped"}, success[1]],
            [{**success[0], "app": {"slug": "unknown"}}, success[1]],
        ):
            with self.subTest(invalid=invalid), patch.object(manager, "gh_json", return_value={
                "total_count": len(invalid), "check_runs": invalid,
            }):
                with self.assertRaises(manager.ReleaseError):
                    manager.github_gate(Path("/fake/gh"), SHA_A)


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
              patch.object(manager, "smoke", side_effect=[
                  {"bootstrap_repository": {"type": "object"}},
                  manager.ReleaseError("new MCP smoke failed"),
              ])):
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
            self.assertFalse((self.root / "releases" / SHA_B).exists())
            self.assertEqual(len(list((self.root / "releases").glob(".quarantine-" + SHA_B + "-*"))), 1)
            self.assertEqual(manager.promote(**self._runner()), "ACTIVATED " + SHA_B)
            self.assertEqual(manager.read_marker(self.root)["sha"], SHA_B)

    def test_rollback_rejects_modified_previously_verified_release(self):
        old = self._release(SHA_A)
        self._release(SHA_B)
        self._marker(SHA_B, SHA_A)
        old.write_text("# tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(manager.ReleaseError, "differ"):
            manager.rollback(self.root, self.legacy)
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_B)

    def test_rollback_then_repromotion_rebuilds_inactive_release(self):
        self._release(SHA_A)
        self._release(SHA_B)
        self._marker(SHA_B, SHA_A)
        self.assertEqual(manager.rollback(self.root, self.legacy), "ROLLED_BACK " + SHA_A)
        def fresh_archive(_repo, _sha, destination):
            script = destination / "tools" / "devflow_mcp.py"
            script.parent.mkdir(parents=True)
            script.write_text("# freshly rebuilt\n", encoding="utf-8")
        with (patch.object(manager, "trusted_latest", return_value=SHA_B),
              patch.object(manager, "run", return_value=""),
              patch.object(manager, "source_archive", side_effect=fresh_archive),
              patch.object(manager, "run_unittests"),
              patch.object(manager, "registered_mcp_env", return_value={}),
              patch.object(manager, "smoke", return_value={"bootstrap_repository": {}})):
            self.assertEqual(manager.promote(**self._runner()), "ACTIVATED " + SHA_B)
        self.assertIn("# freshly rebuilt", (self.root / "releases" / SHA_B / "tools" / "devflow_mcp.py").read_text())

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
