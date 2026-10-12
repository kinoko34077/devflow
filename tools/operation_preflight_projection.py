"""Non-authorizing projection of #465's authenticated read-only artifact preview.

This module has no network transport, credential, GitHub mutation or execution
entrypoint. Callers must independently authenticate policy/admission and
revalidate the real target with an operation-specific writer. A projection or
digest produced here is NEVER an approval, an actor attestation, or a write grant.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from tools.safe_dispatch_contract import parse_json_object

SCHEMA = "operation-preflight-projection.v0"
_PREVIEW_SCHEMA = "generated-artifacts-plan.v1"
_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z", re.ASCII)
_PREVIEW_KEYS = frozenset({
    "schema", "status", "repository", "target_branch", "expected_head",
    "producer_run_id", "manifest_sha256", "file_count", "total_bytes",
    "changes", "writes_performed", "target_head", "ci_verified",
    "writer_authorized", "auth_status",
})
_CHANGE_KEYS = frozenset({"path", "size", "sha256"})


class ProjectionRejected(ValueError):
    """Invalid or falsely privileged read-only evidence shape."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ProjectionRejected(reason)


def _exact_sha(value: Any, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def project_artifact_preview(
    preview_json: str,
    *,
    trusted_policy: Mapping[str, Any],
    trusted_admission: Mapping[str, Any],
    request_id: str,
    catalog_source_sha: str,
) -> dict[str, Any]:
    """Validate and project a #465 preview; do not authenticate or authorize it.

    trusted_policy/admission MUST originate from the existing trusted #465
    caller's independently authenticated path, not request/manifest/Issue JSON.
    Accepting these parameters does not verify the provenance of their source.
    This function only recognizes the narrow #465 dry-run/NO_OP payload.
    """
    _require(_exact_sha(catalog_source_sha, _SHA), "unverified catalog SHA shape")
    _require(type(request_id) is str and _REQUEST_ID.fullmatch(request_id) is not None,
             "invalid request id")
    _require(isinstance(trusted_policy, Mapping) and
             isinstance(trusted_admission, Mapping), "missing trusted input mappings")

    try:
        preview = parse_json_object(preview_json, max_bytes=131072)
    except (ValueError, UnicodeError) as exc:
        raise ProjectionRejected("invalid bounded read-only preview JSON") from exc
    _require(frozenset(preview) == _PREVIEW_KEYS, "unexpected preview shape")
    _require(preview["schema"] == _PREVIEW_SCHEMA, "incorrect native plan schema")
    _require(preview["status"] in ("DRY_RUN", "NO_OP"), "not a read-only preview status")
    _require(preview["writes_performed"] is False and
             preview["writer_authorized"] is False and
             preview["ci_verified"] is False and
             preview["auth_status"] == "AUTHENTICATED_READ_ONLY",
             "preview advertises privileged, unverified or effectful state")

    recipe = trusted_policy.get("recipe")
    limits = trusted_policy.get("limits")
    _require(isinstance(recipe, Mapping) and isinstance(limits, Mapping),
             "invalid trusted policy")
    paths = recipe.get("paths")
    _require(type(paths) in (tuple, list) and 0 < len(paths) <= 256 and
             all(type(p) is str and p for p in paths) and
             len(set(paths)) == len(paths), "invalid approved path set")
    _require(type(trusted_policy.get("repository")) is str and
             preview["repository"] == trusted_policy["repository"] ==
             trusted_admission.get("repository"), "repository mismatch")
    _require(preview["target_branch"] == trusted_admission.get("branch") and
             type(preview["target_branch"]) is str and
             preview["target_branch"] != trusted_policy.get("default_branch") and
             preview["target_branch"].startswith(
                 trusted_policy.get("branch_prefix", "\0")
             ), "target branch mismatch")
    _require(_exact_sha(preview["expected_head"], _SHA) and
             preview["expected_head"] == preview["target_head"] ==
             trusted_admission.get("expected_head"), "observed target head mismatch")
    _require(recipe.get("id") == trusted_admission.get("recipe_id") and
             recipe.get("version") == trusted_admission.get("recipe_version"),
             "recipe/version mismatch")
    _require(trusted_admission.get("actor") in trusted_policy.get("allowed_actors", ()),
             "actor outside trusted recipe policy")
    _require(trusted_admission.get("producer_workflow_ref") ==
             trusted_policy.get("producer_workflow_ref"),
             "untrusted producer workflow")
    _require(type(preview["producer_run_id"]) is int and
             preview["producer_run_id"] > 0 and
             preview["producer_run_id"] == trusted_admission.get("producer_run_id"),
             "producer run mismatch")
    _require(_exact_sha(preview["manifest_sha256"], _DIGEST),
             "invalid manifest digest shape")
    _require(type(preview["file_count"]) is int and
             preview["file_count"] == len(paths), "file count mismatch")

    total = preview["total_bytes"]
    ceiling = limits.get("max_total_bytes")
    max_file = limits.get("max_file_bytes")
    _require(type(ceiling) is int and type(max_file) is int and
             ceiling > 0 and max_file > 0 and
             type(total) is int and 0 <= total <= ceiling,
             "total bytes exceeds trusted limits")
    changes = preview["changes"]
    _require(type(changes) is list and len(changes) <= len(paths),
             "invalid change list")
    allowed = set(paths)
    change_paths = []
    total_changed = 0
    for item in changes:
        _require(type(item) is dict and frozenset(item) == _CHANGE_KEYS,
                 "invalid change record")
        path = item["path"]
        size = item["size"]
        _require(type(path) is str and path in allowed, "path outside trusted allowlist")
        _require(type(size) is int and 0 <= size <= max_file,
                 "file size exceeds trusted limit")
        _require(_exact_sha(item["sha256"], _DIGEST), "invalid file digest")
        change_paths.append(path)
        total_changed += size
    _require(change_paths == sorted(set(change_paths)),
             "non-canonical or duplicate changed paths")
    _require(total_changed <= total, "changed bytes exceed entire archive")
    _require((preview["status"] == "DRY_RUN") == bool(changes),
             "dry-run/NO_OP change mismatch")

    # Only a canonical, bounded diagnostic projection. No bearer capability,
    # access token, expiry-based approval, runner authentication or write flag.
    evidence = {
        "schema": SCHEMA,
        "request_id": request_id,
        "catalog_source_sha": catalog_source_sha,
        "operation": "generated_artifact.readonly_preview@1",
        "repository": trusted_policy["repository"],
        "recipe_id": recipe["id"],
        "recipe_version": recipe["version"],
        "target_branch": preview["target_branch"],
        "observed_head": preview["target_head"],
        "producer_run_id": preview["producer_run_id"],
        "native_status": preview["status"],
        "manifest_sha256": preview["manifest_sha256"],
        "approved_paths": sorted(paths),
        "file_count": preview["file_count"],
        "total_bytes": total,
        "changes": [dict(item) for item in changes],
        "effect_authorized": False,
        "writes_performed": False,
        "requires_fresh_writer_revalidation": True,
        "trust_status": "PROJECTION_ONLY_UNAUTHENTICATED",
    }
    # Digest only detects report modifications; it does NOT establish a signer.
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    evidence["diagnostic_sha256"] = hashlib.sha256(encoded).hexdigest()
    return evidence
