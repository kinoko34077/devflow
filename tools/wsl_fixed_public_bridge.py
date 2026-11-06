"""Bounded owner-Windows -> existing WSL2 Ubuntu public read-only proof.

This is an on-demand Actions-independent adapter, NOT authenticated job ingress,
OS-secure sandbox, Private CI, Cloud dispatch, or GitHub Claim authority.
No user-supplied commands, paths, recipe or raw task payload are accepted.
"""
from __future__ import annotations

import json
import ntpath
import os
import subprocess
from dataclasses import dataclass

_PUBLIC_COMMIT = "fb1f353ddf5438407a5e806682a4b37611cf346d"
_PUBLIC_BLOB = "cbe42086a50cd1bf44e4198c97cce96a6bc36396"
_EXPECTED_OUTPUT = "48022e9a9b0ba8912856ec1866cf91e0ff6566e4d6f448425911137c72d810fb"
_MAX_STDOUT = 2048

# This constant is supplied only to Python's stdin, never to a shell.
# The inner task fetches ONLY the immutable public source and validates its
# Git blob before an isolated-Python-mode local subprocess. Temp files expire.
_LINUX_PROOF = r'''
import hashlib, json, os, subprocess, sys, tempfile, urllib.request

COMMIT="fb1f353ddf5438407a5e806682a4b37611cf346d"
BLOB="cbe42086a50cd1bf44e4198c97cce96a6bc36396"
OUTPUT="48022e9a9b0ba8912856ec1866cf91e0ff6566e4d6f448425911137c72d810fb"
RECIPE=hashlib.sha256(b"devflow:f3a:sha256-fixed-v1:public-readonly-static-input\n").hexdigest()
def hold(reason):
    print(json.dumps({"status":"HOLD","reason":reason},sort_keys=True))
    sys.exit(2)
try:
    url="https://raw.githubusercontent.com/kinoko34077/devflow/"+COMMIT+"/tools/central_runner_probe.py"
    with urllib.request.urlopen(url,timeout=15) as response:
        source=response.read(32769)
except Exception:
    hold("PUBLIC_SOURCE_UNAVAILABLE")
if len(source)>32768:
    hold("SOURCE_SIZE_DENIED")
gitblob=hashlib.sha1(b"blob "+str(len(source)).encode("ascii")+b"\0"+source).hexdigest()
if gitblob!=BLOB:
    hold("PUBLIC_SOURCE_BLOB_MISMATCH")
job={"schema_version":"devflow.f3a.fixed-readonly.v1","repository":"kinoko34077/devflow",
     "task_ref":"kinoko34077/devflow#601","source_sha":COMMIT,
     "recipe_id":"sha256-fixed-v1","recipe_sha256":RECIPE,
     "attempt_id":"wsl2-fixed-readonly-01","effect":"READ_ONLY"}
try:
    with tempfile.TemporaryDirectory(prefix="devflow-wsl-public-") as root:
        path=os.path.join(root,"central_runner_probe.py")
        with open(path,"wb") as handle: handle.write(source)
        run=subprocess.run([sys.executable,"-I","-S",path,"--expected-source-sha",COMMIT],
                           input=json.dumps(job).encode("utf-8"),capture_output=True,
                           timeout=10,check=False,shell=False,
                           env={"PATH":"/usr/bin:/bin","PYTHONNOUSERSITE":"1"})
        if len(run.stdout)>2048 or run.returncode!=0:
            hold("FIXED_JOB_FAILED")
        receipt=json.loads(run.stdout)
except subprocess.TimeoutExpired:
    hold("FIXED_JOB_TIMEOUT")
except (OSError,ValueError,TypeError):
    hold("FIXED_JOB_INVALID")
if not (receipt.get("status")=="LOCAL_READ_ONLY_PROOF"
        and receipt.get("output_sha256")==OUTPUT
        and receipt.get("source_sha")==COMMIT
        and receipt.get("authenticated") is False
        and receipt.get("source_verified") is False
        and receipt.get("claim_authority") is False
        and receipt.get("github_check_authority") is False):
    hold("FIXED_RECEIPT_DENIED")
print(json.dumps({"status":"WSL_FIXED_PUBLIC_PROOF","public_source_blob_verified":True,
                  "source_git_blob":BLOB,"source_sha":COMMIT,"output_sha256":OUTPUT,
                  "authenticated":False,"isolated_host_verified":False,
                  "claim_authority":False,"github_check_authority":False},
                 sort_keys=True,separators=(",",":")))
'''


@dataclass(frozen=True)
class WslProofResult:
    status: str
    reason: str | None = None
    public_source_blob_verified: bool = False
    authenticated: bool = False
    isolated_host_verified: bool = False
    claim_authority: bool = False
    github_check_authority: bool = False


def _interpret(returncode: int, stdout: str) -> WslProofResult:
    """Do not reflect arbitrary WSL output or its errors to the caller."""
    if len(stdout) > _MAX_STDOUT:
        return WslProofResult("HOLD", "OUTPUT_TOO_LARGE")
    try:
        data = json.loads(stdout)
    except (TypeError, ValueError):
        return WslProofResult("HOLD", "INVALID_RECEIPT")
    if type(data) is not dict:
        return WslProofResult("HOLD", "INVALID_RECEIPT")
    required = {"status", "public_source_blob_verified", "source_git_blob",
                "source_sha", "output_sha256", "authenticated",
                "isolated_host_verified", "claim_authority", "github_check_authority"}
    if (returncode != 0 or set(data) != required or data["status"] != "WSL_FIXED_PUBLIC_PROOF"
            or data["public_source_blob_verified"] is not True
            or data["source_git_blob"] != _PUBLIC_BLOB or data["source_sha"] != _PUBLIC_COMMIT
            or data["output_sha256"] != _EXPECTED_OUTPUT
            or any(data[key] is not False for key in ("authenticated",
                "isolated_host_verified", "claim_authority", "github_check_authority"))):
        return WslProofResult("HOLD", "RECEIPT_NOT_AUTHORIZED")
    return WslProofResult("WSL_FIXED_PUBLIC_PROOF", public_source_blob_verified=True)


def run_once(*, timeout_seconds: int = 40) -> WslProofResult:
    """One-shot, no background process or listener; Windows + existing Ubuntu."""
    if type(timeout_seconds) is not int or not (1 <= timeout_seconds <= 60):
        return WslProofResult("HOLD", "INVALID_DEADLINE")
    if os.name != "nt":
        return WslProofResult("HOLD", "WINDOWS_REQUIRED")
    system_root = os.environ.get("SystemRoot", "")
    if not system_root or not ntpath.isabs(system_root):
        return WslProofResult("HOLD", "SYSTEM_ROOT_UNVERIFIED")
    executable = ntpath.join(system_root, "System32", "wsl.exe")
    # Inherit only the Windows paths needed to locate system DLLs; no PAT, token,
    # GH_TOKEN, WSLENV or arbitrary user environment variables.
    env = {"SystemRoot": system_root, "WINDIR": system_root,
           "PATH": ntpath.join(system_root, "System32")}
    try:
        run = subprocess.run(
            [executable, "--distribution", "Ubuntu-24.04", "--exec",
             "python3", "-I", "-S", "-"],
            input=_LINUX_PROOF, text=True, capture_output=True,
            timeout=timeout_seconds, check=False, shell=False, env=env,
        )
    except subprocess.TimeoutExpired:
        return WslProofResult("HOLD", "WSL_TIMEOUT")
    except (OSError, ValueError):
        return WslProofResult("HOLD", "WSL_UNAVAILABLE")
    return _interpret(run.returncode, run.stdout)


def main() -> int:
    from dataclasses import asdict
    outcome = run_once()
    print(json.dumps(asdict(outcome), sort_keys=True))
    return 0 if outcome.status == "WSL_FIXED_PUBLIC_PROOF" else 2


if __name__ == "__main__":
    raise SystemExit(main())
