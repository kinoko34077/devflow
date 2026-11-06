"""Offline-only tests: never use the owner's gh binary or real credentials."""
import io
import os
import subprocess
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from tools import owner_local_fixed_dispatch as f

SHA = "a" * 40


def fake_subprocess(*, login=f.ACTOR, head=SHA, blob=f.WORKFLOW_BLOB_SHA,
                    state="active", dispatch_rc=0):
    calls = []

    def run(argv, **kwargs):
        calls.append(tuple(argv))
        if tuple(argv[:3]) == ("gh", "api", "user"):
            return subprocess.CompletedProcess(argv, 0, login + "\n", "")
        if tuple(argv[:2]) == ("gh", "api"):
            if "/branches/main" in argv[2]:
                return subprocess.CompletedProcess(argv, 0, head + "\n", "")
            if "/contents/" in argv[2]:
                return subprocess.CompletedProcess(argv, 0, blob + "\n", "")
            if "/actions/workflows/" in argv[2]:
                return subprocess.CompletedProcess(argv, 0, state + "\n", "")
        if tuple(argv[:3]) == ("gh", "workflow", "run"):
            return subprocess.CompletedProcess(argv, dispatch_rc, "", "secret is hidden")
        raise AssertionError(f"unexpected subprocess: {argv}")

    return run, calls


class OwnerLocalFixedDispatchTests(unittest.TestCase):
    def setUp(self):
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_default_is_read_only_and_never_dispatches(self):
        run, calls = fake_subprocess()
        with patch.object(f.subprocess, "run", side_effect=run):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(f.main(["--expected-head", SHA]), 0)
        self.assertIn("PREFLIGHT_OK_NO_ACTION_TAKEN", output.getvalue())
        self.assertEqual(len(calls), 4)
        self.assertFalse(any(q[:3] == ("gh", "workflow", "run") for q in calls))

    def test_explicit_execution_fixed_arguments_only(self):
        run, calls = fake_subprocess()
        with patch.object(f.subprocess, "run", side_effect=run):
            result = f.dispatch(SHA)
        self.assertEqual(result.code, "REQUEST_SUBMITTED_UNVERIFIED_VERIFY_ACTIONS_RUN")
        self.assertEqual(calls[-1], (
            "gh", "workflow", "run", "maintenance-audit.yml", "--repo", "kinoko34077/devflow",
            "--ref", "main", "--field", "mode=audit",
            "--field", "repository=kinoko34077/devflow", "--field", "control=16",
        ))
        self.assertEqual(len(calls), 6)
        for argv in calls:
            self.assertNotIn("-X", argv)
            self.assertNotIn("--shell", argv)

    def test_reject_malformed_sha_without_touching_cli(self):
        with patch.object(f.subprocess, "run", side_effect=AssertionError("should not call")):
            for head in ("0", "A" * 40, " " + SHA, SHA + "\n", "a" * 39, "a" * 41):
                self.assertEqual(f.dispatch(head).code, "HOLD_INVALID_EXPECTED_HEAD")

    def test_reject_shadow_token_without_invoking_cli(self):
        with patch.dict(os.environ, {"GH_TOKEN": "hidden"}):
            with patch.object(f.subprocess, "run", side_effect=AssertionError("should not call")):
                self.assertEqual(f.dispatch(SHA).code, "HOLD_ENV_TOKEN_SHADOW")

    def test_actor_mismatch_prevents_dispatch(self):
        run, calls = fake_subprocess(login="untrusted")
        with patch.object(f.subprocess, "run", side_effect=run):
            self.assertEqual(f.dispatch(SHA).code, "HOLD_UNVERIFIED_ACTOR")
        self.assertEqual(len(calls), 1)

    def test_stale_head_prevents_dispatch(self):
        run, calls = fake_subprocess(head="b" * 40)
        with patch.object(f.subprocess, "run", side_effect=run):
            self.assertEqual(f.dispatch(SHA).code, "HOLD_MAIN_HEAD_CHANGED_OR_UNAVAILABLE")
        self.assertEqual(len(calls), 2)

    def test_unreviewed_workflow_source_prevents_dispatch(self):
        run, calls = fake_subprocess(blob="c" * 40)
        with patch.object(f.subprocess, "run", side_effect=run):
            self.assertEqual(f.dispatch(SHA).code, "HOLD_UNREVIEWED_WORKFLOW_SOURCE")
        self.assertEqual(len(calls), 3)

    def test_disabled_workflow_prevents_dispatch(self):
        run, calls = fake_subprocess(state="disabled_manually")
        with patch.object(f.subprocess, "run", side_effect=run):
            self.assertEqual(f.dispatch(SHA).code, "HOLD_WORKFLOW_DISABLED_OR_UNAVAILABLE")
        self.assertEqual(len(calls), 4)

    def test_head_race_prevents_dispatch(self):
        run, calls = fake_subprocess()
        n = 0
        def head_race(argv, **kwargs):
            nonlocal n
            if "/branches/main" in " ".join(argv):
                n += 1
                if n == 2:
                    return subprocess.CompletedProcess(argv, 0, "b" * 40, "")
            return run(argv, **kwargs)
        with patch.object(f.subprocess, "run", side_effect=head_race):
            self.assertEqual(f.dispatch(SHA).code, "HOLD_HEAD_CHANGED_BEFORE_REQUEST")
        self.assertFalse(any(q[:3] == ("gh", "workflow", "run") for q in calls))

    def test_dispatch_error_never_prints_stderr(self):
        run, calls = fake_subprocess(dispatch_rc=1)
        with patch.object(f.subprocess, "run", side_effect=run):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(f.main(["--expected-head", SHA, "--execute"]), 2)
        self.assertEqual(output.getvalue().strip(), "HOLD_DISPATCH_DENIED_OR_FAILED")
        self.assertNotIn("secret", output.getvalue())
        self.assertEqual(len(calls), 6)

    def test_missing_cli_fails_closed(self):
        with patch.object(f.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(f.dispatch(SHA).code, "HOLD_UNVERIFIED_ACTOR")

    def test_unknown_arguments_are_rejected(self):
        with patch.object(f.subprocess, "run", side_effect=AssertionError("should not call")):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    f.main(["--expected-head", SHA, "--repo", "other-owner/repo"])


if __name__ == "__main__":
    unittest.main()
