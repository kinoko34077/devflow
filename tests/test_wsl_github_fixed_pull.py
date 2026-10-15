"""Tests for on-demand GitHub comment GET -> fixed Public WSL2 with replay ledger."""
from __future__ import annotations

from contextlib import closing

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from tools import wsl_github_fixed_pull as pull


def comment(comment_id=6199999911, nonce="f3c-0123456789abcdefghij", **mutations):
    body = pull._PREFIX + json.dumps({
        "schema_version": "devflow.f3c.wsl-public-request.v1",
        "repository": "kinoko34077/devflow",
        "task_ref": "kinoko34077/devflow#610",
        "recipe_id": "wsl-fixed-public-v1",
        "effect": "READ_ONLY",
        "nonce": nonce,
    }, sort_keys=True)
    data = dict(
        id=comment_id, issue_url=pull._ISSUE_URL,
        user={"login": "kinoko34077", "type": "User"},
        created_at="2026-10-15T18:00:00Z",
        updated_at="2026-10-15T18:00:00Z",
        body=body,
    )
    data.update(mutations)
    return data


class GitHubWslPullTests(unittest.TestCase):
    def test_public_fixed_candidate_never_runs(self):
        c = comment()
        with patch.object(pull, "_fetch_comment", return_value=c), \
             patch.object(pull, "run_fixed_public") as worker, \
             patch.object(pull, "_reserve") as reserve:
            result = pull.execute_comment(c["id"])
        self.assertEqual(result.status, "CANDIDATE_ONLY")
        self.assertTrue(result.github_author_observed)
        self.assertFalse(result.authenticated)
        worker.assert_not_called()
        reserve.assert_not_called()

    def test_bogus_author_issue_edited_request_never_runs(self):
        base = comment()
        variants = [
            {"id": True},
            {"issue_url": "https://api.github.com/repos/other/other/issues/610"},
            {"user": {"login": "attacker", "type": "User"}},
            {"user": {"login": "kinoko34077", "type": "Bot"}},
            {"updated_at": "2026-10-15T18:01:00Z"},
            {"body": "RUN arbitrary shell"},
            {"body": base["body"].replace("READ_ONLY", "WRITE")},
            {"body": base["body"].replace("wsl-fixed-public-v1", "sh -c attacker")},
            {"body": base["body"].replace("#610", "#1")},
            {"body": base["body"].replace("f3c-0123456789abcdefghij", "f3c-short")},
            {"body": base["body"].replace("kinoko34077/devflow", "other/repo")},
            {"body": base["body"] + "\nATTACK"},
        ]
        for changed in variants:
            with self.subTest(changed=changed):
                with patch.object(pull, "_fetch_comment", return_value={**base, **changed}), \
                     patch.object(pull, "_reserve") as reserve, \
                     patch.object(pull, "run_fixed_public") as worker:
                    result = pull.execute_comment(base["id"], execute=True)
                self.assertEqual(result.status, "HOLD")
                self.assertEqual(result.reason, "REQUEST_UNTRUSTED_OR_UNAVAILABLE")
                reserve.assert_not_called()
                worker.assert_not_called()

    def test_bad_numeric_identity_denied_without_fetch(self):
        for candidate in (0, -1, True, "6199", 10**20):
            with self.subTest(candidate=candidate), patch.object(pull, "_fetch_comment") as fetch:
                self.assertEqual(pull.execute_comment(candidate).reason, "INVALID_COMMENT_ID")
                fetch.assert_not_called()

    def test_read_existing_gh_only_fixed_url_and_no_shell(self):
        data = comment()
        proc = subprocess.CompletedProcess([], 0, stdout=json.dumps(data), stderr="SECRET")
        with patch.object(pull.subprocess, "run", return_value=proc) as run:
            observed = pull._fetch_comment(data["id"])
        self.assertEqual(observed["id"], data["id"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["gh", "api", "-H", "Accept: application/vnd.github+json"])
        self.assertEqual(argv[-1], f"repos/kinoko34077/devflow/issues/comments/{data['id']}")
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_api_errors_are_redacted(self):
        cases = [
            subprocess.CompletedProcess([], 403, stdout="SECRET", stderr="OTHER_SECRET"),
            subprocess.CompletedProcess([], 0, stdout="{bad", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="X" * 16385, stderr=""),
        ]
        for value in cases:
            with self.subTest(value=value.returncode), patch.object(pull.subprocess, "run", return_value=value):
                self.assertIsNone(pull._fetch_comment(6199999911))
        with patch.object(pull.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 1)):
            self.assertIsNone(pull._fetch_comment(6199999911))

    def test_sqlite_reservation_denies_replay_across_calls(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = Path(root) / "receipts.sqlite3"
            self.assertEqual(pull._reserve(ledger, 6199999911, "d" * 64), "RESERVED")
            self.assertEqual(pull._reserve(ledger, 6199999911, "d" * 64), "REPLAY_DENIED")
            self.assertEqual(pull._reserve(ledger, 6199999912, "d" * 64), "REPLAY_DENIED")
            with closing(sqlite3.connect(str(ledger))) as con:
                rows = con.execute("SELECT comment_id,status FROM public_job_attempts").fetchall()
            self.assertEqual(rows, [(6199999911, "RESERVED")])

    def test_real_path_calls_only_pinned_worker_and_denies_replay(self):
        c = comment()
        mock_worker = Mock(
            status="WSL_FIXED_PUBLIC_PROOF", public_source_blob_verified=True,
            authenticated=False, isolated_host_verified=False,
            claim_authority=False, github_check_authority=False,
        )
        with tempfile.TemporaryDirectory() as root, \
             patch.object(pull, "_fetch_comment", return_value=c), \
             patch.object(pull, "run_fixed_public", return_value=mock_worker) as worker:
            ledger = Path(root) / "replay.sqlite3"
            first = pull.execute_comment(c["id"], execute=True, ledger_path=ledger)
            second = pull.execute_comment(c["id"], execute=True, ledger_path=ledger)
        self.assertEqual(first.status, "PUBLIC_READONLY_EXECUTED")
        self.assertEqual(second.reason, "REPLAY_DENIED")
        self.assertEqual(worker.call_count, 1)
        worker.assert_called_once_with(timeout_seconds=40)
        self.assertFalse(first.authenticated)
        self.assertFalse(first.claim_authority)

    def test_failed_worker_stays_consumed_no_auto_retry(self):
        c = comment()
        with tempfile.TemporaryDirectory() as root, \
             patch.object(pull, "_fetch_comment", return_value=c), \
             patch.object(pull, "run_fixed_public", side_effect=RuntimeError("SECRET")) as worker:
            ledger = Path(root) / "replay.sqlite3"
            first = pull.execute_comment(c["id"], execute=True, ledger_path=ledger)
            second = pull.execute_comment(c["id"], execute=True, ledger_path=ledger)
            with closing(sqlite3.connect(str(ledger))) as con:
                outcome = con.execute("SELECT status FROM public_job_attempts").fetchone()[0]
        self.assertEqual(first.reason, "WORKER_NOT_VERIFIED")
        self.assertEqual(second.reason, "REPLAY_DENIED")
        self.assertEqual(outcome, "UNCERTAIN")
        self.assertEqual(worker.call_count, 1)
        self.assertNotIn("SECRET", str(first))

    def test_missing_ledger_does_not_run(self):
        c = comment()
        with patch.object(pull, "_fetch_comment", return_value=c), \
             patch.object(pull, "_ledger_path", return_value=None), \
             patch.object(pull, "run_fixed_public") as worker:
            self.assertEqual(pull.execute_comment(c["id"], execute=True).reason, "LEDGER_PATH_UNAVAILABLE")
            worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
