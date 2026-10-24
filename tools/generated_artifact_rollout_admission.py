"""Dormant read-only writer-side admission checks for devflow#465.

No token creation, HTTP transport, Git writes or workflow activation is exposed.
The caller supplies a separately authenticated GitHub API reader. The returned
admission does NOT authorize write: subsequent reviewed writer integration must
revalidate target branch/rulesets/PR/head and exact archive bytes.
"""
from __future__ import annotations

import base64
import pathlib
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected
from tools.generated_artifact_rollout import (
    CALLER_PATH, fixed_policy, producer_admission, select_fixed_recipe,
)

_TEMPLATE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "docs/operations/templates"
TEMPLATE = _TEMPLATE_ROOT / "verified-artifacts-rollout-ids.yml"
_TEMPLATES = {
    "kinoko34077/IDS-Composit": TEMPLATE,
    "kinoko34077/testapp": _TEMPLATE_ROOT / "verified-artifacts-rollout-testapp.yml",
}
PLACEHOLDER = "<DEVFLOW_SHA>"
MAX_CALLER_BYTES = 16384


def exact_caller_text(template: str, devflow_sha: str) -> str:
    """A trusted, fixed full-byte template, not a YAML substring whitelist."""
    from tools.generated_artifact_rollout import _sha
    sha = _sha(devflow_sha, "devflow_sha")
    if not isinstance(template, str) or template.count(PLACEHOLDER) != 2:
        raise ArtifactRejected("trusted rollout caller template is not canonical")
    return template.replace(PLACEHOLDER, sha)


def verify_exact_caller(text: str, trusted_template: str, devflow_sha: str) -> None:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_CALLER_BYTES:
        raise ArtifactRejected("caller content missing or too large")
    if text != exact_caller_text(trusted_template, devflow_sha):
        raise ArtifactRejected("caller differs from the exact approved trusted template")


def _required_runner(env: Mapping[str, str]) -> dict[str, str]:
    fields = (
        "GITHUB_REPOSITORY", "GITHUB_ACTOR", "GITHUB_ACTOR_ID",
        "GITHUB_TRIGGERING_ACTOR",
        "GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_WORKFLOW_REF",
        "GITHUB_WORKFLOW_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
    )
    return {field: env.get(field, "") for field in fields}


def attest_authenticated_readonly(
    api: Any, env: Mapping[str, str], *, repository: str, recipe_id: str,
    target_branch: str, expected_head: str, source_head: str,
    devflow_sha: str, devflow_checkout_sha: str,
    trusted_template: str | None = None,
) -> dict[str, Any]:
    """Independently fetch actions run, workflow, caller content before admission.

    This routine has ONLY GET calls. API must be a trusted GitHub reader for the
    pinned target repository; archive content and producer input cannot supply
    run/workflow/caller observations.
    """
    select_fixed_recipe(repository, recipe_id)
    if getattr(api, "repository", None) != repository:
        raise ArtifactRejected("independent API reader repository mismatch")
    runner = _required_runner(env)
    policy = fixed_policy(repository, recipe_id, runner["GITHUB_WORKFLOW_SHA"])
    admission = producer_admission(
        policy, runner, target_branch=target_branch,
        expected_head=expected_head, source_head=source_head,
        devflow_sha=devflow_sha, devflow_checkout_sha=devflow_checkout_sha,
    )
    if env.get("MODE") not in ("dry-run", "write"):
        raise ArtifactRejected("writer mode is not in the exact allowlist")
    # IDS is approved for read-only Caller preparation only. Even if a
    # forged event supplies mode=write, read-only attestation must reject it.
    if repository == "kinoko34077/IDS-Composit" and env.get("MODE") != "dry-run":
        raise ArtifactRejected("IDS rollout mode is read-only until separate admission")
    run = api.get(f"/actions/runs/{admission['producer_run_id']}")
    if not isinstance(run, dict):
        raise ArtifactRejected("GitHub Actions run metadata unavailable")
    workflow_id = run.get("workflow_id")
    if type(workflow_id) is not int or workflow_id <= 0:
        raise ArtifactRejected("GitHub Actions workflow identity missing")
    workflow = api.get(f"/actions/workflows/{workflow_id}")
    if not isinstance(workflow, dict):
        raise ArtifactRejected("GitHub Actions workflow metadata unavailable")
    actor = admission["actor"]
    expected_workflow_sha = runner["GITHUB_WORKFLOW_SHA"]
    if (
        type(run.get("id")) is not int
        or run["id"] != admission["producer_run_id"]
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] != admission["producer_run_attempt"]
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "in_progress"
        or run.get("head_sha") != expected_workflow_sha
        or run.get("head_branch") != "main"
        or run.get("path") != CALLER_PATH
        or not isinstance(run.get("actor"), dict)
        or run["actor"].get("id") != 79015263
        or run["actor"].get("login") != actor
        or not isinstance(run.get("repository"), dict)
        or run["repository"].get("full_name") != repository
        or run.get("workflow_id") != workflow.get("id")
        or workflow.get("path") != CALLER_PATH
    ):
        raise ArtifactRejected("independent GitHub producer metadata mismatch")
    t = run.get("triggering_actor")
    if not isinstance(t, dict) or t.get("id") != 79015263 or t.get("login") != actor:
        raise ArtifactRejected("missing or different-actor GitHub REST rerun rejected")
    raw = api.get(f"/contents/{CALLER_PATH}?ref={expected_workflow_sha}")
    if (
        not isinstance(raw, dict)
        or raw.get("type") != "file"
        or raw.get("path") != CALLER_PATH
        or raw.get("encoding") != "base64"
        or not isinstance(raw.get("content"), str)
    ):
        raise ArtifactRejected("GitHub caller content unavailable")
    try:
        decoded = base64.b64decode(raw["content"].replace("\n", ""), validate=True)
        if len(decoded) > MAX_CALLER_BYTES:
            raise ArtifactRejected("caller blob too large")
        caller_text = decoded.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ArtifactRejected("GitHub caller is not strict UTF-8/base64") from exc
    template_path = _TEMPLATES.get(repository)
    if template_path is None:
        raise ArtifactRejected("registered repository lacks trusted caller template")
    template = trusted_template if trusted_template is not None else template_path.read_text("utf-8")
    verify_exact_caller(caller_text, template, devflow_sha)
    return {
        "status": "AUTHENTICATED_READ_ONLY",
        "policy": policy,
        "admission": admission,
        "mode": env["MODE"],
        "writer_authorized": False,
    }
