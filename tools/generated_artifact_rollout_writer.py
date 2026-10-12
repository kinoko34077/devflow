"""DORMANT privileged-boundary adapter for rollout R1 (devflow#465).

This file cannot enable writeback: WRITE_ACTIVATED is false until a separate
reviewed change and repository-specific Human/security admission. No new
workflow or target caller is installed by this module.
"""
from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import ARCHIVE_NAME, MANIFEST_NAME
from tools.generated_artifact_rollout_admission import attest_authenticated_readonly
from tools.generated_artifact_rollout_dryrun import (
    _ReadOnlyApi, _read_regular_bounded, MANIFEST_CEILING,
)
from tools.generated_artifact_writer import verified_writeback

# A separate PR + explicit per-target Human gate must be satisfied before
# enabling this. Do NOT bind this constant to a dispatch input or env var.
WRITE_ACTIVATED = False


def execute_reviewed_entry(
    api: Any, env: Mapping[str, str], artifact_dir: pathlib.Path, *,
    repository: str, recipe_id: str, target_branch: str,
    expected_head: str, source_head: str, devflow_sha: str,
    devflow_checkout_sha: str,
    trusted_template: str | None = None,
) -> dict[str, Any]:
    """Perform authenticated dry-run; *not* an executable write path today.

    The accepted v1 non-force CAS writer core is imported rather than copied.
    Future production activation must also independently prove exact-head CI,
    security review, caller permissions and rollback; no such proof exists here.
    """
    mode = env.get("MODE")
    if mode not in ("dry-run", "write"):
        raise ArtifactRejected("mode outside strict fixed allowlist")
    if mode == "write" and not WRITE_ACTIVATED:
        raise ArtifactRejected("privileged multi-repository writeback is not activated")
    authenticated = attest_authenticated_readonly(
        api, env, repository=repository, recipe_id=recipe_id,
        target_branch=target_branch, expected_head=expected_head,
        source_head=source_head, devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
        trusted_template=trusted_template,
    )
    policy = authenticated["policy"]
    manifest_bytes = _read_regular_bounded(artifact_dir / MANIFEST_NAME, MANIFEST_CEILING)
    archive_bytes = _read_regular_bounded(
        artifact_dir / ARCHIVE_NAME, policy["limits"]["max_archive_bytes"],
    )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ArtifactRejected("manifest is not strict UTF-8 JSON") from exc
    # Every current-mode execution gets a proxy incapable of mutations;
    # the unactivated 'write' branch is intentionally unreachable.
    reader = _ReadOnlyApi(api) if mode == "dry-run" else api
    plan = verified_writeback(
        reader, policy, authenticated["admission"],
        manifest, archive_bytes, dry_run=(mode != "write"),
    )
    return {
        **plan,
        "writeback_enabled": WRITE_ACTIVATED,
        "authenticated_runner": authenticated["status"],
        "ci_verified": False,
    }
