"""Bounded real GitHub Actions launch-evidence reader (#752, R2).

Only fixed GitHub REST GET endpoints. The existing user's ephemeral read token
must resolve to the same personal account as the private repository owner.
No run trigger, Claim, billing flag write, Check write, scheduled task, token
storage, fallback selection or Private source transfer occurs here.

An authenticated response establishes *read provenance*, not entitlement to
execute a job or to suppress Actions for the whole month.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tools.private_ci_billing_block import (
    JobLaunchReceipt, classify_job_launch,
)

_API = "https://api.github.com"
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_BLOCK = (
    "The job was not started because recent account payments have failed "
    "or your spending limit needs to be increased."
)
_MAX_RESPONSE = 1024 * 1024
_TIMEOUT = 10


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Hold(ValueError):
    """An allowlisted refusal reason only; never incorporate response text."""


@dataclass(frozen=True)
class AuthenticatedLaunchObservation:
    status: str                   # HOLD | PLAN_ONLY
    action: str                   # HOLD | RECORD_BILLING_BLOCK
    reason: str                   # Fixed machine reason
    requests_attempted: int = 0
    # This object is only populated after *all* six authenticated API reads.
    # It is neither signed authority nor a transferable bearer proof.
    receipt: JobLaunchReceipt | None = field(default=None, repr=False, compare=False)
    verified_for_dispatch: bool = False


def _hold(reason: str, count: int) -> AuthenticatedLaunchObservation:
    return AuthenticatedLaunchObservation("HOLD", "HOLD", reason, count)


def _valid_account(value: object) -> bool:
    return type(value) is str and _OWNER.fullmatch(value) is not None


def _valid_repository(value: object, account: str) -> bool:
    if type(value) is not str or value.count("/") != 1:
        return False
    owner, repo = value.split("/")
    return (
        _valid_account(owner) and owner.casefold() == account.casefold()
        and _REPO.fullmatch(repo) is not None
        and repo not in (".", "..") and not repo.startswith((".", "-"))
        and not repo.endswith((".", "-", ".git"))
    )


def _utc(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _iso(value: object) -> datetime:
    if type(value) is not str or len(value) > 36:
        raise _Hold("INVALID_JOB_COMPLETION_TIME")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _Hold("INVALID_JOB_COMPLETION_TIME") from exc
    if not _utc(result):
        raise _Hold("INVALID_JOB_COMPLETION_TIME")
    return result


def _get_json(opener, token: str, path: str) -> object:
    url = _API + path
    req = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer " + token,
    }, method="GET")
    try:
        with opener.open(req, timeout=_TIMEOUT) as response:
            if response.status != 200 or response.geturl() != url:
                raise _Hold("GITHUB_RESPONSE_ORIGIN_NOT_VERIFIED")
            raw = response.read(_MAX_RESPONSE + 1)
    except HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise _Hold("GITHUB_AUTH_OR_ACCESS_UNAVAILABLE") from exc
        raise _Hold("GITHUB_HTTP_ERROR") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise _Hold("GITHUB_TRANSPORT_UNAVAILABLE") from exc
    if len(raw) > _MAX_RESPONSE:
        raise _Hold("GITHUB_RESPONSE_TOO_LARGE")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise _Hold("GITHUB_RESPONSE_INVALID") from exc


def observe_github_job_launch_once(
    account: str,
    repository: str,
    run_id: int,
    job_id: int,
    expected_head_sha: str,
    now_utc: datetime,
    token: str,
    *,
    opener=None,
) -> AuthenticatedLaunchObservation:
    """Read six exact GitHub API resources, produce only a plan-only proposal.

    The caller must pin the intended *Private* run/job and target commit.
    No endpoint names, arbitrary URL or auth marker are supplied by a job.
    A token with no access yields HOLD; it is never minted or persisted.
    """
    if (not _valid_account(account) or not _valid_repository(repository, account)
            or type(run_id) is not int or run_id <= 0
            or type(job_id) is not int or job_id <= 0
            or type(expected_head_sha) is not str or not _SHA.fullmatch(expected_head_sha)
            or not _utc(now_utc)
            or type(token) is not str or not token or len(token) > 4096
            or any(c.isspace() for c in token)):
        return _hold("INVALID_PINNED_READ_CONTEXT", 0)

    opener = build_opener(_NoRedirect()) if opener is None else opener
    base = "/repos/" + repository
    calls = 0

    def get(path: str):
        nonlocal calls
        calls += 1
        return _get_json(opener, token, path)

    try:
        user = get("/user")
        if (type(user) is not dict or type(user.get("id")) is not int
                or user["id"] <= 0 or type(user.get("login")) is not str
                or user["login"].casefold() != account.casefold()):
            raise _Hold("GITHUB_OWNER_IDENTITY_NOT_VERIFIED")

        repo = get(base)
        owner = repo.get("owner") if type(repo) is dict else None
        if (type(repo) is not dict or type(owner) is not dict
                or repo.get("private") is not True
                or type(repo.get("id")) is not int or repo["id"] <= 0
                or type(repo.get("full_name")) is not str
                or repo["full_name"].casefold() != repository.casefold()
                or type(owner.get("id")) is not int or owner["id"] != user["id"]
                or type(owner.get("login")) is not str
                or owner["login"].casefold() != account.casefold()):
            raise _Hold("GITHUB_PRIVATE_OWNER_NOT_VERIFIED")

        run = get(base + "/actions/runs/" + str(run_id))
        run_repo = run.get("repository") if type(run) is dict else None
        if (type(run) is not dict or type(run_repo) is not dict
                or type(run.get("id")) is not int or run["id"] != run_id
                or type(run_repo.get("id")) is not int or run_repo["id"] != repo["id"]
                or run.get("head_sha") != expected_head_sha
                or run.get("status") != "completed"
                or run.get("conclusion") != "failure"):
            raise _Hold("GITHUB_WORKFLOW_RUN_NOT_VERIFIED")

        job = get(base + "/actions/jobs/" + str(job_id))
        if (type(job) is not dict
                or type(job.get("id")) is not int or job["id"] != job_id
                or type(job.get("run_id")) is not int or job["run_id"] != run_id
                or job.get("head_sha") != expected_head_sha
                or job.get("status") != "completed"
                or job.get("conclusion") != "failure"
                or job.get("runner_name") not in (None, "")
                or job.get("runner_id") not in (None, 0)
                or type(job.get("steps")) is not list
                or len(job["steps"]) != 0
                or job.get("check_run_url") != _API + base + "/check-runs/" + str(job_id)):
            raise _Hold("GITHUB_UNSTARTED_JOB_NOT_VERIFIED")
        completed = _iso(job.get("completed_at"))
        if not timedelta(0) <= now_utc - completed <= timedelta(hours=24):
            raise _Hold("GITHUB_COMPLETION_NOT_CURRENT")

        check = get(base + "/check-runs/" + str(job_id))
        output = check.get("output") if type(check) is dict else None
        app = check.get("app") if type(check) is dict else None
        if (type(check) is not dict or type(output) is not dict
                or type(app) is not dict or app.get("slug") != "github-actions"
                or type(check.get("id")) is not int or check["id"] != job_id
                or check.get("head_sha") != expected_head_sha
                or check.get("status") != "completed"
                or check.get("conclusion") != "failure"
                or type(output.get("annotations_count")) is not int
                or not (1 <= output["annotations_count"] < 100)):
            raise _Hold("GITHUB_CHECK_RUN_NOT_VERIFIED")

        annotations = get(base + "/check-runs/" + str(job_id) + "/annotations?per_page=100&page=1")
        if (type(annotations) is not list
                or len(annotations) != output["annotations_count"]
                or any(type(item) is not dict for item in annotations)):
            raise _Hold("GITHUB_ANNOTATIONS_INCOMPLETE")
        # Only the exact accepted billing-stop wording qualifies. Never
        # echo arbitrary annotations to the caller, logs or persisted state.
        matching = [
            item["message"] for item in annotations
            if type(item.get("message")) is str and _BLOCK in item["message"]
        ]
        if len(matching) != 1:
            raise _Hold("GITHUB_BILLING_STOP_ANNOTATION_NOT_VERIFIED")

        receipt = JobLaunchReceipt(
            account=account, repository=repository, visibility="private",
            run_id=run_id, job_id=job_id, head_sha=expected_head_sha,
            completed_at_utc=completed, conclusion="failure",
            runner_name="", steps_count=0, annotation=_BLOCK,
            authenticated_github_read=True,
        )
        plan = classify_job_launch(receipt, now_utc, account)
        if plan.status != "PLAN_ONLY" or plan.action != "RECORD_BILLING_BLOCK":
            raise _Hold("GITHUB_RECEIPT_CLASSIFICATION_REJECTED")
        return AuthenticatedLaunchObservation(
            "PLAN_ONLY", "RECORD_BILLING_BLOCK", plan.reason, calls,
            receipt=receipt,
        )
    except _Hold as exc:
        return _hold(str(exc), calls)
    except (TypeError, KeyError, AttributeError, OverflowError):
        return _hold("GITHUB_RECEIPT_SCHEMA_INVALID", calls)


__all__ = ["AuthenticatedLaunchObservation", "observe_github_job_launch_once"]
