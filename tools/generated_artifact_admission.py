"""Pure admission/run-attestation boundary; no network, credentials or writes.

The writer must fetch the workflow run and workflow metadata *independently*
from GitHub REST. Neither the producer archive nor its manifest can provide
these trusted observations. This helper validates them before a write plan.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from tools.generated_artifact_contract import ArtifactRejected, _policy, _provenance

CALLER_PATH = ".github/workflows/verified-artifacts-pilot.yml"
RECIPE = "jo-orthography-accounting"
OUTPUTS = ["data/reports/orthography-v2-source-accounting.json"]
REPO = "kinoko34077/japanese-orthography"


def _required(obs: Mapping, key: str) -> str:
    value = obs.get(key)
    if not isinstance(value, str) or not value:
        raise ArtifactRejected("missing authenticated runner context: " + key)
    return value


def _decimal(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise ArtifactRejected("invalid positive numeric Actions identifier")
    return int(value)


def attest_producer(
    raw_policy: Mapping, runner: Mapping, run: Mapping, workflow: Mapping,
    *, target_branch: str, expected_head: str,
) -> dict:
    """Return admission from verified GitHub runner + two GitHub REST observations.

    run and workflow MUST be independently fetched by the trusted writer job:
    GET /actions/runs/<github.run_id>, GET /actions/workflows/<run.workflow_id>.
    """
    policy = _policy(dict(raw_policy))
    if policy["repository"] != REPO or policy["recipe"]["id"] != RECIPE or policy["recipe"]["paths"] != OUTPUTS:
        raise ArtifactRejected("unadmitted repository or generated-file recipe")
    if _required(runner, "repository") != REPO:
        raise ArtifactRejected("runner repository differs from fixed admission")
    actor = _required(runner, "actor")
    if actor not in policy["allowed_actors"] or _required(runner, "triggering_actor") != actor:
        raise ArtifactRejected("untrusted actor or different-actor re-run")
    if _required(runner, "event") != "workflow_dispatch":
        raise ArtifactRejected("untrusted workflow trigger")
    branch = policy["default_branch"]
    if _required(runner, "ref") != "refs/heads/" + branch:
        raise ArtifactRejected("caller did not run from default branch")
    ref = _required(runner, "workflow_ref")
    if ref != REPO + "/" + CALLER_PATH + "@refs/heads/" + branch:
        raise ArtifactRejected("unexpected workflow caller path")
    workflow_sha = _required(runner, "workflow_sha")
    if not re.fullmatch(r"[0-9a-f]{40}", workflow_sha):
        raise ArtifactRejected("invalid caller workflow SHA")
    pinned_ref = REPO + "/" + CALLER_PATH + "@" + workflow_sha
    if policy["producer_workflow_ref"] != pinned_ref:
        raise ArtifactRejected("unreviewed caller workflow SHA")
    if not isinstance(run, Mapping) or not isinstance(workflow, Mapping):
        raise ArtifactRejected("independent GitHub metadata not supplied")
    rid = _decimal(_required(runner, "run_id"))
    attempt = _decimal(_required(runner, "run_attempt"))
    if type(run.get("id")) is not int or run["id"] != rid or (
        type(run.get("run_attempt")) is not int or run["run_attempt"] != attempt
    ):
        raise ArtifactRejected("producer run identity or attempt mismatch")
    if (
        run.get("event") != "workflow_dispatch"
        or run.get("status") != "in_progress"
        or run.get("head_sha") != workflow_sha
        or run.get("head_branch") != branch
        or run.get("path") != CALLER_PATH
        or (run.get("actor") or {}).get("login") != actor
        or (run.get("repository") or {}).get("full_name") != REPO
        or not isinstance(run.get("workflow_id"), int)
        or run.get("workflow_id") != workflow.get("id")
        or workflow.get("path") != CALLER_PATH
    ):
        raise ArtifactRejected("GitHub Actions producer provenance mismatch")
    if not isinstance(target_branch, str) or not target_branch.startswith(policy["branch_prefix"]):
        raise ArtifactRejected("target branch outside approved prefix")
    if not isinstance(expected_head, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ArtifactRejected("expected source/head is not a full SHA")
    admission = {
        "repository": REPO, "actor": actor, "branch": target_branch,
        "expected_head": expected_head, "source_sha": expected_head,
        "recipe_id": RECIPE, "recipe_version": policy["recipe"]["version"],
        "producer_run_id": rid, "producer_run_attempt": attempt,
        "producer_workflow_ref": pinned_ref,
    }
    return dict(_provenance(admission, "attested admission"))
