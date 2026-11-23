"""No-network contract tests for guarded local MCP release selection (#1111)."""

import json
from pathlib import Path
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

    def test_no_marker_preserves_original_legacy_launch(self):
        self.assertEqual(
            launcher.selected_script(str(self.legacy), root=self.root),
            self.legacy,
        )

    def test_atomic_marker_picks_verified_sha_without_editing_config(self):
        candidate = self._release(SHA_A)
        manager.write_marker(self.root, SHA_A, None)
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

    def test_marker_requires_installed_release(self):
        manager.write_marker(self.root, SHA_A, None)
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

    def test_missing_and_invalid_sha_rejected_without_state_change(self):
        with self.assertRaises(manager.ReleaseError):
            manager.write_marker(self.root, "unknown", None)
        self.assertIsNone(manager.read_marker(self.root))
        with self.assertRaises(manager.ReleaseError):
            manager.write_marker(self.root, SHA_A, "../unsafe")
        self.assertIsNone(manager.read_marker(self.root))

    def test_rollback_first_restores_legacy_without_deleting_release(self):
        self._release(SHA_A)
        manager.write_marker(self.root, SHA_A, None)
        self.assertEqual(
            manager.rollback(self.root, self.legacy), "ROLLED_BACK_TO_LEGACY",
        )
        self.assertIsNone(manager.read_marker(self.root))
        self.assertTrue((self.root / "releases" / SHA_A).is_dir())

    def test_subsequent_rollback_switches_sha_and_retains_both(self):
        self._release(SHA_A)
        self._release(SHA_B)
        manager.write_marker(self.root, SHA_B, SHA_A)
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

    def test_staging_failure_does_not_promote_or_modify_old_release(self):
        old = self._release(SHA_A)
        manager.write_marker(self.root, SHA_A, None)
        def fake_archive(_repo, _sha, destination):
            target = destination / "tools" / "devflow_mcp.py"
            target.parent.mkdir()
            target.write_text("# new\n", encoding="utf-8")
        with (patch.object(manager, "trusted_latest", return_value=SHA_B),
              patch.object(manager, "run", return_value=""),
              patch.object(manager, "source_archive", side_effect=fake_archive),
              patch.object(manager, "run_unittests", return_value=None),
              patch.object(manager, "smoke", side_effect=[
                  {"bootstrap_repository": {"type": "object"}},
                  manager.ReleaseError("new MCP smoke failed"),
              ])):
            with self.assertRaises(manager.ReleaseError):
                manager.promote(**self._runner())
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_A)
        self.assertTrue(old.is_file())
        self.assertFalse((self.root / "releases" / SHA_B).exists())

    def test_successful_staging_atomically_selects_new_release(self):
        def fake_archive(_repo, _sha, destination):
            target = destination / "tools" / "devflow_mcp.py"
            target.parent.mkdir()
            target.write_text("# new\n", encoding="utf-8")
        with (patch.object(manager, "trusted_latest", return_value=SHA_A),
              patch.object(manager, "source_archive", side_effect=fake_archive),
              patch.object(manager, "run_unittests", return_value=None),
              patch.object(manager, "smoke", return_value={"bootstrap_repository": {}})):
            self.assertEqual(manager.promote(**self._runner()), "ACTIVATED " + SHA_A)
        self.assertEqual(manager.read_marker(self.root)["sha"], SHA_A)
        self.assertIsNone(manager.read_marker(self.root)["previous_sha"])
        self.assertTrue((self.root / "releases" / SHA_A / "tools" / "devflow_mcp.py").is_file())


if __name__ == "__main__":
    unittest.main()
