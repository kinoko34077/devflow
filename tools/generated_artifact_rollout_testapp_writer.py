"""testapp-only, bounded R2 writeback: separate from the R1 read-only verifier.

The only effectful target is a scratch public-fixture PR, exactly one JSON path.
This module MUST run only in a pinned, reviewed, distinct Actions writer job.
It never checks out or imports target-repository source and never creates tokens.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import ARCHIVE_NAME, MANIFEST_NAME
from tools.generated_artifact_rollout_admission import attest_authenticated_readonly
from tools.generated_artifact_rollout_dryrun import _read_regular_bounded, MANIFEST_CEILING
from tools.generated_artifact_writer import GitHubWriteApi, verified_writeback

TESTAPP_REPO = "kinoko34077/testapp"
TESTAPP_RECIPE = "testapp-public-fixture-v1"
SCRATCH_BRANCH = "artifact/writeback-testapp/e2e-20261012"
ALLOWED_PATH = "data/writeback-e2e/generated.json"
_SHA = re.compile(r"[0-9a-f]{40}\Z")


class RestrictedTestappWriteApi:
    """Only v1 CAS's three immutable Git-object POSTs and one branch PATCH.

    Read methods remain available for required independent GitHub REST
    admission and protected-branch/PR/commit/tree/readback inspection.
    Target output paths are independently bounded by the fixed recipe.
    """
    def __init__(self, api: Any):
        if getattr(api, "repository", None) != TESTAPP_REPO:
            raise ArtifactRejected("write API repository mismatch")
        self.repository = TESTAPP_REPO
        self._api = api

    def get(self, path: str) -> Any:
        if not isinstance(path, str):
            raise ArtifactRejected("GitHub read path invalid")
        return self._api.get(path)

    def post(self, path: str, payload: Any) -> Any:
        if path not in {"/git/blobs", "/git/trees", "/git/commits"}:
            raise ArtifactRejected("GitHub POST outside immutable object allowlist")
        return self._api.post(path, payload)

    def patch(self, path: str, payload: Any) -> Any:
        if path != f"/git/refs/heads/{SCRATCH_BRANCH}":
            raise ArtifactRejected("GitHub ref update outside fixed scratch branch")
        if (
            not isinstance(payload, dict)
            or payload.get("force") is not False
            or not isinstance(payload.get("sha"), str)
            or not _SHA.fullmatch(payload["sha"])
            or set(payload) != {"sha", "force"}
        ):
            raise ArtifactRejected("GitHub ref update must be non-force exact SHA")
        return self._api.patch(path, payload)


def testapp_write(
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
) -> dict[str, Any]:
    """Execute a single fully authenticated, bounded scratch write or replay.

    Requires separate GitHub job permissions and strict in-code scope checks.
    Never promote manifest, ZIP, source code or caller-provided policy to authority.
    """
    if (
        repository != TESTAPP_REPO
        or recipe_id != TESTAPP_RECIPE
        or target_branch != SCRATCH_BRANCH
        or env.get("GITHUB_REPOSITORY") != TESTAPP_REPO
        or env.get("MODE") != "write"
        or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
    ):
        raise ArtifactRejected("writer is not admitted for this testapp-only E2E")

    bounded = RestrictedTestappWriteApi(api)
    authenticated = attest_authenticated_readonly(
        bounded,
        env,
        repository=repository,
        recipe_id=recipe_id,
        target_branch=target_branch,
        expected_head=expected_head,
        source_head=source_head,
        devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
    )
    policy = authenticated["policy"]
    if policy["recipe"]["paths"] != [ALLOWED_PATH]:
        raise ArtifactRejected("testapp output allowlist not the exact one-path contract")
    manifest_bytes = _read_regular_bounded(artifact_dir / MANIFEST_NAME, MANIFEST_CEILING)
    archive_bytes = _read_regular_bounded(
        artifact_dir / ARCHIVE_NAME, policy["limits"]["max_archive_bytes"],
    )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactRejected("invalid verified writeback manifest") from exc
    result = verified_writeback(
        bounded, policy, authenticated["admission"],
        manifest, archive_bytes, dry_run=False,
    )
    return {
        **result,
        "writer_scope": "testapp-single-fixture",
        # Successful CAS does not prove post-write CI ran on the writer HEAD.
        "ci_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded testapp-only writeback E2E writer")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--target-branch", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--devflow-sha", required=True)
    args = parser.parse_args(argv)
    try:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if repo != TESTAPP_REPO:
            raise ArtifactRejected("writer forbidden for non-testapp repository")
        token = os.environ.get("WRITER_TOKEN", "")
        result = testapp_write(
            GitHubWriteApi(repo, token),
            os.environ,
            pathlib.Path(args.artifact),
            repository=repo,
            recipe_id=args.recipe,
            target_branch=args.target_branch,
            expected_head=args.expected_head,
            source_head=args.expected_head,
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
