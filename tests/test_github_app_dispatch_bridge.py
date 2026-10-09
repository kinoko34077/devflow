"""Run the GitHub App dispatch bridge's dependency-free Node security tests in CI."""
import pathlib
import shutil
import subprocess
import unittest


class GitHubAppDispatchBridgeTests(unittest.TestCase):
    def test_node_policy_and_worker_contract(self):
        self.assertIsNotNone(shutil.which("node"), "Node.js is required; never silently skip security tests")
        root = pathlib.Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", "--test", "tools/github_app_dispatch/dispatch.test.mjs"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(
            result.returncode, 0,
            f"Node bridge test failed:\n{result.stdout}\n{result.stderr}",
        )
