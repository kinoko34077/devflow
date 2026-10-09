"""Produce a bounded, deterministic ZIP and manifest from fixed generated paths.

This code is read-only to source files. Admission is provided by a trusted
GitHub Actions runner, not by generator output or archive metadata.
"""
import hashlib
import io
import json
import pathlib
import stat
import zipfile
from collections.abc import Mapping

from tools.generated_artifact_contract import ArtifactRejected, _policy, _provenance


def package_approved_outputs(policy: Mapping, admission: Mapping,
                             source_root: pathlib.Path) -> tuple[dict, bytes]:
    p = _policy(dict(policy))
    a = _provenance(dict(admission), "admission")
    if a["repository"] != p["repository"] or a["recipe_id"] != p["recipe"]["id"]:
        raise ArtifactRejected("producer admission does not match approved recipe")
    root = source_root.resolve(strict=True)
    files, blobs = [], {}
    for relative in sorted(p["recipe"]["paths"]):
        path = root / relative
        if path.parent.resolve(strict=True) != path.parent:
            raise ArtifactRejected("unsafe artifact parent directory")
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or mode & 0o111:
            raise ArtifactRejected("generated artifact is not a regular nonexecutable file")
        if path.stat().st_size > p["limits"]["max_file_bytes"]:
            raise ArtifactRejected("generated artifact is too large")
        raw = path.read_bytes()
        if len(raw) > p["limits"]["max_file_bytes"]:
            raise ArtifactRejected("generated artifact bytes exceed limit")
        blobs[relative] = raw
        files.append({"path": relative, "size": len(raw),
                      "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"schema": "generated-artifacts.v1", "provenance": dict(a), "files": files}
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w") as archive:
        for relative, data in sorted(blobs.items()):
            info = zipfile.ZipInfo(relative)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    payload = mem.getvalue()
    if len(payload) > p["limits"]["max_archive_bytes"]:
        raise ArtifactRejected("generated archive exceeds limit")
    return manifest, payload


def canonical_manifest_json(manifest: Mapping) -> bytes:
    return (json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")) + "\n").encode("utf-8")
