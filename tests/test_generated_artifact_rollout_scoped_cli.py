"""Regression for identical fixed-recipe writer CLIs and post-write CI evidence."""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import unittest
from unittest.mock import patch

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import fixed_policy, select_fixed_recipe
from tools import generated_artifact_rollout_scoped_write as shared
from tools import generated_artifact_rollout_testapp_write as testapp
from tools import generated_artifact_rollout_bootstrap_e2e_write as bootstrap


class FixedWriterCliRegressionTests(unittest.TestCase):
    def entries(self):
        return (
            (testapp, "execute_testapp_scoped_write"),
            (bootstrap, "execute_bootstrap_e2e_scoped_write"),
        )

    def test_success_forwards_exact_inputs_and_does_not_print_token(self):
        for module, entry in self.entries():
            with self.subTest(repository=module._REPOSITORY):
                stdout, stderr = io.StringIO(), io.StringIO()
                token_transport = object()
                expected = {"status": "COMMITTED", "ci_verified": False}
                with (
                    patch.dict(os.environ, {
                        "WRITER_TOKEN": "synthetic-test-token",
                        "DEVFLOW_CHECKOUT_SHA": "c" * 40,
                    }, clear=True),
                    patch.object(shared, "GitHubWriteApi", return_value=token_transport) as maker,
                    patch.object(module, entry, return_value=expected) as execute,
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    status = module.main([
                        "--artifact", "fixed-archive",
                        "--target-branch", "artifact/fixed-test",
                        "--expected-head", "a" * 40,
                        "--devflow-sha", "b" * 40,
                    ])
                    args, kwargs = execute.call_args
                    self.assertIs(args[0], token_transport)
                    self.assertIs(args[1], os.environ)
                    self.assertEqual(args[2], pathlib.Path("fixed-archive"))
                    self.assertEqual(kwargs, {
                        "target_branch": "artifact/fixed-test",
                        "expected_head": "a" * 40,
                        "devflow_sha": "b" * 40,
                        "devflow_checkout_sha": "c" * 40,
                    })
                self.assertEqual(status, 0)
                self.assertEqual(stdout.getvalue(), json.dumps(expected, sort_keys=True) + "\n")
                self.assertEqual(stderr.getvalue(), "")
                maker.assert_called_once_with(module._REPOSITORY, "synthetic-test-token")
                execute.assert_called_once()
                self.assertNotIn("synthetic-test-token", stdout.getvalue())

    def test_rejected_write_keeps_exit_code_and_redacts_token(self):
        for module, entry in self.entries():
            with self.subTest(repository=module._REPOSITORY):
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch.dict(os.environ, {"WRITER_TOKEN": "synthetic-test-token"}, clear=True),
                    patch.object(shared, "GitHubWriteApi", return_value=object()),
                    patch.object(module, entry, side_effect=ArtifactRejected("synthetic rejection")),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    status = module.main([
                        "--artifact", "fixed-archive",
                        "--target-branch", "artifact/fixed-test",
                        "--expected-head", "a" * 40,
                        "--devflow-sha", "b" * 40,
                    ])
                self.assertEqual(status, 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), "REJECTED: synthetic rejection\n")
                self.assertNotIn("synthetic-test-token", stderr.getvalue())


class ScopedWriterEvidenceRegressionTests(unittest.TestCase):
    def test_success_or_replay_cannot_claim_post_commit_ci(self):
        repository = testapp._REPOSITORY
        recipe = testapp._RECIPE
        policy = fixed_policy(repository, recipe, "b" * 40)

        class Transport:
            repository = testapp._REPOSITORY

        for result_status in ("COMMITTED", "NO_OP", "NO_OP_REPLAY"):
            with self.subTest(status=result_status):
                with (
                    patch.object(shared, "attest_authenticated_readonly",
                                 return_value={"policy": policy, "admission": {}}),
                    patch.object(shared, "_read_regular_bounded",
                                 side_effect=[b"{}", b"fixed-archive"]),
                    patch.object(shared, "require_main_protection") as protected,
                    patch.object(shared, "verified_writeback",
                                 return_value={"status": result_status, "ci_verified": True}) as writeback,
                ):
                    response = shared.execute_registered_write(
                        Transport(),
                        {"MODE": "write", "GITHUB_REPOSITORY": repository,
                         "GITHUB_EVENT_NAME": "workflow_dispatch"},
                        pathlib.Path("unused"), repository=repository,
                        recipe_id=recipe,
                        target_branch=select_fixed_recipe(repository, recipe).branch_prefix + "unit",
                        expected_head="a" * 40, devflow_sha="b" * 40,
                        devflow_checkout_sha="b" * 40,
                    )
                self.assertEqual(response["status"], result_status)
                self.assertIs(response["ci_verified"], False)
                self.assertEqual(response["writer_scope"], repository)
                protected.assert_called_once()
                writeback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
