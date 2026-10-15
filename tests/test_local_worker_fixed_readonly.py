"""Real one-shot subprocess proof plus fail-closed adversarial inputs."""
import hashlib
import subprocess
from unittest.mock import patch

import pytest

from tools.local_worker_fixed_readonly import FixedJob, WorkerDenied, execute_once


REPO = "kinoko34077/devflow"
SHA = "a" * 40


def good(**overrides):
    values = dict(repository=REPO, task_ref=REPO + "#605", source_sha=SHA,
                  recipe_id="python-runtime-version-v1", effect="READ_ONLY", timeout_seconds=5)
    values.update(overrides)
    return FixedJob(**values)


@pytest.mark.parametrize("change,reason", [
    ({"repository": "other/repo"}, "REPOSITORY_DENIED"),
    ({"repository": None}, "REPOSITORY_DENIED"),
    ({"task_ref": "kinoko34077/other#1"}, "TASK_SCOPE_DENIED"),
    ({"source_sha": "main"}, "INVALID_SOURCE_SHA"),
    ({"recipe_id": "arbitrary-shell"}, "RECIPE_DENIED"),
    ({"effect": "WRITE"}, "RECIPE_DENIED"),
    ({"timeout_seconds": 0}, "INVALID_DEADLINE"),
    ({"timeout_seconds": True}, "INVALID_DEADLINE"),
    ({"timeout_seconds": 999}, "INVALID_DEADLINE"),
])
def test_invalid_job_never_executes(change, reason):
    with patch("tools.local_worker_fixed_readonly.subprocess.run") as run:
        with pytest.raises(WorkerDenied, match="^" + reason + "$"):
            execute_once(good(**change), allowed_repository=REPO)
    run.assert_not_called()


def test_real_local_process_is_not_actions_or_cloud():
    receipt = execute_once(good(), allowed_repository=REPO)
    assert receipt.outcome == "SUCCESS"
    assert receipt.stdout_sha256 == hashlib.sha256(b"3\n").hexdigest()
    assert receipt.stdout_bytes == 2
    assert receipt.execution_authorized is False
    assert receipt.simulated is False


def test_only_fixed_argv_no_secrets_or_shell():
    with patch("tools.local_worker_fixed_readonly.subprocess.run", return_value=subprocess.CompletedProcess(
        [], 0, stdout=b"3\n", stderr=b"HIDDEN_SECRET"
    )) as call:
        receipt = execute_once(good(), allowed_repository=REPO)
    assert receipt.outcome == "SUCCESS"
    assert "HIDDEN_SECRET" not in str(receipt)
    assert call.call_args.kwargs["shell"] is False
    assert call.call_args.args[0][1:4] == ["-I", "-S", "-c"]
    assert "HIDDEN_SECRET" not in str(call.call_args.kwargs["env"])
    assert "PATH" not in call.call_args.kwargs["env"]


def test_timeout_yields_no_false_receipt():
    with patch("tools.local_worker_fixed_readonly.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 1)):
        receipt = execute_once(good(), allowed_repository=REPO)
    assert receipt.outcome == "TIMEOUT"
    assert receipt.stdout_sha256 is None
    assert receipt.exit_code is None


def test_exit_failure_no_false_receipt():
    with patch("tools.local_worker_fixed_readonly.subprocess.run", return_value=subprocess.CompletedProcess(
        [], 5, stdout=b"HIDDEN", stderr=b"SECRET"
    )):
        receipt = execute_once(good(), allowed_repository=REPO)
    assert receipt.outcome == "PROCESS_FAILURE"
    assert receipt.stdout_sha256 is None
    assert "HIDDEN" not in str(receipt)


def test_output_overflow_fails_closed():
    with patch("tools.local_worker_fixed_readonly.subprocess.run", return_value=subprocess.CompletedProcess(
        [], 0, stdout=b"H" * 1025, stderr=b""
    )):
        receipt = execute_once(good(), allowed_repository=REPO)
    assert receipt.outcome == "OUTPUT_TOO_LARGE"
    assert receipt.stdout_sha256 is None


def test_operational_error_fails_closed():
    with patch("tools.local_worker_fixed_readonly.subprocess.run", side_effect=OSError("private info")):
        receipt = execute_once(good(), allowed_repository=REPO)
    assert receipt.outcome == "PROCESS_UNAVAILABLE"
    assert "private info" not in str(receipt)
