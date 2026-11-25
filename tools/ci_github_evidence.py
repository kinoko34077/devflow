"""Source-scoped, read-only GitHub CI observations for #1121.

Native run/job status and PR candidate identity are distinct observations.
Neither a PR head SHA nor a success conclusion proves a particular checkout,
test recipe, resolved environment or historical PR body. No merge/skip grant.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
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
    repository_id = _object(run.get("repository")).get("id")
    head_repository_id = _object(run.get("head_repository")).get("id")
    return {key: run[key] for key in (
        "id", "workflow_id", "run_attempt", "head_sha", "path", "event", "status",
    )} | {
        "conclusion": run.get("conclusion"),
        "repository_id": repository_id if _id(repository_id) else None,
        "head_repository_id": head_repository_id if _id(head_repository_id) else None,
        "head_branch": run.get("head_branch"),
    }


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


# This is a specific code-execution identity, not a mandatory dimension set
# for metadata or external-state guarantees. Only a trusted host may supply
# these measurements; a PR artifact, log line or user JSON is not a receipt.
@dataclass(frozen=True)
class ExecutionInputs:
    tree_sha: str
    recipe_sha256: str
    environment_sha256: str
    dependencies_sha256: str
    policy_sha256: str

    def valid(self) -> bool:
        return _sha(self.tree_sha) and all(
            isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
            for v in (self.recipe_sha256, self.environment_sha256,
                      self.dependencies_sha256, self.policy_sha256)
        )


@dataclass(frozen=True)
class TrustedExecutionReceipt:
    repository: str
    guarantee: str
    run_id: int
    workflow_id: int
    workflow_path: str
    event: str
    event_head_sha: str
    job_id: int
    job_name: str
    job_attempt: int
    checkout_sha: str
    inputs: ExecutionInputs
    source_ref: str
    valid_until: datetime | None


def read_execution_verification(
    reader: GitHubReader, repository: str, guarantee: str,
    required: ExecutionInputs, receipt: TrustedExecutionReceipt | None,
    *, now: datetime,
) -> dict:
    """Bind trusted, measured execution inputs to a current native job.

    This is an internal adapter, not a receipt authentication mechanism.
    The protected collector must measure the actual tested bytes, recipe,
    resolved environment/dependencies and policy, bind them to the job,
    establish freshness and authenticate its receipt before calling here.
    None means no such evidence exists. No public JSON/CLI receipt input.
    A matching Git commit alone cannot establish what a job executed.
    """
    repository = normalize_repository(repository)

    def unknown(reason: str) -> dict:
        return {
            "status": "UNKNOWN", "reason": reason, "tested_tree": None,
            "decision": {"action": "HOLD", "reason": reason, "evidence_refs": ()},
            "requires_source_revalidation": True,
        }

    if (not isinstance(required, ExecutionInputs) or not required.valid()
            or not _text(guarantee) or not isinstance(now, datetime)
            or now.utcoffset() is None):
        return unknown("EXECUTION_REQUIREMENT_UNKNOWN")
    if receipt is None:
        return unknown("TRUSTED_EXECUTION_RECEIPT_UNAVAILABLE")
    if (not isinstance(receipt, TrustedExecutionReceipt)
            or receipt.repository != repository or receipt.guarantee != guarantee
            or not all(_id(v) for v in (receipt.run_id, receipt.workflow_id,
                                      receipt.job_id, receipt.job_attempt))
            or not all(_text(v) for v in (receipt.workflow_path, receipt.event,
                                          receipt.job_name, receipt.source_ref))
            or not _sha(receipt.event_head_sha) or not _sha(receipt.checkout_sha)
            or not isinstance(receipt.inputs, ExecutionInputs) or not receipt.inputs.valid()
            or (receipt.valid_until is not None and (
                not isinstance(receipt.valid_until, datetime)
                or receipt.valid_until.utcoffset() is None))):
        return unknown("EXECUTION_RECEIPT_INVALID")
    native = read_run_verification(reader, repository, receipt.run_id)
    if native.get("status") != "OBSERVED" or native.get("job_coverage") != "COMPLETE_PAGE":
        return unknown("NATIVE_EXECUTION_EVIDENCE_UNKNOWN")
    run = native["run"]
    if (run["workflow_id"], run["path"], run["event"], run["head_sha"]) != (
            receipt.workflow_id, receipt.workflow_path, receipt.event, receipt.event_head_sha):
        return unknown("EXECUTION_RUN_IDENTITY_MISMATCH")
    jobs = [job for job in native["jobs"] if job["id"] == receipt.job_id]
    if (len(jobs) != 1 or jobs[0]["name"] != receipt.job_name
            or jobs[0]["attempt"] != receipt.job_attempt):
        return unknown("EXECUTION_JOB_IDENTITY_MISMATCH")
    job = jobs[0]
    try:
        commit = reader.get_git_commit(repository, receipt.checkout_sha)
    except DevflowMCPError:
        return unknown("EXECUTION_CHECKOUT_UNAVAILABLE")
    if (commit.get("sha") != receipt.checkout_sha
            or _object(commit.get("tree")).get("sha") != receipt.inputs.tree_sha):
        return unknown("EXECUTION_CHECKOUT_TREE_MISMATCH")

    # The original guarantee is owned by trusted policy. Never compare only
    # HEAD or one hash, nor treat a current native job failure as a success.
    # A non-successful/in-progress workflow is conservatively not reusable.
    outcome = _outcome(job) if _outcome(run) == "success" else _outcome(run)
    # In particular, a successful workflow with a queued/failed/skipped job
    # is not successful evidence for that job's guarantee.
    required_identity = Requirement(repository, guarantee, asdict(required))
    observed_identity = Requirement(repository, guarantee, asdict(receipt.inputs))
    decision = assess_verification(
        required_identity,
        (Observation(observed_identity, outcome, job["source_ref"], receipt.valid_until),),
        now=now,
    )
    return {
        "status": "OBSERVED", "tested_tree": receipt.inputs.tree_sha,
        "checkout_sha": receipt.checkout_sha, "job_source_ref": job["source_ref"],
        "receipt_source_ref": receipt.source_ref, "decision": asdict(decision),
        "requires_source_revalidation": True,
    }


@dataclass(frozen=True)
class FixedSourceRequirement:
    """Explicit pin selected by the trusted policy owner, not a client request."""
    repository: str
    repository_id: int
    channel: str
    policy_revision: str
    commit: str
    branch: str
    workflow_id: int
    workflow_path: str
    required_jobs: tuple[str, ...]


def valid_fixed_source_requirement(required: object) -> bool:
    """Shared structural validation for native observation and host policy."""
    if (not isinstance(required, FixedSourceRequirement)
            or not _text(required.repository) or not _id(required.repository_id)
            or not all(_text(v) for v in (required.channel, required.policy_revision,
                                         required.branch, required.workflow_path))
            or not _sha(required.commit) or not _id(required.workflow_id)
            or not isinstance(required.required_jobs, tuple) or not required.required_jobs
            or not all(_text(v) for v in required.required_jobs)
            or len(set(required.required_jobs)) != len(required.required_jobs)):
        return False
    try:
        return normalize_repository(required.repository) == required.repository
    except DevflowMCPError:
        return False


def read_fixed_source_verification(
    reader: GitHubReader, required: FixedSourceRequirement,
) -> dict:
    """Observe exact native push evidence for an already selected fixed source.

    No candidate search across revisions, checkout, trust-policy approval,
    cache promotion, execution grant or test-equivalence claim. The host
    separately authenticates its policy and authorizes the selected revision.
    """
    def result(status: str, reason: str, **evidence) -> dict:
        return {
            "status": status, "reason": reason,
            "can_authorize_execution": False, "tested_tree": None,
            "requires_source_revalidation": True, **evidence,
        }

    if not valid_fixed_source_requirement(required):
        return result("UNKNOWN", "FIXED_SOURCE_REQUIREMENT_INVALID")
    try:
        repository = normalize_repository(required.repository)
        packet = reader.get_fixed_push_workflow_runs(
            repository, required.workflow_id, required.commit, required.branch,
        )
    except DevflowMCPError:
        return result("UNKNOWN", "FIXED_SOURCE_RUN_LOOKUP_UNAVAILABLE")
    records = packet.get("workflow_runs")
    count = packet.get("total_count")
    if type(count) is not int or count != 1 or not isinstance(records, list) or len(records) != 1:
        return result("UNKNOWN", "FIXED_SOURCE_RUN_NOT_UNIQUE")
    record = _object(records[0])
    run_id = record.get("id")
    if not _id(run_id):
        return result("UNKNOWN", "FIXED_SOURCE_RUN_IDENTITY_UNPROVEN")
    identity = _run_identity(record, repository, run_id)
    if identity is None or (
        identity["repository_id"], identity["head_repository_id"], identity["head_branch"],
        identity["head_sha"], identity["workflow_id"], identity["path"], identity["event"]
    ) != (
        required.repository_id, required.repository_id, required.branch,
        required.commit, required.workflow_id, required.workflow_path, "push"
    ):
        return result("UNKNOWN", "FIXED_SOURCE_RUN_IDENTITY_UNPROVEN")
    # Reuse the original observer, including latest jobs and run revalidation.
    native = read_run_verification(reader, repository, run_id)
    if (native.get("status") != "OBSERVED" or native.get("job_coverage") != "COMPLETE_PAGE"
            or native.get("run") != identity):
        return result("UNKNOWN", "FIXED_SOURCE_RUN_CHANGED_OR_INCOMPLETE")
    evidence = {"source_ref": native["source_ref"], "run_id": run_id,
                "run_attempt": identity["run_attempt"], "commit": required.commit}
    if _outcome(identity) != "success":
        return result("NOT_SUCCESSFUL", "FIXED_SOURCE_RUN_NOT_SUCCESSFUL", **evidence)
    job_refs = []
    for name in required.required_jobs:
        matches = [job for job in native["jobs"] if job["name"] == name]
        if len(matches) != 1:
            return result("UNKNOWN", "FIXED_SOURCE_REQUIRED_JOB_NOT_UNIQUE", **evidence)
        if _outcome(matches[0]) != "success":
            return result("NOT_SUCCESSFUL", "FIXED_SOURCE_REQUIRED_JOB_NOT_SUCCESSFUL", **evidence)
        job_refs.append(matches[0]["source_ref"])
    try:
        commit = reader.get_git_commit(repository, required.commit)
    except DevflowMCPError:
        return result("UNKNOWN", "FIXED_SOURCE_COMMIT_UNAVAILABLE", **evidence)
    tree = _object(commit.get("tree")).get("sha")
    if commit.get("sha") != required.commit or not _sha(tree):
        return result("UNKNOWN", "FIXED_SOURCE_TREE_UNPROVEN", **evidence)
    return result(
        "NATIVE_SOURCE_CANDIDATE", "EXACT_PUSH_AND_REQUIRED_JOBS_SUCCESS",
        repository=repository, repository_id=required.repository_id,
        channel=required.channel, policy_revision=required.policy_revision,
        tree_sha=tree, job_source_refs=tuple(job_refs), **evidence,
    )
