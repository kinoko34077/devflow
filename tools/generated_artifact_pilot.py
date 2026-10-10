"""Single-repository Pilot entrypoints for verified generated-artifact writeback (devflow#384 S3.3).

Two subcommands are run by the shared reusable workflow
``.github/workflows/generated-artifact-writeback.yml``:

``produce``
    Runs in the unprivileged ``produce`` job (``contents: read``, no secrets)
    *after* the fixed recipe has executed target-repository code. Everything it
    emits is low-trust data: the writer re-derives every authority input itself.

``write``
    Runs in the separately permissioned ``write`` job from a devflow checkout
    pinned to the reviewed SHA. It never executes target-repository code or
    artifact contents. It independently authenticates the producer run through
    GitHub REST, verifies the caller workflow *content* at the run's
    ``workflow_sha`` (devflow#387 review F1), then delegates to the reviewed
    planner/writer core.

The Pilot scope is fixed here and is not caller-configurable: one repository,
one recipe, one generated path (japanese-orthography#300).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import sys
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_admission import (
    CALLER_PATH,
    OUTPUTS,
    RECIPE,
    REPO,
    attest_producer,
)
from tools.generated_artifact_contract import ArtifactRejected, _policy, _provenance
from tools.generated_artifact_packager import canonical_manifest_json, package_approved_outputs
from tools.generated_artifact_replay_probe import ReplayProbeRejected, probe_exact_replay
from tools.generated_artifact_writer import GitHubWriteApi, verified_writeback

REUSABLE_WORKFLOW = "kinoko34077/devflow/.github/workflows/generated-artifact-writeback.yml"
RECIPE_VERSION = "1"
RECIPE_NPM_SCRIPT = "generate:orthography-accounting"
BRANCH_PREFIX = "artifact/devflow384/"
DEFAULT_BRANCH = "main"
ALLOWED_ACTORS = ("kinoko34077",)
FORBIDDEN_BRANCHES = ("main", "migration/tar-pattern-291")
MANIFEST_NAME = "manifest.json"
ARCHIVE_NAME = "artifact.zip"
_LIMIT = 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{40}")
_FORBIDDEN_CALLER_TRIGGERS = (
    "pull_request", "push:", "schedule", "workflow_run", "repository_dispatch",
    "issue_comment", "issues:", "workflow_call", "merge_group", "release:",
)


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ArtifactRejected(f"{name} must be an exact 40-character SHA")
    return value


def pilot_policy(workflow_sha: str) -> dict[str, Any]:
    """Return the fixed Pilot policy bound to one authenticated caller workflow SHA.

    Only ``workflow_sha`` varies per run. It is accepted only after the caller
    identity and content checks below; it never comes from producer output.
    """
    policy = {
        "schema": "generated-artifacts-policy.v1",
        "repository": REPO,
        "allowed_actors": list(ALLOWED_ACTORS),
        "default_branch": DEFAULT_BRANCH,
        "branch_prefix": BRANCH_PREFIX,
        "forbidden_branches": list(FORBIDDEN_BRANCHES),
        "recipe": {"id": RECIPE, "version": RECIPE_VERSION, "paths": list(OUTPUTS)},
        "producer_workflow_ref": f"{REPO}/{CALLER_PATH}@{_sha(workflow_sha, 'workflow_sha')}",
        "limits": {
            "max_files": len(OUTPUTS),
            "max_file_bytes": _LIMIT,
            "max_total_bytes": _LIMIT,
            "max_archive_bytes": _LIMIT,
            "max_expansion_ratio": 1000,
        },
    }
    return dict(_policy(policy))


def verify_caller_content(text: str, devflow_sha: str) -> None:
    """Fail closed unless the caller is the thin, pinned, dispatch-only Pilot caller."""
    devflow_sha = _sha(devflow_sha, "devflow_sha")
    if not isinstance(text, str) or len(text) > 16384:
        raise ArtifactRejected("caller workflow content unavailable or oversized")
    lines = [line.strip() for line in text.splitlines()]
    uses = [line for line in lines if line.startswith("uses:") or line.startswith("- uses:")]
    expected_uses = f"uses: {REUSABLE_WORKFLOW}@{devflow_sha}"
    if uses != [expected_uses]:
        raise ArtifactRejected("caller must invoke only the reviewed reusable workflow at the pinned devflow SHA")
    if [line for line in lines if line.startswith("devflow_sha:")] != [f"devflow_sha: {devflow_sha}"]:
        raise ArtifactRejected("caller devflow_sha input must equal its reusable-workflow pin")
    if "workflow_dispatch:" not in lines:
        raise ArtifactRejected("caller must be workflow_dispatch-only")
    lowered = text.lower()
    for token in _FORBIDDEN_CALLER_TRIGGERS:
        if token in lowered:
            raise ArtifactRejected("caller declares a forbidden trigger or construct")
    if "secrets" in lowered or "run:" in lowered:
        raise ArtifactRejected("caller must not pass secrets or run commands")


def _runner_from_env(env: Mapping[str, str]) -> dict[str, str]:
    keys = {
        "repository": "GITHUB_REPOSITORY",
        "actor": "GITHUB_ACTOR",
        "triggering_actor": "GITHUB_TRIGGERING_ACTOR",
        "event": "GITHUB_EVENT_NAME",
        "ref": "GITHUB_REF",
        "workflow_ref": "GITHUB_WORKFLOW_REF",
        "workflow_sha": "GITHUB_WORKFLOW_SHA",
        "run_id": "GITHUB_RUN_ID",
        "run_attempt": "GITHUB_RUN_ATTEMPT",
    }
    return {name: str(env.get(var) or "") for name, var in keys.items()}


def _inputs(env: Mapping[str, str]) -> tuple[str, str, str, str]:
    devflow_sha = _sha(env.get("DEVFLOW_SHA"), "devflow_sha input")
    checkout = _sha(env.get("DEVFLOW_CHECKOUT_SHA"), "devflow checkout")
    if checkout != devflow_sha:
        raise ArtifactRejected("devflow helper checkout differs from the pinned devflow SHA")
    expected_head = _sha(env.get("EXPECTED_HEAD"), "expected_head input")
    branch = str(env.get("TARGET_BRANCH") or "")
    if not branch.startswith(BRANCH_PREFIX) or branch == BRANCH_PREFIX:
        raise ArtifactRejected("target branch outside the approved Pilot prefix")
    mode = str(env.get("MODE") or "")
    if mode not in ("dry-run", "write", "write-replay-test"):
        raise ArtifactRejected("mode must be dry-run, write or write-replay-test")
    return devflow_sha, expected_head, branch, mode


def produce(env: Mapping[str, str], source_root: pathlib.Path, out_dir: pathlib.Path) -> dict[str, Any]:
    """Package the fixed recipe output. Output is low-trust; the writer re-verifies it."""
    _, expected_head, branch, _ = _inputs(env)
    if _sha(env.get("SOURCE_HEAD"), "source checkout") != expected_head:
        raise ArtifactRejected("producer source checkout differs from expected_head")
    runner = _runner_from_env(env)
    workflow_sha = _sha(runner["workflow_sha"], "workflow_sha")
    policy = pilot_policy(workflow_sha)
    admission = {
        "repository": runner["repository"],
        "actor": runner["actor"],
        "branch": branch,
        "expected_head": expected_head,
        "source_sha": expected_head,
        "recipe_id": RECIPE,
        "recipe_version": RECIPE_VERSION,
        "producer_run_id": int(runner["run_id"]) if runner["run_id"].isdigit() else 0,
        "producer_run_attempt": int(runner["run_attempt"]) if runner["run_attempt"].isdigit() else 0,
        "producer_workflow_ref": policy["producer_workflow_ref"],
    }
    _provenance(admission, "producer admission")
    manifest, archive = package_approved_outputs(policy, admission, source_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / MANIFEST_NAME).write_bytes(canonical_manifest_json(manifest))
    (out_dir / ARCHIVE_NAME).write_bytes(archive)
    return {"status": "PRODUCED", "files": len(manifest["files"]), "archive_bytes": len(archive)}


def _read_bounded(path: pathlib.Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ArtifactRejected(f"{path.name} is missing or not a regular file")
    if path.stat().st_size > limit:
        raise ArtifactRejected(f"{path.name} exceeds the Pilot size limit")
    data = path.read_bytes()
    if len(data) > limit:
        raise ArtifactRejected(f"{path.name} exceeds the Pilot size limit")
    return data


def _caller_text(api: GitHubWriteApi, workflow_sha: str) -> str:
    response = api.get(f"/contents/{CALLER_PATH}?ref={workflow_sha}")
    if not isinstance(response, dict) or response.get("type") != "file" or response.get("encoding") != "base64":
        raise ArtifactRejected("caller workflow content unavailable")
    if response.get("path") != CALLER_PATH:
        raise ArtifactRejected("caller workflow path mismatch")
    try:
        raw = base64.b64decode(str(response.get("content") or "").replace("\n", ""), validate=True)
        return raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ArtifactRejected("caller workflow content undecodable") from exc


def write(env: Mapping[str, str], artifact_dir: pathlib.Path, api: GitHubWriteApi | None = None) -> dict[str, Any]:
    """Authenticate the producer run, then plan (dry-run) or commit through the reviewed core."""
    devflow_sha, expected_head, branch, mode = _inputs(env)
    runner = _runner_from_env(env)
    if runner["repository"] != REPO:
        raise ArtifactRejected("writer is not running in the Pilot repository")
    workflow_sha = _sha(runner["workflow_sha"], "workflow_sha")
    if api is None:
        token = str(env.get("WRITER_TOKEN") or "")
        api = GitHubWriteApi(REPO, token)
    if not runner["run_id"].isdigit():
        raise ArtifactRejected("invalid run id")
    run = api.get(f"/actions/runs/{int(runner['run_id'])}")
    workflow_id = run.get("workflow_id") if isinstance(run, dict) else None
    if type(workflow_id) is not int or workflow_id <= 0:
        raise ArtifactRejected("producer run metadata unavailable")
    workflow = api.get(f"/actions/workflows/{workflow_id}")
    verify_caller_content(_caller_text(api, workflow_sha), devflow_sha)
    policy = pilot_policy(workflow_sha)
    admission = attest_producer(
        policy, runner, run, workflow if isinstance(workflow, dict) else {},
        target_branch=branch, expected_head=expected_head,
    )
    manifest_bytes = _read_bounded(artifact_dir / MANIFEST_NAME, 64 * 1024)
    archive = _read_bounded(artifact_dir / ARCHIVE_NAME, policy["limits"]["max_archive_bytes"])
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ArtifactRejected("manifest is not valid UTF-8 JSON") from exc
    if mode == "write-replay-test":
        return probe_exact_replay(api, policy, admission, manifest, archive,
                                  verified_writeback=verified_writeback)
    return verified_writeback(api, policy, admission, manifest, archive, dry_run=(mode != "write"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="devflow#384 verified generated-artifact Pilot")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("produce")
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True)
    w = sub.add_parser("write")
    w.add_argument("--artifact", required=True)
    sub.add_parser("recipe-script")
    args = parser.parse_args(argv)
    try:
        if args.command == "recipe-script":
            print(RECIPE_NPM_SCRIPT)
            return 0
        if args.command == "produce":
            result = produce(os.environ, pathlib.Path(args.source), pathlib.Path(args.out))
        else:
            result = write(os.environ, pathlib.Path(args.artifact))
    except ReplayProbeRejected as exc:
        if exc.outcome_unknown:
            print(json.dumps({
                "status": "REPLAY_TEST_WRITE_OUTCOME_UNKNOWN",
                "writes_performed": "UNKNOWN",
                "ci_verified": False,
                "recovery_required": True,
            }, sort_keys=True), file=sys.stderr)
        if exc.first_committed:
            print(json.dumps({
                "status": "REPLAY_TEST_FAILED_AFTER_COMMIT",
                "writes_performed": True,
                "previous_head": exc.previous_head,
                "new_head": exc.new_head,
                "ci_verified": False,
                "recovery_required": True,
            }, sort_keys=True), file=sys.stderr)
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2
    except ArtifactRejected as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
