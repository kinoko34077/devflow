"""Fixed-reference resolver for a separately protected, explicitly approved host.

Only the host owner supplies the absolute policy path and its trusted SHA-256.
This module is NOT an authentication mechanism or public service. Its output
must not be trusted from a consumer-controlled invocation or checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib

# A protected host may invoke this exact script with Python -I -B. Never
# import policy/implementation from the consumer's current working directory.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ci_github_evidence import (
    FixedSourceRequirement, read_fixed_source_verification,
    valid_fixed_source_requirement,
)
from tools.devflow_mcp_core import GitHubReader

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TREE = re.compile(r"[0-9a-f]{40}\Z")
_MAX_POLICY_BYTES = 64 * 1024
_FIELDS = frozenset({
    "repository", "repository_id", "channel", "commit", "tree_sha",
    "branch", "workflow_id", "workflow_path", "required_jobs",
})


def _blocked(reason: str) -> dict:
    return {"status": "BLOCKED", "reason": reason}


def resolve_fixed_reference(
    reader: GitHubReader, policy_bytes: bytes, approved_digest: str,
    *, repository: str, channel: str, policy_revision: str, pinned_commit: str = "",
) -> dict:
    """Resolve a fixed policy entry and current native evidence, or deny.

    The caller must independently establish that the policy digest and bytes
    are approved, the implementation is trusted, and the host is protected.
    Native success alone never adds a policy entry. No automatic OFFLINE.
    """
    if (type(policy_bytes) is not bytes or not 0 < len(policy_bytes) <= _MAX_POLICY_BYTES
            or type(approved_digest) is not str or not _DIGEST.fullmatch(approved_digest)
            or policy_revision != approved_digest
            or hashlib.sha256(policy_bytes).hexdigest() != approved_digest):
        return _blocked("HOST_POLICY_IDENTITY_MISMATCH")
    if (type(repository) is not str or type(channel) is not str
            or type(pinned_commit) is not str
            or pinned_commit and not _TREE.fullmatch(pinned_commit)):
        return _blocked("REFERENCE_REQUEST_INVALID")
    try:
        policy = tomllib.loads(policy_bytes.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        return _blocked("HOST_POLICY_INVALID")
    if (set(policy) != {"schema_version", "sources"}
            or type(policy["schema_version"]) is not int or policy["schema_version"] != 1
            or type(policy["sources"]) is not list or not policy["sources"]):
        return _blocked("HOST_POLICY_INVALID")
    entries = {}
    for source in policy["sources"]:
        if (type(source) is not dict or set(source) != _FIELDS
                or type(source["required_jobs"]) is not list
                or type(source["tree_sha"]) is not str or not _TREE.fullmatch(source["tree_sha"])):
            return _blocked("HOST_POLICY_INVALID")
        required = FixedSourceRequirement(
            repository=source["repository"], repository_id=source["repository_id"],
            channel=source["channel"], policy_revision=approved_digest,
            commit=source["commit"], branch=source["branch"],
            workflow_id=source["workflow_id"], workflow_path=source["workflow_path"],
            required_jobs=tuple(source["required_jobs"]),
        )
        if not valid_fixed_source_requirement(required):
            return _blocked("HOST_POLICY_INVALID")
        key = (required.repository, required.channel)
        if key in entries:
            return _blocked("HOST_POLICY_SOURCE_AMBIGUOUS")
        entries[key] = (required, source["tree_sha"])
    entry = entries.get((repository, channel))
    if entry is None:
        return _blocked("REFERENCE_SOURCE_NOT_APPROVED")
    required, tree = entry
    if pinned_commit and pinned_commit != required.commit:
        return _blocked("REFERENCE_PIN_NOT_APPROVED")

    evidence = read_fixed_source_verification(reader, required)
    if evidence.get("status") != "NATIVE_SOURCE_CANDIDATE":
        return _blocked("REFERENCE_NATIVE_EVIDENCE_UNAVAILABLE")
    if evidence.get("tree_sha") != tree:
        return _blocked("REFERENCE_TREE_MISMATCH")
    # The fixed approved entry + current native evidence, not a generic run
    # success, is the resolution. Base separately verifies the Git snapshot.
    return {
        "status": "RESOLVED", "repository": required.repository,
        "repository_id": required.repository_id, "channel": required.channel,
        "policy_revision": approved_digest, "commit": required.commit,
        "mode": "CURRENT", "tree_sha": tree,
        "source_ref": evidence["source_ref"],
        "requires_source_revalidation": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # These first two values are protected-profile configuration, not request
    # fields. A caller controlling them is outside the trusted host contract.
    parser.add_argument("--host-policy", type=Path, required=True)
    parser.add_argument("--approved-digest", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--policy-revision", required=True)
    parser.add_argument("--pin", default="")
    args = parser.parse_args(argv)
    try:
        if not args.host_policy.is_absolute() or not args.host_policy.is_file():
            result = _blocked("HOST_POLICY_UNAVAILABLE")
        else:
            with args.host_policy.open("rb") as stream:
                raw = stream.read(_MAX_POLICY_BYTES + 1)
            result = resolve_fixed_reference(
                GitHubReader.from_env(), raw, args.approved_digest,
                repository=args.repository, channel=args.channel,
                policy_revision=args.policy_revision, pinned_commit=args.pin,
            )
    except OSError:
        result = _blocked("HOST_POLICY_UNAVAILABLE")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "RESOLVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
