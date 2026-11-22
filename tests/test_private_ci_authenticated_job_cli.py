"""Fixed-credentials CLI entry tests; no network or secret exposure."""
import contextlib
from io import StringIO
import json
import os
import unittest
from unittest.mock import patch

from tools import private_ci_authenticated_job_cli as cli
from tools.private_ci_authenticated_job_read import AuthenticatedLaunchObservation

REPO = "kinoko34077/test-private"
SHA = "a" * 40
ARGS = ["--repository", REPO, "--run-id", "123", "--job-id", "456", "--head", SHA]


class AuthenticatedJobCliTests(unittest.TestCase):
    def test_missing_auth_returns_hold_without_request(self):
        output = StringIO()
        with patch.dict(os.environ, {"DEVFLOW_GITHUB_TOKEN": "", "GITHUB_TOKEN": ""}), \
             patch.object(cli, "observe_github_job_launch_once") as fetch, \
             contextlib.redirect_stdout(output):
            rc = cli.main(ARGS)
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "HOLD")
        fetch.assert_not_called()

    def test_existing_ephemeral_env_token_and_safe_result(self):
        output = StringIO()
        with patch.dict(os.environ, {"DEVFLOW_GITHUB_TOKEN": "SYNTHETIC_TOKEN_NOT_FOR_OUTPUT",
                                     "GITHUB_TOKEN": ""}), \
             patch.object(cli, "observe_github_job_launch_once", return_value=
                          AuthenticatedLaunchObservation(
                              "PLAN_ONLY", "RECORD_BILLING_BLOCK",
                              "PRIVATE_HOSTED_BILLING_BLOCKED_NOT_QUOTA_PROOF", 6
                          )) as fetch, contextlib.redirect_stdout(output):
            rc = cli.main(ARGS)
        self.assertEqual(rc, 0)
        self.assertNotIn("SYNTHETIC_TOKEN_NOT_FOR_OUTPUT", output.getvalue())
        data = json.loads(output.getvalue())
        self.assertIs(data["verified_for_dispatch"], False)
        self.assertNotIn("receipt", data)
        self.assertEqual(fetch.call_args.args[:5], (
            "kinoko34077", REPO, 123, 456, SHA,
        ))

    def test_no_host_access_suppression_from_unknown(self):
        output = StringIO()
        with patch.dict(os.environ, {"DEVFLOW_GITHUB_TOKEN": "SYNTHETIC"}), \
             patch.object(cli, "observe_github_job_launch_once", return_value=
                          AuthenticatedLaunchObservation("HOLD", "HOLD",
                                                        "GITHUB_JOB_UNVERIFIED", 3)), \
             contextlib.redirect_stdout(output):
            rc = cli.main(ARGS)
        self.assertEqual(rc, 2)
        data = json.loads(output.getvalue())
        self.assertEqual(data["action"], "HOLD")
        self.assertFalse(data["verified_for_dispatch"])


if __name__ == "__main__":
    unittest.main()
