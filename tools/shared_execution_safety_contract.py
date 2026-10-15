"""M2 pure compatibility projections. No real authentication, dispatch or Claim.

M1: devflow#639 / owner devflow#646. Ingress data, caller-supplied
catalog and "observed" actor are NEVER a verified principal. These
projections are not capabilities or authorizations. Production runtime
must authenticate actor/source/catalog independently (G2B0 C1-C6).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from tools.safe_dispatch_contract import admit_dispatch, parse_json_object

_VERSION = "devflow.shared-safety-projection.v1"
_F3C_SCHEMA = "devflow.f3c.wsl-public-request.v1"
_F3C_PREFIX = "F3C-WSL-PUBLIC-ONCE-V1\n"
_F3C_KEYS = frozenset({
    "schema_version", "repository", "task_ref", "recipe_id", "effect", "nonce",
})
_F3C_NONCE = re.compile(r"f3c-[a-z0-9]{20}\Z")
_OWNER = "kinoko34077"
_REPO = "kinoko34077/devflow"
_TASK = "kinoko34077/devflow#610"
_RECIPE = "wsl-fixed-public-v1"
_MAX_F3C = 1024


@dataclass(frozen=True)
class SafetyProjection:
    """A safe report, deliberately incapable of carrying live authority."""
    schema_version: str = _VERSION
    status: str = "HOLD"
    reason: str = "INVALID"
    legacy_schema: str | None = None
    repository: str | None = None
    task_ref: str | None = None
    operation: str | None = None
    effect: str | None = None
    request_id: str | None = None
    request_digest: str | None = None
    nonce_digest: str | None = None
    backend_candidate: str | None = None
    source_sha: str | None = None
    catalog_sha256: str | None = None
    authenticated: bool = False
    source_verified: bool = False
    claim_authority: bool = False
    github_check_authority: bool = False
    independently_executed: bool = False


def _digest(domain: bytes, obj: dict[str, Any]) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(domain + raw).hexdigest()


def project_f3c_candidate(body: str, *, comment_id: int,
                          observed_login: str) -> SafetyProjection:
    """Project one legacy F3C public request, with *no* execution permission.

    The login supplied here is ONLY attribution from an untrusted envelope;
    a matching login never makes the proposal authenticated.
    """
    denied = SafetyProjection(legacy_schema=_F3C_SCHEMA)
    if (type(body) is not str or len(body) > _MAX_F3C
            or not body.startswith(_F3C_PREFIX)
            or type(comment_id) is not int or not 1 <= comment_id < 10**17
            or type(observed_login) is not str
            or observed_login != _OWNER):
        return SafetyProjection(
            legacy_schema=_F3C_SCHEMA, reason="UNTRUSTED_ENVELOPE_OR_SIZE",
        )
    try:
        obj = parse_json_object(body[len(_F3C_PREFIX):], max_bytes=_MAX_F3C)
    except (ValueError, TypeError, OverflowError):
        return SafetyProjection(
            legacy_schema=_F3C_SCHEMA, reason="STRICT_JSON_DENIED",
        )
    if (frozenset(obj) != _F3C_KEYS
            or type(obj["schema_version"]) is not str
            or obj["schema_version"] != _F3C_SCHEMA
            or type(obj["repository"]) is not str or obj["repository"] != _REPO
            or type(obj["task_ref"]) is not str or obj["task_ref"] != _TASK
            or type(obj["recipe_id"]) is not str or obj["recipe_id"] != _RECIPE
            or type(obj["effect"]) is not str or obj["effect"] != "READ_ONLY"
            or type(obj["nonce"]) is not str
            or _F3C_NONCE.fullmatch(obj["nonce"]) is None):
        return SafetyProjection(
            legacy_schema=_F3C_SCHEMA, reason="FIXED_PUBLIC_RECIPE_DENIED",
        )
    return SafetyProjection(
        status="CANDIDATE_ONLY",
        reason="LEGACY_PUBLIC_REQUEST_VALID_NOT_AUTHENTICATED",
        legacy_schema=_F3C_SCHEMA,
        repository=_REPO,
        task_ref=_TASK,
        operation=_RECIPE,
        effect="READ_ONLY",
        request_id=f"gh-comment-{comment_id}",
        request_digest=_digest(b"devflow-shared-f3c-request-v1\0", obj),
        nonce_digest=hashlib.sha256(
            b"devflow-shared-f3c-nonce-v1\0" + obj["nonce"].encode("ascii")
        ).hexdigest(),
        backend_candidate="fixed-public-wsl2",
    )


def project_g1_policy(raw_request: str, *, catalog: Any,
                      observed_actor: str) -> SafetyProjection:
    """Wrap the actual existing G1 policy, but never attest caller/catalog.

    Policy admission is not an authenticated principal, validated catalog
    provenance, target repository observation, execution or Claim.
    """
    if type(raw_request) is not str or type(observed_actor) is not str:
        return SafetyProjection(reason="INVALID_G1_INPUT")
    try:
        request = parse_json_object(raw_request, max_bytes=8192)
    except (ValueError, TypeError, OverflowError):
        return SafetyProjection(reason="STRICT_JSON_DENIED")
    decision = admit_dispatch(request, catalog, verified_actor=observed_actor)
    if decision.status != "ADMITTED":
        return SafetyProjection(
            reason=("HUMAN_GATE_REQUIRED" if decision.status == "NEEDS_HUMAN"
                    else "G1_POLICY_DENIED"),
            legacy_schema="dispatch-request.v1",
        )
    return SafetyProjection(
        status="POLICY_ONLY",
        reason="G1_POLICY_MATCHED_NOT_AUTHENTICATED_OR_EXECUTED",
        legacy_schema="dispatch-request.v1",
        repository=decision.repository,
        operation=decision.action,
        effect="READ_ONLY",
        request_id=decision.request_id,
        request_digest=_digest(b"devflow-shared-g1-request-v1\0", request),
        backend_candidate=decision.backend,
    )
