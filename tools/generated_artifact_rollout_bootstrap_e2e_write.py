"""Single-repository writer entry for the approved #1050 Bootstrap E2E."""
from __future__ import annotations

import pathlib
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import select_fixed_recipe
from tools.generated_artifact_rollout_scoped_write import (
    NarrowRegisteredWriteApi, execute_registered_write, run_registered_write_cli,
)

_REPOSITORY = "kinoko34077/devflow-writeback-bootstrap-e2e-20261118"
_RECIPE = "bootstrap-writeback-e2e-v1"
# Only the accepted fixture's fixed repo/recipe pair is activated here.
_ACTIVATED_WRITER_RECIPES = frozenset({(_REPOSITORY, _RECIPE)})


class NarrowBootstrapE2EWriteApi(NarrowRegisteredWriteApi):
    """Exact adapter for the accepted Bootstrap writeback fixture."""

    def __init__(self, transport: Any, branch: str) -> None:
        super().__init__(
            transport, branch, repository=_REPOSITORY, recipe_id=_RECIPE,
        )


def execute_bootstrap_e2e_scoped_write(
    api: Any, env: Mapping[str, str], artifact_dir: pathlib.Path, *,
    target_branch: str, expected_head: str, devflow_sha: str,
    devflow_checkout_sha: str,
) -> dict[str, Any]:
    """Run the same verified writer only for the approved fixed recipe."""
    if (_REPOSITORY, _RECIPE) not in _ACTIVATED_WRITER_RECIPES:
        raise ArtifactRejected("Bootstrap E2E writer recipe not explicitly activated")
    select_fixed_recipe(_REPOSITORY, _RECIPE)
    return execute_registered_write(
        api, env, artifact_dir, repository=_REPOSITORY, recipe_id=_RECIPE,
        target_branch=target_branch, expected_head=expected_head,
        devflow_sha=devflow_sha, devflow_checkout_sha=devflow_checkout_sha,
    )


def main(argv: list[str] | None = None) -> int:
    return run_registered_write_cli(
        argv, repository=_REPOSITORY,
        description="Fixed Bootstrap E2E scoped write",
        execute=execute_bootstrap_e2e_scoped_write,
    )

if __name__ == "__main__":
    raise SystemExit(main())
