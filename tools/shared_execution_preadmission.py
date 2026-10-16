"""M4-A principal/evidence PRE-admission ONLY: a typed, zero-effect projection.

A parsed GitHub comment, caller-controlled principal kind/ID, OIDC-shaped blob,
token-shaped string, or apparent receipt is *not* an authenticated principal.
This file cannot mint a capability, read credentials, issue a Claim, dispatch,
or attest an executor. Runtime user-to-server GET /user and installation/OIDC
verification remain separately approved G2B0/#541 responsibilities.

Owner: devflow#659; integration: #639; parent gateway: #541.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from tools.safe_dispatch_contract import parse_json_object

_SCHEMA = "devflow.shared-principal-preadmission.v1"
_KIND = frozenset({
    "USER_DELEGATED",
    "APP_INSTALLATION_MACHINE",
    "ACTIONS_OIDC",
    "LOCAL_UNVERIFIED",
})
_REQUIRED = frozenset({
    "schema", "asserted_kind", "asserted_principal_id", "target_repository_id",
    "request_id", "request_sha256", "source_sha", "catalog_sha256",
    "nonce", "issued_at", "expires_at", "effect",
})
_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z", re.ASCII)
_SHA1 = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_NONCE = re.compile(r"[A-Za-z0-9_.:-]{16,128}\Z", re.ASCII)
_MAX_BYTES = 4096


@dataclass(frozen=True)
class UntrustedPrincipalProjection:
    """A serializable *untrusted* hint, never a verified issuer/authorization."""
    schema: str = _SCHEMA
    status: str = "HOLD"
    reason: str = "INVALID_OR_UNTRUSTED"
    asserted_kind: str | None = None
    asserted_principal_id: int | None = None
    target_repository_id: int | None = None
    request_id: str | None = None
    claim_digest: str | None = None
    authenticated: bool = False
    issuer_verified: bool = False
    catalog_verified: bool = False
    clock_verified: bool = False
    source_verified: bool = False
    claim_authority: bool = False
    github_check_authority: bool = False
    execution_verified: bool = False


def project_untrusted_principal(raw: str) -> UntrustedPrincipalProjection:
    """Check a future-auth-adapter's *untrusted* transport hints, without I/O.

    The caller selects all input values, including the asserted kind, numeric
    identity and timestamps. Thus even a syntactically accepted object remains
    PROTOCOL_ONLY. This is NOT a trusted clock/issuer/source/receipt adapter.
    """
    if type(raw) is not str:
        return UntrustedPrincipalProjection(reason="INVALID_INPUT_TYPE")
    try:
        doc = parse_json_object(raw, max_bytes=_MAX_BYTES)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return UntrustedPrincipalProjection(reason="STRICT_JSON_DENIED")

    if frozenset(doc) != _REQUIRED or doc.get("schema") != _SCHEMA:
        return UntrustedPrincipalProjection(reason="UNKNOWN_PROTOCOL_SHAPE")
    if type(doc["asserted_kind"]) is not str or doc["asserted_kind"] not in _KIND:
        return UntrustedPrincipalProjection(reason="INVALID_PRINCIPAL_KIND")
    if not all(type(doc[f]) is int and doc[f] > 0
               for f in ("asserted_principal_id", "target_repository_id")):
        return UntrustedPrincipalProjection(reason="INVALID_NUMERIC_IDS")
    if (type(doc["request_id"]) is not str
            or _ID.fullmatch(doc["request_id"]) is None
            or type(doc["nonce"]) is not str
            or _NONCE.fullmatch(doc["nonce"]) is None
            or type(doc["request_sha256"]) is not str
            or _SHA256.fullmatch(doc["request_sha256"]) is None
            or type(doc["source_sha"]) is not str
            or _SHA1.fullmatch(doc["source_sha"]) is None
            or type(doc["catalog_sha256"]) is not str
            or _SHA256.fullmatch(doc["catalog_sha256"]) is None):
        return UntrustedPrincipalProjection(reason="INVALID_PINS_OR_REQUEST")
    if (type(doc["issued_at"]) is not int
            or type(doc["expires_at"]) is not int
            or doc["issued_at"] < 1
            or not doc["issued_at"] < doc["expires_at"] <= doc["issued_at"] + 300):
        return UntrustedPrincipalProjection(reason="INVALID_ASSERTED_WINDOW")
    if type(doc["effect"]) is not str or doc["effect"] != "READ_ONLY":
        return UntrustedPrincipalProjection(reason="EFFECT_NOT_SUPPORTED")

    # Bind *asserted* values by domain-separated digest without declaring
    # their truth. No nonce/source/token, private body or raw input is echoed.
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode("ascii")
    digest = sha256(b"devflow-m4a-untrusted-protocol-v1\0" + canonical).hexdigest()
    return UntrustedPrincipalProjection(
        status="PROTOCOL_ONLY",
        reason="ASSERTIONS_PARSED_NOT_AUTHENTICATED",
        asserted_kind=doc["asserted_kind"],
        asserted_principal_id=doc["asserted_principal_id"],
        target_repository_id=doc["target_repository_id"],
        request_id=doc["request_id"],
        claim_digest=digest,
    )
