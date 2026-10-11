"""Pure Git-object/byte provenance proof for a pinned G2B0 operation catalog.

NO network, GitHub credential, protected-branch attestation or execution here.
Caller MUST independently authenticate source repository numeric ID, verify
trusted reviewed build-time pins and connector transport before using output.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1, sha256
import re
from typing import Any, Mapping

from tools.safe_dispatch_contract import _valid_catalog, parse_json_object

_OID = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}\Z")
_MAX_TREE = 524288
_MAX_ENTRIES = 2048
_MAX_COMMIT = 32768
_MAX_CATALOG = 8192


@dataclass(frozen=True)
class CatalogSourcePin:
    """Build-time pins. User-supplied instances are NOT a trust root."""
    source_repo_id: int
    commit_sha: str
    catalog_path: str
    blob_sha: str
    content_sha256: str


@dataclass(frozen=True)
class CatalogSourceResult:
    status: str
    reason: str
    catalog: dict[str, Any] | None = None


def _valid_pin(pin: object) -> bool:
    if type(pin) is not CatalogSourcePin:
        return False
    if type(pin.source_repo_id) is not int or pin.source_repo_id <= 0:
        return False
    if any(type(s) is not str for s in (pin.commit_sha, pin.catalog_path, pin.blob_sha, pin.content_sha256)):
        return False
    if not (_OID.fullmatch(pin.commit_sha) and _OID.fullmatch(pin.blob_sha)
            and _DIGEST.fullmatch(pin.content_sha256)):
        return False
    if len(pin.catalog_path) > 256:
        return False
    parts = pin.catalog_path.split("/")
    return 1 <= len(parts) <= 8 and all(
        _SEGMENT.fullmatch(s) is not None
        and s not in (".", "..") and not s.endswith((".", ".lock"))
        for s in parts
    )


def _git_oid(kind: bytes, data: bytes) -> str:
    return sha1(kind + b" " + str(len(data)).encode("ascii") + b"\x00" + data).hexdigest()


def _commit_tree(raw: bytes) -> str | None:
    if len(raw) > _MAX_COMMIT or b"\x00" in raw:
        return None
    headers, sep, _body = raw.partition(b"\n\n")
    if not sep:
        return None
    lines = headers.split(b"\n")
    if not lines or not lines[0].startswith(b"tree "):
        return None
    oid = lines[0][5:]
    if len(oid) != 40 or not _OID.fullmatch(oid.decode("ascii", errors="ignore")):
        return None
    if any(line.startswith(b"tree ") for line in lines[1:]):
        return None
    return oid.decode("ascii")


def _tree_entries(raw: bytes) -> dict[bytes, tuple[bytes, str]] | None:
    if type(raw) is not bytes or len(raw) > _MAX_TREE:
        return None
    out: dict[bytes, tuple[bytes, str]] = {}
    folded: set[bytes] = set()
    pos = 0
    while pos < len(raw):
        end = raw.find(b"\x00", pos)
        if end < 0:
            return None
        field = raw[pos:end]
        mode, sep, name = field.partition(b" ")
        if not sep or not mode or not name or b" " in mode:
            return None
        if mode not in (b"40000", b"100644", b"100755", b"120000", b"160000"):
            return None
        if name in (b".", b"..") or b"/" in name or b"\\" in name:
            return None
        if len(name) > 255 or name in out or name.lower() in folded:
            return None
        folded.add(name.lower())
        pos = end + 1
        if pos + 20 > len(raw):
            return None
        oid = raw[pos:pos+20].hex()
        pos += 20
        out[name] = (mode, oid)
        if len(out) > _MAX_ENTRIES:
            return None
    return out


def verify_catalog_source(
    pin: CatalogSourcePin,
    *,
    commit_bytes: bytes,
    trees_by_oid: Mapping[str, bytes],
    blobs_by_oid: Mapping[str, bytes],
) -> CatalogSourceResult:
    """Match untrusted *already acquired* Git-object bytes to trusted pins.

    This does not obtain/authenticate source bytes, confirm branch protection,
    or prove the pin was actually reviewer-approved. It NEVER grants execution.
    """
    def block(reason: str) -> CatalogSourceResult:
        return CatalogSourceResult("BLOCKED", reason)

    if not _valid_pin(pin):
        return block("INVALID_BUILD_PIN")
    if type(commit_bytes) is not bytes or len(commit_bytes) > _MAX_COMMIT:
        return block("INVALID_COMMIT_BYTES")
    if _git_oid(b"commit", commit_bytes) != pin.commit_sha:
        return block("COMMIT_OID_MISMATCH")
    tree_oid = _commit_tree(commit_bytes)
    if tree_oid is None:
        return block("INVALID_COMMIT_TREE")
    if type(trees_by_oid) is not dict or type(blobs_by_oid) is not dict:
        return block("INVALID_OBJECT_MAP")
    if len(trees_by_oid) > 8 or len(blobs_by_oid) > 1:
        return block("UNEXPECTED_OBJECT_COUNT")
    parts = [s.encode("ascii") for s in pin.catalog_path.split("/")]
    for position, segment in enumerate(parts):
        raw_tree = trees_by_oid.get(tree_oid)
        if type(raw_tree) is not bytes or len(raw_tree) > _MAX_TREE:
            return block("MISSING_OR_LARGE_TREE")
        if _git_oid(b"tree", raw_tree) != tree_oid:
            return block("TREE_OID_MISMATCH")
        entries = _tree_entries(raw_tree)
        if entries is None:
            return block("INVALID_TREE_ENTRIES")
        found = entries.get(segment)
        if found is None:
            return block("CATALOG_PATH_MISSING")
        mode, child_oid = found
        if position < len(parts) - 1:
            if mode != b"40000":
                return block("CATALOG_PARENT_NOT_TREE")
            tree_oid = child_oid
        else:
            if mode != b"100644":
                return block("CATALOG_NOT_REGULAR_FILE")
            if child_oid != pin.blob_sha:
                return block("CATALOG_BLOB_NOT_PINNED")
    blob = blobs_by_oid.get(pin.blob_sha)
    if type(blob) is not bytes or len(blob) > _MAX_CATALOG:
        return block("MISSING_OR_LARGE_CATALOG")
    if _git_oid(b"blob", blob) != pin.blob_sha:
        return block("BLOB_OID_MISMATCH")
    if sha256(blob).hexdigest() != pin.content_sha256:
        return block("CATALOG_SHA256_MISMATCH")
    try:
        catalog = parse_json_object(blob.decode("utf-8"), max_bytes=_MAX_CATALOG)
    except (UnicodeError, ValueError):
        return block("CATALOG_JSON_INVALID")
    if not _valid_catalog(catalog):
        return block("CATALOG_SCHEMA_INVALID")
    return CatalogSourceResult("OFFLINE_SOURCE_MATCHED", "BYTES_MATCH_PINS_NOT_AUTHENTICATED", catalog)
