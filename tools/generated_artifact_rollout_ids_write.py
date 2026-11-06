"""IDS W1.4 writer boundary (pre-activation, fail-closed).

No workflow currently calls this module. A separate reviewed admission and
immutable pinned workflow are required before effectful execution.
"""
from __future__ import annotations

import base64
import json
import pathlib
import re
import urllib.parse
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import ARCHIVE_NAME, MANIFEST_NAME, fixed_policy
from tools.generated_artifact_rollout_admission import CALLER_PATH, attest_authenticated_readonly
from tools.generated_artifact_rollout_dryrun import MANIFEST_CEILING, _read_regular_bounded
from tools.generated_artifact_writer import verified_writeback

REPOSITORY = "kinoko34077/IDS-Composit"
RECIPE = "ids-known-merge-v0.2"
BRANCH_PREFIX = "artifact/writeback-ids/"
OUTPUTS = frozenset({
    "data/known/generated/known-index-v0.2.json",
    "data/known/reports/known-index-v0.2.json",
})
MAX_FILE_BYTES = 24 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_ENCODED_FILE_BYTES = ((MAX_FILE_BYTES + 2) // 3) * 4
_SHA = re.compile(r"[0-9a-f]{40}")
# Deliberately not activated: the current admission verifier rejects IDS write.
WRITER_ACTIVATED = False


def _is_target_branch(branch: str) -> bool:
    if not isinstance(branch, str) or not re.fullmatch(
        r"artifact/writeback-ids/[A-Za-z0-9][A-Za-z0-9._-]*", branch
    ):
        return False
    name = branch[len(BRANCH_PREFIX):]
    return (
        ".." not in name
        and "@{" not in name
        and not name.endswith(".")
        and not name.lower().endswith(".lock")
    )


def validate_target(repository: str, recipe: str, branch: str, expected_head: str) -> None:
    if (repository, recipe) != (REPOSITORY, RECIPE):
        raise ArtifactRejected("IDS writer repository or recipe mismatch")
    if not _is_target_branch(branch):
        raise ArtifactRejected("IDS writer target must be an admitted scratch branch")
    if not isinstance(expected_head, str) or not _SHA.fullmatch(expected_head):
        raise ArtifactRejected("IDS writer expected HEAD must be an exact SHA")


def validate_outputs(outputs: Mapping[str, bytes]) -> None:
    if (
        not isinstance(outputs, Mapping)
        or not outputs
        or any(not isinstance(path, str) for path in outputs)
        or not set(outputs).issubset(OUTPUTS)
    ):
        raise ArtifactRejected("IDS writer output paths must be a non-empty subset of the fixed recipe")
    total = 0
    for payload in outputs.values():
        if not isinstance(payload, bytes) or len(payload) > MAX_FILE_BYTES:
            raise ArtifactRejected("IDS writer file is not bounded bytes")
        total += len(payload)
    if total > MAX_TOTAL_BYTES:
        raise ArtifactRejected("IDS writer combined output exceeds size ceiling")


def validate_policy(policy: Mapping[str, Any]) -> None:
    """Reject any widening of the reviewed static IDS recipe before planning."""
    if not isinstance(policy, Mapping) or policy.get("repository") != REPOSITORY:
        raise ArtifactRejected("IDS writer policy repository mismatch")
    workflow_prefix = f"{REPOSITORY}/{CALLER_PATH}@"
    workflow_ref = policy.get("producer_workflow_ref")
    if not isinstance(workflow_ref, str) or not workflow_ref.startswith(workflow_prefix):
        raise ArtifactRejected("IDS writer policy workflow pin mismatch")
    workflow_sha = workflow_ref[len(workflow_prefix):]
    if not _SHA.fullmatch(workflow_sha) or policy != fixed_policy(REPOSITORY, RECIPE, workflow_sha):
        raise ArtifactRejected("IDS writer policy differs from the fixed IDS recipe")


class NarrowIdsWriteApi:
    """Minimal Git object write surface; never permits default-branch mutation."""

    def __init__(self, transport: Any, branch: str, expected_head: str):
        validate_target(getattr(transport, "repository", ""), RECIPE, branch, expected_head)
        self.repository = REPOSITORY
        self._transport = transport
        self._branch = branch
        self._patch_ref = "/git/refs/heads/" + urllib.parse.quote(branch, safe="/")
        self._expected_head = expected_head
        self._expected_tree_sha: str | None = None
        self._branch_head: str | None = None
        self._created_blobs: dict[str, tuple[str, bytes]] = {}
        self._blob_attempted_paths: set[str] = set()
        self._created_tree_sha: str | None = None
        self._tree_creation_attempted = False
        self._created_commit_sha: str | None = None
        self._commit_creation_attempted = False
        self._ref_update_attempted = False
        self._created_total_bytes = 0

    def get(self, path: str) -> Any:
        if not isinstance(path, str):
            raise ArtifactRejected("IDS writer unadmitted read endpoint")
        expected_pulls = "/pulls?state=open&head=" + urllib.parse.quote(
            REPOSITORY.split("/")[0] + ":" + self._branch, safe=""
        )
        allowed = path in ("", "/rulesets", "/branches/main", "/branches/" + self._branch, expected_pulls)
        allowed = allowed or bool(re.fullmatch(r"/actions/runs/[0-9]+", path))
        allowed = allowed or bool(re.fullmatch(r"/actions/workflows/[0-9]+", path))
        allowed = allowed or bool(re.fullmatch(
            re.escape(f"/contents/{CALLER_PATH}?ref=") + r"[0-9a-f]{40}", path
        ))
        allowed = allowed or bool(re.fullmatch(r"/git/commits/[0-9a-f]{40}", path))
        allowed = allowed or bool(re.fullmatch(r"/git/trees/[0-9a-f]{40}", path))
        allowed = allowed or bool(re.fullmatch(r"/git/blobs/[0-9a-f]{40}", path))
        allowed = allowed or bool(re.fullmatch(r"/compare/[0-9a-f]{40}\.{3}[0-9a-f]{40}", path))
        if not allowed:
            raise ArtifactRejected("IDS writer unadmitted read endpoint")
        result = self._transport.get(path)
        if path == "/branches/" + self._branch and WRITER_ACTIVATED:
            commit = result.get("commit") if isinstance(result, Mapping) else None
            head = commit.get("sha") if isinstance(commit, Mapping) else None
            if (
                not isinstance(result, Mapping)
                or result.get("protected") is not False
                or not isinstance(head, str)
                or not _SHA.fullmatch(head)
            ):
                raise ArtifactRejected("IDS writer target branch state cannot be verified")
            if self._ref_update_attempted and head != self._created_commit_sha:
                raise ArtifactRejected("IDS writer post-update branch head differs from its commit")
            self._branch_head = head
        if path == f"/git/commits/{self._expected_head}":
            tree = result.get("tree") if isinstance(result, Mapping) else None
            tree_sha = tree.get("sha") if isinstance(tree, Mapping) else None
            if (
                not isinstance(result, Mapping)
                or result.get("sha") != self._expected_head
                or not isinstance(tree_sha, str)
                or not _SHA.fullmatch(tree_sha)
            ):
                raise ArtifactRejected("IDS writer expected-head tree cannot be verified")
            if WRITER_ACTIVATED and self._branch_head != self._expected_head:
                raise ArtifactRejected("IDS writer target branch was not verified at the expected HEAD")
            self._expected_tree_sha = tree_sha
        return result

    def post_blob_for_path(self, output_path: str, payload: Mapping[str, Any]) -> Any:
        """Create one bounded blob while retaining its validated recipe path."""
        if not WRITER_ACTIVATED:
            raise ArtifactRejected("IDS privileged writer not activated")
        if (
            not isinstance(output_path, str)
            or output_path not in OUTPUTS
            or self._branch_head != self._expected_head
            or self._expected_tree_sha is None
            or self._tree_creation_attempted
            or self._created_tree_sha is not None
            or self._commit_creation_attempted
            or self._ref_update_attempted
            or output_path in self._blob_attempted_paths
            or len(self._created_blobs) >= len(OUTPUTS)
        ):
            raise ArtifactRejected("IDS writer blob path or mutation stage is not admitted")
        decoded = self._decode_blob_payload(payload)
        self._blob_attempted_paths.add(output_path)
        result = self._transport.post("/git/blobs", dict(payload))
        sha = result.get("sha") if isinstance(result, Mapping) else None
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ArtifactRejected("IDS writer created blob SHA cannot be verified")
        self._created_blobs[output_path] = (sha, decoded)
        self._created_total_bytes += len(decoded)
        return result

    def _decode_blob_payload(self, payload: Mapping[str, Any]) -> bytes:
        if not isinstance(payload, Mapping):
            raise ArtifactRejected("IDS writer blob payload must be an object")
        content = payload.get("content")
        if (
            set(payload) != {"content", "encoding"}
            or payload.get("encoding") != "base64"
            or not isinstance(content, str)
            or len(content) > MAX_ENCODED_FILE_BYTES
        ):
            raise ArtifactRejected("IDS writer blob payload is not an admitted bounded base64 object")
        try:
            decoded = base64.b64decode(content, validate=True)
        except (ValueError, TypeError) as exc:
            raise ArtifactRejected("IDS writer blob is not strict base64") from exc
        if (
            base64.b64encode(decoded).decode("ascii") != content
            or len(decoded) > MAX_FILE_BYTES
            or self._created_total_bytes + len(decoded) > MAX_TOTAL_BYTES
        ):
            raise ArtifactRejected("IDS writer blob exceeds fixed output size limits")
        return decoded

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        if not WRITER_ACTIVATED:
            raise ArtifactRejected("IDS privileged writer not activated")
        if path == "/git/blobs":
            raise ArtifactRejected("IDS writer blob creation requires its fixed output path")
        if path not in ("/git/trees", "/git/commits") or not isinstance(payload, Mapping):
            raise ArtifactRejected("IDS writer unadmitted Git mutation")
        if path == "/git/trees":
            entries = payload.get("tree")
            if (
                set(payload) != {"base_tree", "tree"}
                or self._branch_head != self._expected_head
                or self._expected_tree_sha is None
                or payload.get("base_tree") != self._expected_tree_sha
                or not isinstance(entries, list)
                or not entries
                or self._tree_creation_attempted
                or self._created_tree_sha is not None
                or self._commit_creation_attempted
                or self._ref_update_attempted
                or len(entries) != len(self._created_blobs)
                or len(entries) > len(OUTPUTS)
            ):
                raise ArtifactRejected("IDS writer tree is not based on the verified target tree")
            seen_paths: set[str] = set()
            output_bytes = {}
            for entry in entries:
                if not isinstance(entry, Mapping) or set(entry) != {"path", "mode", "type", "sha"}:
                    raise ArtifactRejected("IDS writer tree entry shape is invalid")
                entry_path = entry.get("path")
                sha = entry.get("sha")
                if (
                    not isinstance(entry_path, str)
                    or entry_path not in OUTPUTS
                    or entry_path in seen_paths
                    or entry.get("mode") != "100644"
                    or entry.get("type") != "blob"
                    or not isinstance(sha, str)
                    or entry_path not in self._created_blobs
                    or sha != self._created_blobs[entry_path][0]
                ):
                    raise ArtifactRejected("IDS writer tree contains an unapproved path or blob")
                seen_paths.add(entry_path)
                output_bytes[entry_path] = self._created_blobs[entry_path][1]
            if seen_paths != set(self._created_blobs):
                raise ArtifactRejected("IDS writer tree must include every created blob exactly once")
            validate_outputs(output_bytes)
            self._tree_creation_attempted = True
            result = self._transport.post(path, dict(payload))
            sha = result.get("sha") if isinstance(result, Mapping) else None
            if not isinstance(sha, str) or not _SHA.fullmatch(sha):
                raise ArtifactRejected("IDS writer created tree SHA cannot be verified")
            self._created_tree_sha = sha
            return result

        if (
            set(payload) != {"message", "tree", "parents"}
            or not isinstance(payload.get("message"), str)
            or not payload["message"]
            or len(payload["message"]) > 8192
            or self._branch_head != self._expected_head
            or payload.get("tree") != self._created_tree_sha
            or self._created_tree_sha is None
            or payload.get("parents") != [self._expected_head]
            or self._commit_creation_attempted
            or self._ref_update_attempted
        ):
            raise ArtifactRejected("IDS writer commit does not match the verified tree and expected parent")
        self._commit_creation_attempted = True
        result = self._transport.post(path, dict(payload))
        sha = result.get("sha") if isinstance(result, Mapping) else None
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ArtifactRejected("IDS writer created commit SHA cannot be verified")
        self._created_commit_sha = sha
        return result

    def patch(self, path: str, payload: Mapping[str, Any]) -> Any:
        if not WRITER_ACTIVATED:
            raise ArtifactRejected("IDS privileged writer not activated")
        if (
            path != self._patch_ref
            or not isinstance(payload, Mapping)
            or set(payload) != {"sha", "force"}
            or payload.get("force") is not False
            or self._created_commit_sha is None
            or payload.get("sha") != self._created_commit_sha
            or self._branch_head != self._expected_head
            or self._ref_update_attempted
        ):
            raise ArtifactRejected("IDS writer allows only non-force scratch branch updates")
        self._ref_update_attempted = True
        return self._transport.patch(path, dict(payload))

def plan_ids_scoped_write(
    api: Any, env: Mapping[str, str], artifact_dir: pathlib.Path, *,
    target_branch: str, expected_head: str, devflow_sha: str,
    devflow_checkout_sha: str,
) -> dict[str, Any]:
    """Authenticate and plan IDS two-file writeback, without any mutation.

    This is the independently usable read-only prerequisite for a future
    reviewed effectful job. Neither a request field nor an environment variable
    can activate the dormant writer; activation remains a reviewed code change.
    """
    validate_target(getattr(api, "repository", ""), RECIPE, target_branch, expected_head)
    if env.get("MODE") != "dry-run" or env.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ArtifactRejected("IDS planning requires authenticated dry-run context")
    scoped = NarrowIdsWriteApi(api, target_branch, expected_head)
    auth = attest_authenticated_readonly(
        scoped, env, repository=REPOSITORY, recipe_id=RECIPE,
        target_branch=target_branch, expected_head=expected_head,
        source_head=expected_head, devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
    )
    policy = auth["policy"]
    validate_policy(policy)
    main = scoped.get("/branches/main")
    if not isinstance(main, dict) or main.get("name") != "main" or main.get("protected") is not True:
        raise ArtifactRejected("IDS main protection cannot be verified")
    try:
        manifest = json.loads(_read_regular_bounded(
            artifact_dir / MANIFEST_NAME, MANIFEST_CEILING,
        ).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactRejected("IDS manifest is not strict JSON") from exc
    archive = _read_regular_bounded(
        artifact_dir / ARCHIVE_NAME, policy["limits"]["max_archive_bytes"],
    )
    result = verified_writeback(
        scoped, policy, auth["admission"], manifest, archive, dry_run=True,
    )
    return {**result, "writer_scope": REPOSITORY, "writes_performed": False,
            "writeback_enabled": False, "ci_verified": False}
