"""F3A standalone Actions-independent *fixed read-only CPU proof*.

Invocation: python -m tools.central_runner_probe --expected-source-sha <40hex>
             < fixed-request.json

No network, GitHub API, secrets, source checkout, file writes, host provisioning,
or Claim actions. This is an executable *local* process/ABI proof, NOT a hosted
gateway, execution grant, authenticated source, isolated VM, GitHub check, or
production receipt. A caller-chosen --expected-source-sha is NOT attestation.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass

_SCHEMA = "devflow.f3a.fixed-readonly.v1"
_RECIPE_ID = "sha256-fixed-v1"
_RECIPE_BYTES = b"devflow:f3a:sha256-fixed-v1:public-readonly-static-input\n"
_RECIPE_SHA256 = hashlib.sha256(_RECIPE_BYTES).hexdigest()
_PAYLOAD = b"devflow-f3a-public-proof-v1\n"
_REPO = "kinoko34077/devflow"
_TASK_REF = "kinoko34077/devflow#601"
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_ATTEMPT = re.compile(r"[a-z][a-z0-9_.:-]{0,63}\Z")
_INPUT_LIMIT = 4096
_KEYS = frozenset({"schema_version", "repository", "task_ref", "source_sha",
                   "recipe_id", "recipe_sha256", "attempt_id", "effect"})


class ProbeDenied(ValueError):
    """Finite denial code that never repeats a caller's input or credentials."""


@dataclass(frozen=True)
class FixedProof:
    schema_version: str
    status: str
    request_sha256: str
    output_sha256: str
    source_sha: str
    recipe_sha256: str
    backend: str = "standalone-local-process"
    simulated: bool = False
    authenticated: bool = False
    source_verified: bool = False
    isolated_host_verified: bool = False
    claim_authority: bool = False
    github_check_authority: bool = False


def _hexsha(value: object) -> bool:
    return type(value) is str and _SHA1.fullmatch(value) is not None


def run_fixed_probe(raw: bytes, *, expected_source_sha: str) -> FixedProof:
    """Compute an actual CPU hash only for one accepted public fixed recipe.

    A trusted future *outer host* must independently pin source and authenticate
    this process/receipt. The CLI itself only checks the caller-provided pin.
    """
    if not _hexsha(expected_source_sha):
        raise ProbeDenied("INVALID_SOURCE_PIN")
    if type(raw) is not bytes or not (1 <= len(raw) <= _INPUT_LIMIT):
        raise ProbeDenied("INPUT_SIZE_DENIED")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        raise ProbeDenied("INVALID_JSON") from exc
    if type(obj) is not dict or set(obj) != _KEYS:
        raise ProbeDenied("INVALID_REQUEST_SHAPE")
    if (obj["schema_version"] != _SCHEMA
            or type(obj["repository"]) is not str or obj["repository"] != _REPO
            or type(obj["task_ref"]) is not str or obj["task_ref"] != _TASK_REF
            or type(obj["source_sha"]) is not str
            or obj["source_sha"] != expected_source_sha
            or type(obj["recipe_id"]) is not str or obj["recipe_id"] != _RECIPE_ID
            or type(obj["recipe_sha256"]) is not str
            or obj["recipe_sha256"] != _RECIPE_SHA256
            or type(obj["effect"]) is not str or obj["effect"] != "READ_ONLY"
            or type(obj["attempt_id"]) is not str
            or _ATTEMPT.fullmatch(obj["attempt_id"]) is None):
        raise ProbeDenied("FIXED_RECIPE_OR_SOURCE_DENIED")
    canonical = json.dumps(obj, ensure_ascii=True, sort_keys=True,
                           separators=(",", ":")).encode("ascii")
    return FixedProof(
        schema_version=_SCHEMA,
        status="LOCAL_READ_ONLY_PROOF",
        request_sha256=hashlib.sha256(canonical).hexdigest(),
        output_sha256=hashlib.sha256(_PAYLOAD).hexdigest(),
        source_sha=expected_source_sha,
        recipe_sha256=_RECIPE_SHA256,
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if (len(args) != 2 or args[0] != "--expected-source-sha"
            or not _hexsha(args[1])):
        print(json.dumps({"status": "HOLD", "reason": "INVALID_SOURCE_PIN"},
                         sort_keys=True))
        return 2
    try:
        raw = sys.stdin.buffer.read(_INPUT_LIMIT + 1)
        result = run_fixed_probe(raw, expected_source_sha=args[1])
    except ProbeDenied as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc)}, sort_keys=True))
        return 2
    # Static projection: never print private source, raw request, token or job data.
    print(json.dumps(result.__dict__, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
