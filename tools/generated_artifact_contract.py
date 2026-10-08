"""Fail-closed, read-only generated-artifact inspection and dry-run planning.

No GitHub credentials, network calls, execution of source or archive members, or
write methods are exposed here. The writer must authenticate policy/admission
and observed GitHub state independently before invoking this module.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import zipfile
from collections.abc import Mapping
from typing import Any

POLICY_SCHEMA = "generated-artifacts-policy.v1"
MANIFEST_SCHEMA = "generated-artifacts.v1"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]*\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_PROVENANCE_KEYS = frozenset({
    "repository", "actor", "branch", "expected_head", "source_sha",
    "recipe_id", "recipe_version", "producer_run_id",
    "producer_run_attempt", "producer_workflow_ref",
})
_MAX_FILES_CEILING = 256
_MAX_BYTES_CEILING = 100 * 1024 * 1024
_MAX_RATIO_CEILING = 10000


class ArtifactRejected(ValueError):
    """An untrusted input, observed head or policy failed a v1 invariant."""


def _object(value: Any, name: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ArtifactRejected(f"{name}: invalid object keys")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ArtifactRejected(f"{name}: invalid string")
    return value


def _positive_int(value: Any, name: str, limit: int) -> int:
    if type(value) is not int or not (1 <= value <= limit):
        raise ArtifactRejected(f"{name}: invalid integer or limit")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ArtifactRejected(f"{name}: invalid commit SHA")
    return value


def _path(value: Any) -> str:
    value = _string(value, "path")
    parts = value.split("/")
    if (
        len(value) > 240
        or not _PATH.fullmatch(value)
        or any(p in ("", ".", "..") or p.startswith(".") for p in parts)
        or parts[0].lower() in (".git", ".github")
        or value.endswith("/")
    ):
        raise ArtifactRejected("unsafe or unsupported generated file path")
    return value


def _branch(value: Any) -> str:
    value = _string(value, "branch")
    if (
        len(value) > 200
        or not _BRANCH.fullmatch(value)
        or any(p in ("", ".", "..") or p.startswith(".") for p in value.split("/"))
        or value.endswith(".lock")
    ):
        raise ArtifactRejected("invalid target branch")
    return value


def _policy(raw: Any) -> Mapping[str, Any]:
    p = _object(raw, "policy", {
        "schema", "repository", "allowed_actors", "default_branch",
        "branch_prefix", "forbidden_branches", "recipe",
        "producer_workflow_ref", "limits",
    })
    if p["schema"] != POLICY_SCHEMA:
        raise ArtifactRejected("unsupported policy schema")
    _string(p["repository"], "repository")
    _branch(p["default_branch"])
    prefix = _string(p["branch_prefix"], "branch_prefix")
    if not prefix.endswith("/"):
        raise ArtifactRejected("branch_prefix must terminate with /")
    _branch(prefix[:-1])
    actors = p["allowed_actors"]
    if not isinstance(actors, list) or not actors or len(set(map(str, actors))) != len(actors):
        raise ArtifactRejected("allowed_actors must be a unique nonempty list")
    for actor in actors:
        _string(actor, "allowed actor")
    forbidden = p["forbidden_branches"]
    if not isinstance(forbidden, list) or len(set(map(str, forbidden))) != len(forbidden):
        raise ArtifactRejected("forbidden_branches must be a unique list")
    for name in forbidden:
        _branch(name)
    recipe = _object(p["recipe"], "recipe", {"id", "version", "paths"})
    _string(recipe["id"], "recipe.id")
    _string(recipe["version"], "recipe.version")
    paths = recipe["paths"]
    if not isinstance(paths, list) or not paths or len(paths) > _MAX_FILES_CEILING:
        raise ArtifactRejected("recipe.paths: invalid number of paths")
    normalized = [_path(item) for item in paths]
    if len(set(normalized)) != len(normalized):
        raise ArtifactRejected("recipe.paths: duplicates")
    ref = _string(p["producer_workflow_ref"], "producer_workflow_ref")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml@[0-9a-f]{40}", ref):
        raise ArtifactRejected("producer_workflow_ref must be an exact SHA pin")
    limits = _object(p["limits"], "limits", {
        "max_files", "max_file_bytes", "max_total_bytes",
        "max_archive_bytes", "max_expansion_ratio",
    })
    if _positive_int(limits["max_files"], "max_files", _MAX_FILES_CEILING) < len(paths):
        raise ArtifactRejected("policy allows too few files for its recipe")
    for key in ("max_file_bytes", "max_total_bytes", "max_archive_bytes"):
        _positive_int(limits[key], key, _MAX_BYTES_CEILING)
    _positive_int(limits["max_expansion_ratio"], "max_expansion_ratio", _MAX_RATIO_CEILING)
    if limits["max_file_bytes"] > limits["max_total_bytes"]:
        raise ArtifactRejected("max_file_bytes exceeds max_total_bytes")
    return p


def _provenance(raw: Any, name: str) -> Mapping[str, Any]:
    a = _object(raw, name, set(_PROVENANCE_KEYS))
    for key in ("repository", "actor", "recipe_id", "recipe_version"):
        _string(a[key], name + "." + key)
    _branch(a["branch"])
    _sha(a["expected_head"], name + ".expected_head")
    _sha(a["source_sha"], name + ".source_sha")
    _positive_int(a["producer_run_id"], name + ".producer_run_id", 10**16)
    _positive_int(a["producer_run_attempt"], name + ".producer_run_attempt", 1000000)
    _string(a["producer_workflow_ref"], name + ".producer_workflow_ref")
    return a


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Diagnostic digest, not a producer signature or authorization proof."""
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def validate_and_plan(
    policy: Mapping[str, Any],
    admission: Mapping[str, Any],
    manifest: Mapping[str, Any],
    archive_bytes: bytes,
    *,
    observed_head: str,
    existing_files: Mapping[str, bytes | None],
) -> dict[str, Any]:
    """Validate every archive byte against trusted policy/admission/observations.

    Policy, admission, observed_head and existing_files MUST originate from
    independently authenticated trusted caller / GitHub reads, never the
    producer manifest or ZIP. A successful plan DOES NOT authorize or perform a
    push; a future writer must recheck head and use a non-force CAS update.
    """
    p = _policy(policy)
    a = _provenance(admission, "admission")
    m = _object(manifest, "manifest", {"schema", "provenance", "files"})
    if m["schema"] != MANIFEST_SCHEMA:
        raise ArtifactRejected("unsupported manifest schema")
    mp = _provenance(m["provenance"], "manifest.provenance")
    if dict(mp) != dict(a):
        raise ArtifactRejected("producer manifest provenance does not match trusted admission")
    if (
        a["repository"] != p["repository"]
        or a["actor"] not in p["allowed_actors"]
        or a["recipe_id"] != p["recipe"]["id"]
        or a["recipe_version"] != p["recipe"]["version"]
        or a["producer_workflow_ref"] != p["producer_workflow_ref"]
    ):
        raise ArtifactRejected("repository, actor, recipe or workflow not allowed")
    if (
        a["branch"] == p["default_branch"]
        or a["branch"] in p["forbidden_branches"]
        or not a["branch"].startswith(p["branch_prefix"])
        or a["branch"] == p["branch_prefix"]
    ):
        raise ArtifactRejected("target branch is forbidden or outside approved prefix")
    if _sha(observed_head, "observed_head") != a["expected_head"]:
        raise ArtifactRejected("target branch head moved: retry requires new admission")
    if not isinstance(archive_bytes, bytes):
        raise ArtifactRejected("archive must be exact bytes")
    limits = p["limits"]
    if len(archive_bytes) > limits["max_archive_bytes"]:
        raise ArtifactRejected("archive exceeds byte limit")
    items = m["files"]
    if not isinstance(items, list) or len(items) != len(p["recipe"]["paths"]):
        raise ArtifactRejected("manifest file count differs from exact approved path set")
    expected: dict[str, dict[str, Any]] = {}
    total = 0
    for i, item in enumerate(items):
        f = _object(item, f"manifest.files[{i}]", {"path", "size", "sha256"})
        path = _path(f["path"])
        size = _positive_int(f["size"], "size", limits["max_file_bytes"])
        digest = f["sha256"]
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise ArtifactRejected("invalid manifest sha256")
        if path in expected:
            raise ArtifactRejected("duplicate manifest path")
        expected[path] = dict(f)
        total += size
        if total > limits["max_total_bytes"]:
            raise ArtifactRejected("manifest total bytes over limit")
    allowed = set(p["recipe"]["paths"])
    if set(expected) != allowed or len(expected) > limits["max_files"]:
        raise ArtifactRejected("unknown/omitted manifest generated paths")
    if not isinstance(existing_files, Mapping) or not set(existing_files).issubset(allowed):
        raise ArtifactRejected("existing_files includes unknown paths")
    for path, value in existing_files.items():
        if value is not None and not isinstance(value, bytes):
            raise ArtifactRejected(f"existing_files[{path}]: expected bytes or None")
    actual: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r", allowZip64=True) as archive:
            entries = archive.infolist()
            if len(entries) != len(expected):
                raise ArtifactRejected("ZIP entry count mismatch")
            seen: set[str] = set()
            for info in entries:
                path = _path(info.filename)
                if path in seen or path not in expected or info.is_dir():
                    raise ArtifactRejected("duplicate, directory, or unapproved ZIP entry")
                seen.add(path)
                mode = stat.S_IFMT(info.external_attr >> 16)
                if mode not in (0, stat.S_IFREG):
                    raise ArtifactRejected("archive contains symlink/special file")
                if info.flag_bits & 1:
                    raise ArtifactRejected("encrypted ZIP entries are unsupported")
                if (
                    info.file_size != expected[path]["size"]
                    or info.file_size > limits["max_file_bytes"]
                    or info.file_size > max(1, info.compress_size) * limits["max_expansion_ratio"]
                ):
                    raise ArtifactRejected("ZIP declared size or expansion limit rejected")
                with archive.open(info, "r") as member:
                    data = member.read(limits["max_file_bytes"] + 1)
                    if len(data) != info.file_size or member.read(1):
                        raise ArtifactRejected("ZIP actual member size mismatch")
                if hashlib.sha256(data).hexdigest() != expected[path]["sha256"]:
                    raise ArtifactRejected("ZIP content digest mismatch")
                actual[path] = data
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, EOFError, OSError) as exc:
        raise ArtifactRejected("invalid or unreadable ZIP archive") from exc
    if set(actual) != allowed:
        raise ArtifactRejected("ZIP missing expected generated paths")
    changes = [
        {"path": path, "size": len(actual[path]), "sha256": expected[path]["sha256"]}
        for path in sorted(actual)
        if existing_files.get(path) != actual[path]
    ]
    return {
        "schema": "generated-artifacts-plan.v1",
        "status": "CHANGE" if changes else "NO_OP",
        "repository": a["repository"],
        "target_branch": a["branch"],
        "expected_head": a["expected_head"],
        "producer_run_id": a["producer_run_id"],
        "manifest_sha256": manifest_digest(m),
        "file_count": len(actual),
        "total_bytes": total,
        "changes": changes,
        "writes_performed": False,
    }
