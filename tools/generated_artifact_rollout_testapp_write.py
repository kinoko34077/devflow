"""Scoped testapp scratch writeback entry, devflow#474 (not dispatched by default).

This has no free-form repository or file inputs. It MUST run only as a distinct
reviewed writer job after successful, independently verified read-only planning.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.parse
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import CALLER_PATH, ARCHIVE_NAME, MANIFEST_NAME
from tools.generated_artifact_rollout_admission import attest_authenticated_readonly
from tools.generated_artifact_rollout_dryrun import (
    MANIFEST_CEILING, _read_regular_bounded,
)
from tools.generated_artifact_writer import GitHubWriteApi, verified_writeback

_REPOSITORY = "kinoko34077/testapp"
_RECIPE = "testapp-public-fixture-v1"
_PREFIX = "artifact/writeback-testapp/"
_OUTPUT = "data/writeback-e2e/generated.json"
# Explicit R2-specific activation contract: exactly one reviewed test recipe.
# R1's generated_artifact_rollout_writer.WRITE_ACTIVATED=False still governs
# the generic/dormant adapter; it is never silently flipped by this entry.
# This code switch alone is NOT operational activation; a reviewed Caller and
# target default-branch protection remain required independently.
_ACTIVATED_WRITER_RECIPES = frozenset({(_REPOSITORY, _RECIPE)})


class NarrowTestappWriteApi:
    """Whitelisted GET/POST/PATCH subset, bound to one admitted PR branch."""

    def __init__(self, transport: Any, branch: str) -> None:
        if getattr(transport, "repository", None) != _REPOSITORY:
            raise ArtifactRejected("writer transport is not the testapp repository")
        if not isinstance(branch, str) or not re.fullmatch(
            r"artifact/writeback-testapp/[A-Za-z0-9][A-Za-z0-9._-]*", branch
        ):
            raise ArtifactRejected("writer branch outside exact scoped grammar")
        self.repository = _REPOSITORY
        self._transport = transport
        self._branch = branch
        self._patch_ref = "/git/refs/heads/" + urllib.parse.quote(branch, safe="/")

    def get(self, path: str) -> Any:
        allowed = (
            path == ""
            or path == "/rulesets"
            or path.startswith("/actions/runs/")
            or path.startswith("/actions/workflows/")
            or path.startswith(f"/contents/{CALLER_PATH}?ref=")
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
        if path != self._patch_ref or set(payload) != {"sha", "force"} or payload.get("force") is not False:
            raise ArtifactRejected("only non-force update of the admitted scratch branch is allowed")
        return self._transport.patch(path, dict(payload))


def execute_testapp_scoped_write(
    api: Any, env: Mapping[str, str], artifact_dir: pathlib.Path, *,
    target_branch: str, expected_head: str, devflow_sha: str,
    devflow_checkout_sha: str,
) -> dict[str, Any]:
    """Authenticates an actual job-run, then writes only the trusted one-path recipe.

    Unlike the accepted read-only entry, this must never execute in the
    untrusted generator job. No actor/run/manifest input is treated as a grant.
    """
    if env.get("MODE") != "write" or env.get("GITHUB_REPOSITORY") != _REPOSITORY:
        raise ArtifactRejected("actual writer requires approved testapp write job")
    if (_REPOSITORY, _RECIPE) not in _ACTIVATED_WRITER_RECIPES:
        raise ArtifactRejected("testapp writer recipe not explicitly activated")
    if env.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ArtifactRejected("writer must originate from manual trusted caller")
    auth = attest_authenticated_readonly(
        api, env, repository=_REPOSITORY, recipe_id=_RECIPE,
        target_branch=target_branch, expected_head=expected_head,
        source_head=expected_head, devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
    )
    policy = auth["policy"]
    if policy["recipe"]["paths"] != [_OUTPUT]:
        raise ArtifactRejected("writer path set differs from approved one-file fixture")
    try:
        manifest = json.loads(_read_regular_bounded(
            artifact_dir / MANIFEST_NAME, MANIFEST_CEILING,
        ).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactRejected("malformed manifest") from exc
    archive = _read_regular_bounded(
        artifact_dir / ARCHIVE_NAME, policy["limits"]["max_archive_bytes"],
    )
    scoped = NarrowTestappWriteApi(api, target_branch)
    result = verified_writeback(
        scoped, policy, auth["admission"], manifest, archive, dry_run=False,
    )
    return {**result, "writer_scope": _REPOSITORY, "ci_verified": False}


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
