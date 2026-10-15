"""Single-shot Actions-independent *fixed* local subprocess pilot.

No GitHub/Cloud network, scheduling, resident service, untrusted source code,
credentials or Claim mutation. Process isolation is NOT OS sandbox isolation.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass

_REPO = re.compile(r"[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TASK = re.compile(r"([a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*)#[1-9][0-9]*\Z")
_RECIPE = "python-runtime-version-v1"
_PROGRAM = "import sys; sys.stdout.buffer.write((str(sys.version_info.major) + chr(10)).encode('ascii'))"
_MAX_OUTPUT = 1024


class WorkerDenied(ValueError):
    """Finite reason, never caller data."""


@dataclass(frozen=True)
class FixedJob:
    repository: str
    task_ref: str
    source_sha: str
    recipe_id: str
    effect: str
    timeout_seconds: int


@dataclass(frozen=True)
class LocalReceipt:
    outcome: str
    repository: str
    source_sha: str
    recipe_id: str
    exit_code: int | None
    stdout_sha256: str | None
    stdout_bytes: int
    simulated: bool = False
    execution_authorized: bool = False  # Not a GitHub Claim or authorization to write.


def _validate(job: FixedJob, *, allowed_repository: str) -> None:
    if type(job) is not FixedJob or type(allowed_repository) is not str:
        raise WorkerDenied("INVALID_JOB")
    if type(job.repository) is not str or not _REPO.fullmatch(job.repository) or job.repository != allowed_repository:
        raise WorkerDenied("REPOSITORY_DENIED")
    match = _TASK.fullmatch(job.task_ref) if type(job.task_ref) is str else None
    if match is None or match.group(1) != job.repository:
        raise WorkerDenied("TASK_SCOPE_DENIED")
    if type(job.source_sha) is not str or not _SHA.fullmatch(job.source_sha):
        raise WorkerDenied("INVALID_SOURCE_SHA")
    if job.recipe_id != _RECIPE or job.effect != "READ_ONLY":
        raise WorkerDenied("RECIPE_DENIED")
    if type(job.timeout_seconds) is not int or not 1 <= job.timeout_seconds <= 10:
        raise WorkerDenied("INVALID_DEADLINE")


def execute_once(job: FixedJob, *, allowed_repository: str) -> LocalReceipt:
    """Run only pinned, local interpreter probe; no caller-controlled argv."""
    _validate(job, allowed_repository=allowed_repository)
    env = {"PYTHONIOENCODING": "utf-8"}
    # Windows CreateProcess may require SystemRoot to locate system assemblies.
    if os.name == "nt" and os.environ.get("SystemRoot"):
        env["SystemRoot"] = os.environ["SystemRoot"]
    try:
        with tempfile.TemporaryDirectory(prefix="kinotch-worker-probe-") as workspace:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", "-c", _PROGRAM],
                cwd=workspace,
                env=env,
                capture_output=True,
                timeout=job.timeout_seconds,
                check=False,
                shell=False,
            )
    except subprocess.TimeoutExpired:
        outcome, code, stdout = "TIMEOUT", None, b""
    except (OSError, ValueError):
        outcome, code, stdout = "PROCESS_UNAVAILABLE", None, b""
    else:
        code = proc.returncode
        stdout = proc.stdout
        outcome = "SUCCESS" if code == 0 and len(stdout) <= _MAX_OUTPUT else (
            "OUTPUT_TOO_LARGE" if len(stdout) > _MAX_OUTPUT else "PROCESS_FAILURE"
        )
    digest = hashlib.sha256(stdout).hexdigest() if outcome == "SUCCESS" else None
    return LocalReceipt(
        outcome, job.repository, job.source_sha, job.recipe_id,
        code, digest, len(stdout) if digest is not None else 0,
    )
