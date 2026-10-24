"""Static opt-in recipe and unprivileged packager for devflow#465.

This module is NOT a writer, a workflow dispatcher, or an authorization token.
It does not run target repository commands. The independently authenticated
privileged writer must rederive the same policy and attest GitHub run metadata
before any write. The JO v1 Pilot remains separate and unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected, _policy, _provenance
from tools.generated_artifact_packager import (
    canonical_manifest_json, package_approved_outputs,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SUFFIX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
CALLER_PATH = ".github/workflows/verified-artifacts-rollout.yml"
MANIFEST_NAME = "manifest.json"
ARCHIVE_NAME = "artifact.zip"


@dataclass(frozen=True)
class FixedRecipe:
    repository: str
    recipe_id: str
    version: str
    branch_prefix: str
    outputs: tuple[str, ...]
    node_version: str
    generate_npm_script: str
    verify_npm_script: str
    max_file_bytes: int
    max_total_bytes: int
    max_archive_bytes: int


# Source-controlled, reviewed and intentionally finite. Selection never supplies
# commands, path globs, outputs, permission scopes, or new repository identities.
_IDS = FixedRecipe(
    repository="kinoko34077/IDS-Composit",
    recipe_id="ids-known-merge-v0.2",
    version="1",
    branch_prefix="artifact/writeback-ids/",
    outputs=(
        "data/known/generated/known-index-v0.2.json",
        "data/known/reports/known-index-v0.2.json",
    ),
    node_version="22",
    generate_npm_script="known:merge",
    verify_npm_script="known:check:merge",
    max_file_bytes=24 * 1024 * 1024,
    max_total_bytes=32 * 1024 * 1024,
    max_archive_bytes=32 * 1024 * 1024,
)

_TESTAPP = FixedRecipe(
    repository="kinoko34077/testapp",
    recipe_id="testapp-public-fixture-v1",
    version="1",
    branch_prefix="artifact/writeback-testapp/",
    outputs=("data/writeback-e2e/generated.json",),
    node_version="26.10.0",
    generate_npm_script="generate:writeback-e2e",
    verify_npm_script="verify:writeback-e2e",
    max_file_bytes=64 * 1024,
    max_total_bytes=64 * 1024,
    max_archive_bytes=128 * 1024,
)

_RECIPES: tuple[FixedRecipe, ...] = (_IDS, _TESTAPP)


def select_fixed_recipe(repository: str, recipe_id: str) -> FixedRecipe:
    """Reject an unknown/ambiguous pair rather than accepting caller policy."""
    if not isinstance(repository, str) or not isinstance(recipe_id, str):
        raise ArtifactRejected("repository and recipe must be strings")
    matches = [
        recipe for recipe in _RECIPES
        if recipe.repository == repository and recipe.recipe_id == recipe_id
    ]
    if len(matches) != 1:
        raise ArtifactRejected("repository/recipe is not uniquely registered")
    return matches[0]


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ArtifactRejected(f"{name}: must be a 40-character lower-case SHA")
    return value


def fixed_policy(repository: str, recipe_id: str, workflow_sha: str) -> dict[str, Any]:
    recipe = select_fixed_recipe(repository, recipe_id)
    policy = {
        "schema": "generated-artifacts-policy.v1",
        "repository": recipe.repository,
        "allowed_actors": ["kinoko34077"],
        "default_branch": "main",
        "branch_prefix": recipe.branch_prefix,
        "forbidden_branches": ["main"],
        "recipe": {
            "id": recipe.recipe_id,
            "version": recipe.version,
            "paths": list(recipe.outputs),
        },
        "producer_workflow_ref": f"{recipe.repository}/{CALLER_PATH}@{_sha(workflow_sha, 'workflow_sha')}",
        "limits": {
            "max_files": len(recipe.outputs),
            "max_file_bytes": recipe.max_file_bytes,
            "max_total_bytes": recipe.max_total_bytes,
            "max_archive_bytes": recipe.max_archive_bytes,
            "max_expansion_ratio": 1000,
        },
    }
    return dict(_policy(policy))


def fixed_commands(repository: str, recipe_id: str) -> dict[str, Any]:
    """Data only; no subprocess, eval, shell or user-provided script."""
    recipe = select_fixed_recipe(repository, recipe_id)
    return {
        "node_version": recipe.node_version,
        "generate_npm_script": recipe.generate_npm_script,
        "verify_npm_script": recipe.verify_npm_script,
        "output_paths": list(recipe.outputs),
    }


def producer_admission(
    policy: Mapping[str, Any],
    runner: Mapping[str, str],
    *,
    target_branch: str,
    expected_head: str,
    source_head: str,
    devflow_sha: str,
    devflow_checkout_sha: str,
) -> dict[str, Any]:
    """Only a *producer* preflight, never privileged writer attestation.

    All runner fields can be simulated outside GitHub; they must be verified
    independently against GitHub REST in a future privileged writer.
    """
    p = _policy(dict(policy))
    recipe = select_fixed_recipe(p["repository"], p["recipe"]["id"])
    workflow_sha_for_policy = _sha(runner.get("GITHUB_WORKFLOW_SHA"), "workflow_sha")
    if dict(p) != fixed_policy(recipe.repository, recipe.recipe_id, workflow_sha_for_policy):
        raise ArtifactRejected("producer policy differs from the reviewed static recipe")
    if _sha(devflow_sha, "devflow_sha") != _sha(devflow_checkout_sha, "devflow checkout"):
        raise ArtifactRejected("helper checkout does not match pinned devflow SHA")
    if _sha(expected_head, "expected_head") != _sha(source_head, "source_head"):
        raise ArtifactRejected("source checkout differs from expected head")
    if (
        not isinstance(target_branch, str)
        or not target_branch.startswith(recipe.branch_prefix)
        or not _SUFFIX.fullmatch(target_branch[len(recipe.branch_prefix):])
        or len(target_branch) > 200
    ):
        raise ArtifactRejected("target branch outside the fixed recipe prefix")
    required = {
        "GITHUB_REPOSITORY": recipe.repository,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{recipe.repository}/{CALLER_PATH}@refs/heads/main",
    }
    for field, expected in required.items():
        if runner.get(field) != expected:
            raise ArtifactRejected(f"unexpected producer context: {field}")
    actor = runner.get("GITHUB_ACTOR")
    if (
        actor != "kinoko34077"
        or runner.get("GITHUB_ACTOR_ID") != "79015263"
        or runner.get("GITHUB_TRIGGERING_ACTOR") != actor
    ):
        raise ArtifactRejected("untrusted or re-run actor")
    workflow_sha = _sha(runner.get("GITHUB_WORKFLOW_SHA"), "workflow_sha")
    if p["producer_workflow_ref"] != f"{recipe.repository}/{CALLER_PATH}@{workflow_sha}":
        raise ArtifactRejected("policy/caller workflow SHA mismatch")
    def positive(field: str) -> int:
        raw = runner.get(field)
        if not isinstance(raw, str) or not re.fullmatch(r"[1-9][0-9]*", raw):
            raise ArtifactRejected("invalid Actions run identifier: " + field)
        number = int(raw)
        if number > 10**16:
            raise ArtifactRejected("Actions run identifier too large")
        return number

    return dict(_provenance({
        "repository": recipe.repository,
        "actor": actor,
        "branch": target_branch,
        "expected_head": expected_head,
        "source_sha": source_head,
        "recipe_id": recipe.recipe_id,
        "recipe_version": recipe.version,
        "producer_run_id": positive("GITHUB_RUN_ID"),
        "producer_run_attempt": positive("GITHUB_RUN_ATTEMPT"),
        "producer_workflow_ref": p["producer_workflow_ref"],
    }, "producer admission"))


def package_from_fixed_source(
    repository: str, recipe_id: str, runner: Mapping[str, str],
    source_root: pathlib.Path, output_dir: pathlib.Path, *,
    target_branch: str, expected_head: str, source_head: str,
    devflow_sha: str, devflow_checkout_sha: str,
) -> dict[str, Any]:
    workflow_sha = _sha(runner.get("GITHUB_WORKFLOW_SHA"), "workflow_sha")
    policy = fixed_policy(repository, recipe_id, workflow_sha)
    admission = producer_admission(
        policy, runner, target_branch=target_branch, expected_head=expected_head,
        source_head=source_head, devflow_sha=devflow_sha,
        devflow_checkout_sha=devflow_checkout_sha,
    )
    source = source_root.resolve(strict=True)
    destination = output_dir.resolve(strict=False)
    if not source.is_dir() or (destination == source or source in destination.parents):
        raise ArtifactRejected("package output must be outside the source checkout")
    if output_dir.is_symlink():
        raise ArtifactRejected("package output must not be a symlink")
    manifest, archive = package_approved_outputs(policy, admission, source)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / MANIFEST_NAME).write_bytes(canonical_manifest_json(manifest))
    (destination / ARCHIVE_NAME).write_bytes(archive)
    return {
        "status": "PRODUCED_LOW_TRUST",
        "repository": repository, "recipe_id": recipe_id,
        "file_count": len(manifest["files"]), "archive_bytes": len(archive),
        "writer_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only writeback rollout producer (no writer)")
    sub = parser.add_subparsers(dest="command", required=True)
    info = sub.add_parser("recipe-info")
    info.add_argument("--repository", required=True)
    info.add_argument("--recipe", required=True)
    produce = sub.add_parser("produce")
    produce.add_argument("--repository", required=True)
    produce.add_argument("--recipe", required=True)
    produce.add_argument("--source", required=True)
    produce.add_argument("--out", required=True)
    produce.add_argument("--target-branch", required=True)
    produce.add_argument("--expected-head", required=True)
    produce.add_argument("--source-head", required=True)
    produce.add_argument("--devflow-sha", required=True)
    produce.add_argument("--devflow-checkout-sha", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "recipe-info":
            result = fixed_commands(args.repository, args.recipe)
        else:
            result = package_from_fixed_source(
                args.repository, args.recipe, os.environ,
                pathlib.Path(args.source), pathlib.Path(args.out),
                target_branch=args.target_branch, expected_head=args.expected_head,
                source_head=args.source_head, devflow_sha=args.devflow_sha,
                devflow_checkout_sha=args.devflow_checkout_sha,
            )
    except (ArtifactRejected, OSError, ValueError) as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
