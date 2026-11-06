"""Opt-in rollout R1: independently authenticated, strictly GET-only dry-run.

No privileged writer workflow or installed target Caller is provided here.
This is a pure bridge between authenticated runner/caller provenance and the
existing, accepted v1 archive/target-tree planner. All network operations are
GETs; no method can update a repository from this code path.
"""
from __future__ import annotations

import json
import pathlib
import stat
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import ARCHIVE_NAME, MANIFEST_NAME
from tools.generated_artifact_rollout_admission import attest_authenticated_readonly
from tools.generated_artifact_writer import verified_writeback

MANIFEST_CEILING = 64 * 1024


class _ReadOnlyApi:
    def __init__(self, api: Any):
        self.repository = api.repository
        self._api = api

    def get(self, path: str) -> Any:
        return self._api.get(path)

    def post(self, path: str, payload: Any) -> None:
        raise ArtifactRejected("rollout dry-run does not permit GitHub POST")

    def patch(self, path: str, payload: Any) -> None:
        raise ArtifactRejected("rollout dry-run does not permit GitHub PATCH")


def _read_regular_bounded(path: pathlib.Path, ceiling: int) -> bytes:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > ceiling:
            raise ArtifactRejected("artifact file is not regular or exceeds its limit")
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ArtifactRejected("required run artifact is missing") from exc
    if len(data) > ceiling:
        raise ArtifactRejected("artifact content exceeded its limit")
    return data


def preview_authenticated(
    api: Any, env: dict[str, str], artifact_dir: pathlib.Path, *,
    repository: str, recipe_id: str, target_branch: str,
    expected_head: str, source_head: str, devflow_sha: str,
    devflow_checkout_sha: str,
    trusted_template: str | None = None,
) -> dict[str, Any]:
    """Validate source/run/caller AND target PR, branches, archive, output bytes.

    Preview explicitly rejects mode=write even if the trusted template supports
    such a future mode. A later audited privileged entry is a separate contract.
    """
    if env.get("MODE") != "dry-run":
        raise ArtifactRejected("R1 preview is dry-run-only")
    authenticated = attest_authenticated_readonly(
        api, env, repository=repository, recipe_id=recipe_id,
        target_branch=target_branch, expected_head=expected_head,
        source_head=source_head, devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
        trusted_template=trusted_template,
    )
    policy = authenticated["policy"]
    manifest_bytes = _read_regular_bounded(
        artifact_dir / MANIFEST_NAME, MANIFEST_CEILING,
    )
    archive_bytes = _read_regular_bounded(
        artifact_dir / ARCHIVE_NAME, policy["limits"]["max_archive_bytes"],
    )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ArtifactRejected("manifest is not strict UTF-8 JSON") from exc

    # The accepted v1 writer core verifies the exact approved path set, hashes,
    # ZIP entries, Git tree blobs, unprotected PR branch/rulesets and live head.
    # The wrapper precludes POST/PATCH even if a future core path regresses.
    plan = verified_writeback(
        _ReadOnlyApi(api), policy, authenticated["admission"],
        manifest, archive_bytes, dry_run=True,
    )
    return {
        **plan, "writer_authorized": False,
        "auth_status": authenticated["status"],
    }
