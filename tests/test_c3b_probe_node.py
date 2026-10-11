"""Hosted verification for #424's *offline-only* C3-B GitHub App probe.

Do not invoke the credential-bearing entry point: the Node test harness provides
a synthetic process, user token and fetch implementation inside its VM.
"""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/c3b_proof/kinotch_c3b_proof_20261011_hardened.cjs"
FIXTURE = ROOT / "tools/c3b_proof/kinotch_c3b_proof_20261011_hardened.test.cjs"


class C3BProbeOfflineNodeTests(unittest.TestCase):
    def test_source_syntax_and_fully_mocked_negative_matrix(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js required for C3-B proof security fixtures")
        self.assertTrue(SOURCE.is_file(), "Reviewable probe source must exist")
        self.assertTrue(FIXTURE.is_file(), "Networkless Node fixture must exist")
        for args in ([node, "--check", str(SOURCE)], [node, "--test", str(FIXTURE)]):
            with self.subTest(command=args[1]):
                run = subprocess.run(
                    args, cwd=ROOT, capture_output=True, text=True,
                    timeout=20, check=False
                )
                self.assertEqual(
                    run.returncode, 0,
                    f"Offline C3-B check failed (never run OAuth here):\n"
                    f"{run.stdout[-3500:]}\n{run.stderr[-3500:]}",
                )
                if args[1] == "--test":
                    self.assertIn("pass 17", run.stdout)
                    self.assertIn("fail 0", run.stdout)


if __name__ == "__main__":
    unittest.main()
