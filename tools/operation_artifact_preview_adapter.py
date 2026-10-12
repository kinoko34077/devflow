"""A3 optional read-only consumer of the accepted #465 preview and #487 A2 projection.

The #465 preview owns independent GitHub run/caller attestation, ZIP validation,
target inspection and native planning. This thin adapter calls that preview
ONCE, then uses the same already-reviewed pure recipe/admission constructors
to validate and project its result; it does not duplicate GitHub GETs.

This module never produces a writer admission, authenticated bearer proof,
approval, token or permission. No production workflow calls it by default.
"""
from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import fixed_policy, producer_admission
from tools.generated_artifact_rollout_dryrun import (
    _ReadOnlyApi,
    preview_authenticated,
)
from tools.operation_preflight_projection import project_artifact_preview


BUNDLE_SCHEMA = "operation-readonly-preview-bundle.v0"


def preview_and_project_authenticated(
    api: Any,
    env: Mapping[str, str],
    artifact_dir: pathlib.Path,
    *,
    repository: str,
    recipe_id: str,
    target_branch: str,
    expected_head: str,
    source_head: str,
    devflow_sha: str,
    devflow_checkout_sha: str,
    request_id: str,
    catalog_source_sha: str,
    trusted_template: str | None = None,
) -> dict[str, Any]:
    """Obtain one #465 native read-only plan and its non-authorizing A2 shape.

    Caller responsibilities remain explicit:
    - Supply a genuine trusted GitHub GET transport for the target repository.
    - Pin the trusted devflow source and caller template by the existing #465
      contract; never treat this function as a signature or authority source.
    - An eventual separately reviewed writer MUST re-attest all identities,
      current target state, branch rules, actor and per-effect Human gates.

    A preview or diagnostic hash cannot authorize a mutation; this adapter
    does not expose POST/PATCH or an execution entrypoint.
    """
    if env.get("MODE") != "dry-run":
        raise ArtifactRejected("read-only evidence adapter forbids write mode")
    readonly = _ReadOnlyApi(api)
    # Accepted owner #465 native verifier is authoritative for all relevant
    # GitHub GET provenance, approved ZIP bytes, PR and target current state.
    native = preview_authenticated(
        readonly, dict(env), artifact_dir,
        repository=repository, recipe_id=recipe_id,
        target_branch=target_branch, expected_head=expected_head,
        source_head=source_head, devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
        trusted_template=trusted_template,
    )
    # These are pure reviewed #465 constructors, NOT another metadata lookup,
    # and only reached after the full native authenticated preview has passed.
    # Inputs remain assertions; the resulting projection is NOT a credential.
    policy = fixed_policy(
        repository, recipe_id, env.get("GITHUB_WORKFLOW_SHA", ""),
    )
    admission = producer_admission(
        policy, env,
        target_branch=target_branch, expected_head=expected_head,
        source_head=source_head, devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
    )
    projection = project_artifact_preview(
        json.dumps(native, sort_keys=True, separators=(",", ":"), allow_nan=False),
        trusted_policy=policy, trusted_admission=admission,
        request_id=request_id, catalog_source_sha=catalog_source_sha,
    )
    if projection["effect_authorized"] is not False or native["writes_performed"] is not False:
        raise ArtifactRejected("read-only preview cannot authorize or perform effects")
    return {
        "schema": BUNDLE_SCHEMA,
        "native_preview": native,
        "projection": projection,
        "effect_authorized": False,
        "requires_fresh_writer_revalidation": True,
    }
