"""Fixed testapp writer entry, devflow#474 (not dispatched by default)."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import select_fixed_recipe
from tools.generated_artifact_rollout_scoped_write import (
    NarrowRegisteredWriteApi, execute_registered_write, require_main_protection,
)
from tools.generated_artifact_writer import GitHubWriteApi

_REPOSITORY = "kinoko34077/testapp"
_RECIPE = "testapp-public-fixture-v1"
# Explicit R2 activation remains exactly testapp's one accepted fixture.
_ACTIVATED_WRITER_RECIPES = frozenset({(_REPOSITORY, _RECIPE)})


class NarrowTestappWriteApi(NarrowRegisteredWriteApi):
    """Backward-compatible name for testapp's fixed scoped adapter."""

    def __init__(self, transport: Any, branch: str) -> None:
        super().__init__(
            transport, branch, repository=_REPOSITORY, recipe_id=_RECIPE,
        )


_require_main_protection = require_main_protection


def execute_testapp_scoped_write(
    api: Any, env: Mapping[str, str], artifact_dir: pathlib.Path, *,
    target_branch: str, expected_head: str, devflow_sha: str,
    devflow_checkout_sha: str,
) -> dict[str, Any]:
    """Keep the accepted testapp API while delegating to the shared writer."""
    if (_REPOSITORY, _RECIPE) not in _ACTIVATED_WRITER_RECIPES:
        raise ArtifactRejected("testapp writer recipe not explicitly activated")
    # Ensure this exact testapp pair remains source-registered before executing.
    select_fixed_recipe(_REPOSITORY, _RECIPE)
    return execute_registered_write(
        api, env, artifact_dir, repository=_REPOSITORY, recipe_id=_RECIPE,
        target_branch=target_branch, expected_head=expected_head,
        devflow_sha=devflow_sha, devflow_checkout_sha=devflow_checkout_sha,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scoped testapp-only verified scratch write")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--target-branch", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--devflow-sha", required=True)
    args = parser.parse_args(argv)
    try:
        api = GitHubWriteApi(_REPOSITORY, os.environ.get("WRITER_TOKEN", ""))
        result = execute_testapp_scoped_write(
            api, os.environ, pathlib.Path(args.artifact),
            target_branch=args.target_branch, expected_head=args.expected_head,
            devflow_sha=args.devflow_sha,
            devflow_checkout_sha=os.environ.get("DEVFLOW_CHECKOUT_SHA", ""),
        )
    except (ArtifactRejected, OSError, ValueError) as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
