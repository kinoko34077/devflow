"""Shared narrow GitHub adapter for reviewed fixed-recipe writer entries."""
from __future__ import annotations

import json
import pathlib
import re
import urllib.parse
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import (
    ARCHIVE_NAME, MANIFEST_NAME, select_fixed_recipe,
)
from tools.generated_artifact_rollout_admission import attest_authenticated_readonly
from tools.generated_artifact_rollout_dryrun import MANIFEST_CEILING, _read_regular_bounded
from tools.generated_artifact_writer import verified_writeback


class NarrowRegisteredWriteApi:
    """Bind Git mutations to one fixed repository, recipe and scratch branch."""

    def __init__(self, transport: Any, branch: str, *, repository: str, recipe_id: str) -> None:
        recipe = select_fixed_recipe(repository, recipe_id)
        if getattr(transport, "repository", None) != repository:
            raise ArtifactRejected("writer transport is not the registered repository")
        branch_pattern = re.escape(recipe.branch_prefix) + r"[A-Za-z0-9][A-Za-z0-9._-]*"
        if not isinstance(branch, str) or re.fullmatch(branch_pattern, branch) is None:
            raise ArtifactRejected("writer branch outside exact registered grammar")
        self.repository = repository
        self._transport = transport
        self._branch = branch
        self._caller_path = recipe.caller_path
        self._patch_ref = "/git/refs/heads/" + urllib.parse.quote(branch, safe="/")

    def get(self, path: str) -> Any:
        allowed = (
            path == ""
            or path == "/rulesets"
            or path.startswith("/actions/runs/")
            or path.startswith("/actions/workflows/")
            or path.startswith(f"/contents/{self._caller_path}?ref=")
            or path.startswith("/branches/")
            or path.startswith("/pulls?")
            or path.startswith("/git/commits/")
            or path.startswith("/git/trees/")
            or path.startswith("/git/blobs/")
            or path.startswith("/compare/")
        )
        if not allowed:
            raise ArtifactRejected("unadmitted GitHub read endpoint")
        return self._transport.get(path)

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        if path not in ("/git/blobs", "/git/trees", "/git/commits"):
            raise ArtifactRejected("unadmitted Git object mutation")
        return self._transport.post(path, dict(payload))

    def patch(self, path: str, payload: Mapping[str, Any]) -> Any:
        if (
            path != self._patch_ref
            or set(payload) != {"sha", "force"}
            or payload.get("force") is not False
        ):
            raise ArtifactRejected("only non-force update of the admitted scratch branch is allowed")
        return self._transport.patch(path, dict(payload))


def require_main_protection(api: Any) -> None:
    """Fail closed before Git mutation unless GitHub confirms protected main."""
    branch = api.get("/branches/main")
    if (
        not isinstance(branch, dict)
        or branch.get("name") != "main"
        or branch.get("protected") is not True
    ):
        raise ArtifactRejected("default main protection not independently verified")


def execute_registered_write(
    api: Any, env: Mapping[str, str], artifact_dir: pathlib.Path, *,
    repository: str, recipe_id: str, target_branch: str, expected_head: str,
    devflow_sha: str, devflow_checkout_sha: str,
) -> dict[str, Any]:
    """Authenticate one real dispatch and reuse the accepted verified writer."""
    recipe = select_fixed_recipe(repository, recipe_id)
    if env.get("MODE") != "write" or env.get("GITHUB_REPOSITORY") != repository:
        raise ArtifactRejected("actual writer requires its exact approved repository and write job")
    if env.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ArtifactRejected("writer must originate from manual trusted caller")
    auth = attest_authenticated_readonly(
        api, env, repository=repository, recipe_id=recipe_id,
        target_branch=target_branch, expected_head=expected_head,
        source_head=expected_head, devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
    )
    policy = auth["policy"]
    if policy["recipe"]["paths"] != list(recipe.outputs):
        raise ArtifactRejected("writer path set differs from the exact registered recipe")
    try:
        manifest = json.loads(_read_regular_bounded(
            artifact_dir / MANIFEST_NAME, MANIFEST_CEILING,
        ).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactRejected("malformed manifest") from exc
    archive = _read_regular_bounded(
        artifact_dir / ARCHIVE_NAME, policy["limits"]["max_archive_bytes"],
    )
    scoped = NarrowRegisteredWriteApi(
        api, target_branch, repository=repository, recipe_id=recipe_id,
    )
    # The job token is repository-wide. Protected default main is mandatory;
    # only this adapter can update the recipe's unprotected same-repository PR branch.
    require_main_protection(scoped)
    result = verified_writeback(
        scoped, policy, auth["admission"], manifest, archive, dry_run=False,
    )
    return {**result, "writer_scope": repository, "ci_verified": False}
