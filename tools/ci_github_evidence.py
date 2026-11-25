"""Source-scoped, read-only GitHub CI observations for #1121.

Native run/job status and PR candidate identity are distinct observations.
Neither a PR head SHA nor a success conclusion proves a particular checkout,
test recipe, resolved environment or historical PR body. No merge/skip grant.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from tools.ci_verification_plan import Observation, Requirement, assess_verification
from tools.control_semantic_postmerge_event import validate_pr_owner_metadata_event
from tools.devflow_mcp_core import DevflowMCPError, GitHubReader, normalize_repository

_SHA = re.compile(r"[0-9a-f]{40}\Z")


def _sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _id(value: object) -> bool:
    return type(value) is int and value > 0


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _repo(value: object, expected: str) -> bool:
    name = _object(value).get("full_name")
    return isinstance(name, str) and name.casefold() == expected.casefold()


def _read_failure(reason: str) -> dict:
    return {"status": "UNKNOWN", "reason": reason}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                     separators=(",", ":")).encode("ascii")).hexdigest()


def read_pr_verification(reader: GitHubReader, repository: str, number: int) -> dict:
    """Recheck current metadata cheaply; read the candidate tree separately."""
    repository = normalize_repository(repository)
    try:
        pr = reader.get_pull_request(repository, number)
    except DevflowMCPError:
        return _read_failure("PR_READ_UNAVAILABLE")
    base = _object(pr.get("base"))
    head = _object(pr.get("head"))
    base_repo = _object(base.get("repo"))
    ref = f"https://github.com/{repository}/pull/{number}"
    if (not _id(pr.get("number")) or pr["number"] != number
            or pr.get("html_url") != ref or not _repo(base_repo, repository)
            or not _sha(base.get("sha")) or not _sha(head.get("sha"))):
        return _read_failure("PR_IDENTITY_UNPROVEN")

    # This evaluates today's PR body, not a previous event's metadata.
    body = pr.get("body")
    default_branch = base_repo.get("default_branch")
    if (body is not None and not isinstance(body, str)) or not _text(base.get("ref")) or not _text(default_branch):
        metadata = _read_failure("PR_METADATA_INPUT_UNKNOWN")
    else:
        event = {
            "repository": {"full_name": repository, "default_branch": default_branch},
            "pull_request": {"body": body, "base": {"ref": base["ref"]}},
        }
        metadata = validate_pr_owner_metadata_event(event, repository)
        metadata["input_digest"] = _digest(event)
        metadata["source_ref"] = ref

    result = {
        "status": "OBSERVED",
        "source_ref": ref,
        "repository": repository,
        "pr_number": number,
        "head_sha": head["sha"],
        "base_sha": base["sha"],
        "metadata": metadata,
        "candidate": _read_failure("CANDIDATE_IDENTITY_UNPROVEN"),
        "tested_tree": None,
        "requires_source_revalidation": True,
    }
    merged = pr.get("merged")
    state = pr.get("state")
    candidate_sha = pr.get("merge_commit_sha")
    kind = ("MERGED_COMMIT" if state == "closed" and merged is True
            else "SYNTHETIC_MERGE" if state == "open" and merged is False else None)
    if kind is None or not _sha(candidate_sha):
        return result
    try:
        commit = reader.get_git_commit(repository, candidate_sha)
    except DevflowMCPError:
        result["candidate"] = _read_failure("CANDIDATE_READ_UNAVAILABLE")
        return result
    tree = _object(commit.get("tree")).get("sha")
    if commit.get("sha") != candidate_sha or not _sha(tree):
        return result
    if kind == "SYNTHETIC_MERGE":
        parents = commit.get("parents")
        if (not isinstance(parents, list) or
                [_object(parent).get("sha") for parent in parents] != [base["sha"], head["sha"]]):
            result["candidate"] = _read_failure("CANDIDATE_PARENT_MISMATCH")
            return result
    result["candidate"] = {
        "status": "OBSERVED", "kind": kind, "sha": candidate_sha, "tree_sha": tree,
        "source_ref": f"https://github.com/{repository}/commit/{candidate_sha}",
    }
    return result


def _run_identity(run: dict, repository: str, run_id: int) -> dict | None:
    if (not _id(run.get("id")) or run["id"] != run_id
            or not _repo(run.get("repository"), repository)
            or not _id(run.get("workflow_id")) or not _id(run.get("run_attempt"))
            or not _sha(run.get("head_sha")) or not _text(run.get("path"))
            or not _text(run.get("event")) or not _text(run.get("status"))):
        return None
    # Identity is limited to this native record, not the execution environment.
    return {key: run[key] for key in (
        "id", "workflow_id", "run_attempt", "head_sha", "path", "event", "status",
    )} | {"conclusion": run.get("conclusion")}


def _outcome(record: dict) -> str:
    status = record.get("status")
    if status == "completed":
        conclusion = record.get("conclusion")
        return conclusion if _text(conclusion) else "unknown"
    return status if status in ("queued", "in_progress") else "unknown"


def _native_decision(repository: str, guarantee: str, identity: dict, outcome: str,
                     source_ref: str, now: datetime) -> dict:
    requirement = Requirement(repository, guarantee, {k: str(v) for k, v in identity.items()})
    return asdict(assess_verification(
        requirement, (Observation(requirement, outcome, source_ref, None),), now=now,
    ))


def read_run_verification(reader: GitHubReader, repository: str, run_id: int) -> dict:
    """Observe one run and its current job attempts without claiming code equivalence."""
    repository = normalize_repository(repository)
    try:
        run = reader.get_action_run(repository, run_id)
    except DevflowMCPError:
        return _read_failure("RUN_READ_UNAVAILABLE")
    identity = _run_identity(run, repository, run_id)
    if identity is None:
        return _read_failure("RUN_IDENTITY_UNPROVEN")
    source = f"https://github.com/{repository}/actions/runs/{run_id}"
    result = {
        "status": "OBSERVED",
        "repository": repository,
        "source_ref": source,
        "run": identity,
        "event_head_tree": None,
        "tested_tree": None,
        "code_equivalence": _read_failure("EXECUTION_IDENTITY_UNPROVEN"),
        "jobs": [],
        "job_coverage": "UNKNOWN",
        "requires_source_revalidation": True,
    }
    head_commit = _object(run.get("head_commit"))
    if head_commit.get("id") == identity["head_sha"] and _sha(head_commit.get("tree_id")):
        result["event_head_tree"] = head_commit["tree_id"]
    try:
        packet = reader.get_latest_action_jobs(repository, run_id)
        # Resolve the current attempt across the non-atomic jobs read.
        current = reader.get_action_run(repository, run_id)
    except DevflowMCPError:
        result["status"] = "PARTIAL"
        result["reason"] = "JOB_OR_REVALIDATION_READ_UNAVAILABLE"
        return result
    if _run_identity(current, repository, run_id) != identity:
        result["status"] = "PARTIAL"
        result["reason"] = "RUN_CHANGED_DURING_READ"
        return result

    now = datetime.now(timezone.utc)
    run_key = {k: identity[k] for k in ("id", "workflow_id", "run_attempt", "head_sha", "path", "event")}
    result["native_run_decision"] = _native_decision(
        repository, "native-workflow-run-result", run_key, _outcome(run), source, now,
    )
    jobs = packet.get("jobs")
    count = packet.get("total_count")
    if not isinstance(jobs, list) or type(count) is not int or count < len(jobs):
        result["status"] = "PARTIAL"
        result["reason"] = "JOB_PACKET_INVALID"
        return result
    if count != len(jobs):
        # One bounded page is not a complete latest-job inventory.
        result["status"] = "PARTIAL"
        result["reason"] = "JOB_PAGE_INCOMPLETE"
        return result

    seen = set()
    rows = []
    for job in jobs:
        job = _object(job)
        job_id = job.get("id")
        attempt = job.get("run_attempt")
        if (not _id(job_id) or job_id in seen or type(job.get("run_id")) is not int
                or job["run_id"] != run_id or job.get("head_sha") != identity["head_sha"]
                or not _id(attempt) or attempt > identity["run_attempt"]
                or not _text(job.get("name")) or not _text(job.get("status"))):
            result["status"] = "PARTIAL"
            result["reason"] = "JOB_IDENTITY_UNPROVEN"
            return result
        seen.add(job_id)
        job_source = f"{source}/job/{job_id}"
        rows.append({
            "id": job_id, "name": job["name"], "attempt": attempt,
            "status": job["status"], "conclusion": job.get("conclusion"),
            "source_ref": job_source,
            "native_decision": _native_decision(
                repository, "native-workflow-job-result",
                run_key | {"job_id": job_id, "job_attempt": attempt},
                _outcome(job), job_source, now,
            ),
        })
    result["jobs"] = rows
    result["job_coverage"] = "COMPLETE_PAGE"
    return result
