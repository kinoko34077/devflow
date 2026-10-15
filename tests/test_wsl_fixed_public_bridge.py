"""Pure standard-library tests: WSL2 approved fixed read-only bridge."""
import json
import subprocess
import unittest
from unittest.mock import patch

from tools import wsl_fixed_public_bridge as bridge


def _receipt(**kw):
    data = dict(status="WSL_FIXED_PUBLIC_PROOF", public_source_blob_verified=True,
                source_git_blob=bridge._PUBLIC_BLOB, source_sha=bridge._PUBLIC_COMMIT,
                output_sha256=bridge._EXPECTED_OUTPUT, authenticated=False,
                isolated_host_verified=False, claim_authority=False,
                github_check_authority=False)
    data.update(kw)
    return json.dumps(data)


class WslBridgeTests(unittest.TestCase):
    def test_valid_fixed_receipt_never_grants_privileges(self):
        v = bridge._interpret(0, _receipt())
        self.assertEqual(v.status, "WSL_FIXED_PUBLIC_PROOF")
        self.assertFalse(v.authenticated)
        self.assertFalse(v.isolated_host_verified)
        self.assertFalse(v.claim_authority)
        self.assertTrue(v.public_source_blob_verified)

    def test_bad_receipt_and_untrusted_actor_are_rejected(self):
        for output in ('{broken', '[]', _receipt(authenticated=True),
                       _receipt(claim_authority=True),
                       _receipt(github_check_authority=True),
                       _receipt(isolated_host_verified=True),
                       _receipt(source_sha="0" * 40),
                       _receipt(source_git_blob="bad"),
                       _receipt(output_sha256="00" * 32),
                       _receipt(public_source_blob_verified=False),
                       _receipt(unknown_field="x")):
            with self.subTest(output=output[:60]):
                self.assertEqual(bridge._interpret(0, output).status, "HOLD")

    def test_nonzero_or_large_output_rejected(self):
        self.assertEqual(bridge._interpret(2, _receipt()).status, "HOLD")
        self.assertEqual(bridge._interpret(0, "PRIVATE_DATA" * 500).reason, "OUTPUT_TOO_LARGE")

    def test_non_windows_does_not_invoke_wsl(self):
        with patch.object(bridge.os, "name", "posix"), patch.object(bridge.subprocess, "run") as run:
            self.assertEqual(bridge.run_once().reason, "WINDOWS_REQUIRED")
            run.assert_not_called()

    def test_deadline_checked_before_wsl(self):
        for value in (0, 61, True, 1.2):
            with self.subTest(value=value), patch.object(bridge.subprocess, "run") as run:
                self.assertEqual(bridge.run_once(timeout_seconds=value).reason, "INVALID_DEADLINE")
                run.assert_not_called()

    def test_fixed_wsl_argv_no_shell_and_no_creds(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=_receipt(),
                                                stderr="SECRET_SHOULD_NOT_APPEAR")
        with patch.object(bridge.os, "name", "nt"), \
             patch.dict(bridge.os.environ, {"SystemRoot": r"C:\Windows", "GH_TOKEN":"SECRET", "WSLENV":"SECRET"}, clear=True), \
             patch.object(bridge.subprocess, "run", return_value=completed) as run:
            res = bridge.run_once()
        self.assertEqual(res.status, "WSL_FIXED_PUBLIC_PROOF")
        args = run.call_args.args[0]
        self.assertEqual(args[1:], ["--distribution", "Ubuntu-24.04", "--exec", "python3", "-I", "-S", "-"])
        self.assertTrue(args[0].endswith(r"System32\wsl.exe"))
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertNotIn("SECRET", str(run.call_args.kwargs["env"]))
        self.assertNotIn("GH_TOKEN", run.call_args.kwargs["env"])
        self.assertNotIn("WSLENV", run.call_args.kwargs["env"])
        self.assertIn("raw.githubusercontent.com/kinoko34077/devflow/", run.call_args.kwargs["input"])
        self.assertNotIn("SECRET_SHOULD_NOT_APPEAR", str(res))

    def test_timeout_and_launch_error_hold(self):
        with patch.object(bridge.os, "name", "nt"), patch.dict(bridge.os.environ, {"SystemRoot": r"C:\Windows"}, clear=True):
            with patch.object(bridge.subprocess, "run", side_effect=subprocess.TimeoutExpired("wsl", 1)):
                self.assertEqual(bridge.run_once().reason, "WSL_TIMEOUT")
            with patch.object(bridge.subprocess, "run", side_effect=OSError("SECRETS")):
                self.assertEqual(bridge.run_once().reason, "WSL_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
