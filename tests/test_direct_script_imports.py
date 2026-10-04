import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DirectScriptImportRegressionTests(unittest.TestCase):
    def test_project_sync_direct_entrypoint_imports_from_repository_root(self):
        result = subprocess.run(
            [sys.executable, "scripts/project_sync.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn("usage:", result.stdout.lower())

    def test_devflow_mcp_core_top_level_fallback_imports_repository_projection(self):
        code = (
            "import sys; "
            "sys.path.insert(0, '../tools'); "
            "import devflow_mcp_core; "
            "print(devflow_mcp_core.DEFAULT_OWNER)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT / "scripts",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertEqual(result.stdout.strip(), "kinoko34077")


if __name__ == "__main__":
    unittest.main()
