"""Standard-library unittest: real one-shot subprocess + fail-closed inputs."""
import hashlib
import subprocess
import unittest
from unittest.mock import patch

from tools.local_worker_fixed_readonly import FixedJob, WorkerDenied, execute_once

REPO = "kinoko34077/devflow"
SHA = "a" * 40


def good(**overrides):
    values = dict(repository=REPO, task_ref=REPO + "#605", source_sha=SHA,
                  recipe_id="python-runtime-version-v1", effect="READ_ONLY", timeout_seconds=5)
    values.update(overrides)
    return FixedJob(**values)


class FixedReadOnlyWorkerTests(unittest.TestCase):
    def test_invalid_job_never_executes(self):
        cases = [
            ({"repository": "other/repo"}, "REPOSITORY_DENIED"),
            ({"repository": None}, "REPOSITORY_DENIED"),
            ({"task_ref": "kinoko34077/other#1"}, "TASK_SCOPE_DENIED"),
            ({"source_sha": "main"}, "INVALID_SOURCE_SHA"),
            ({"recipe_id": "arbitrary-shell"}, "RECIPE_DENIED"),
            ({"effect": "WRITE"}, "RECIPE_DENIED"),
            ({"timeout_seconds": 0}, "INVALID_DEADLINE"),
            ({"timeout_seconds": True}, "INVALID_DEADLINE"),
            ({"timeout_seconds": 999}, "INVALID_DEADLINE"),
        ]
        for change, reason in cases:
            with self.subTest(reason=reason, change=change):
                with patch("tools.local_worker_fixed_readonly.subprocess.run") as run:
                    with self.assertRaisesRegex(WorkerDenied, "^" + reason + "$"):
                        execute_once(good(**change), allowed_repository=REPO)
                run.assert_not_called()

    def test_real_local_process_is_not_actions_or_cloud(self):
        receipt = execute_once(good(), allowed_repository=REPO)
        self.assertEqual(receipt.outcome, "SUCCESS")
        self.assertEqual(receipt.stdout_sha256, hashlib.sha256(b"3\n").hexdigest())
        self.assertEqual(receipt.stdout_bytes, 2)
        self.assertFalse(receipt.execution_authorized)
        self.assertFalse(receipt.simulated)

    def test_only_fixed_argv_no_secrets_or_shell(self):
        with patch("tools.local_worker_fixed_readonly.subprocess.run", return_value=subprocess.CompletedProcess(
            [], 0, stdout=b"3\n", stderr=b"HIDDEN_SECRET"
        )) as call:
            receipt = execute_once(good(), allowed_repository=REPO)
        self.assertEqual(receipt.outcome, "SUCCESS")
        self.assertNotIn("HIDDEN_SECRET", str(receipt))
        self.assertFalse(call.call_args.kwargs["shell"])
        self.assertEqual(call.call_args.args[0][1:4], ["-I", "-S", "-c"])
        self.assertNotIn("HIDDEN_SECRET", str(call.call_args.kwargs["env"]))
        self.assertNotIn("PATH", call.call_args.kwargs["env"])

    def test_timeout_yields_no_false_receipt(self):
        with patch("tools.local_worker_fixed_readonly.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 1)):
            receipt = execute_once(good(), allowed_repository=REPO)
        self.assertEqual(receipt.outcome, "TIMEOUT")
        self.assertIsNone(receipt.stdout_sha256)
        self.assertIsNone(receipt.exit_code)

    def test_exit_failure_no_false_receipt(self):
        with patch("tools.local_worker_fixed_readonly.subprocess.run", return_value=subprocess.CompletedProcess(
            [], 5, stdout=b"HIDDEN", stderr=b"SECRET"
        )):
            receipt = execute_once(good(), allowed_repository=REPO)
        self.assertEqual(receipt.outcome, "PROCESS_FAILURE")
        self.assertIsNone(receipt.stdout_sha256)
        self.assertNotIn("HIDDEN", str(receipt))

    def test_output_overflow_fails_closed(self):
        with patch("tools.local_worker_fixed_readonly.subprocess.run", return_value=subprocess.CompletedProcess(
            [], 0, stdout=b"H" * 1025, stderr=b""
        )):
            receipt = execute_once(good(), allowed_repository=REPO)
        self.assertEqual(receipt.outcome, "OUTPUT_TOO_LARGE")
        self.assertIsNone(receipt.stdout_sha256)

    def test_operational_error_fails_closed(self):
        with patch("tools.local_worker_fixed_readonly.subprocess.run", side_effect=OSError("private info")):
            receipt = execute_once(good(), allowed_repository=REPO)
        self.assertEqual(receipt.outcome, "PROCESS_UNAVAILABLE")
        self.assertNotIn("private info", str(receipt))


if __name__ == "__main__":
    unittest.main()
