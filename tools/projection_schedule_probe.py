"""Read-only observation of the central projection-cache schedule.

This checks GitHub Actions evidence only, not cache freshness or Repo Monitor
publication. No trigger, write, token installation or scheduler is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com/repos/kinoko34077/devflow/actions/workflows/maintenance-audit.yml/runs"


def classify_run(payload: object, *, expected_utc: str) -> dict[str, object]:
    """Never confuse missing/incomplete Actions evidence with a successful renewal."""
    try:
        target = datetime.fromisoformat(expected_utc.replace("Z", "+00:00"))
        if target.tzinfo is None:
            raise ValueError()
        target = target.astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("expected_utc must be an offset-aware ISO-8601 timestamp") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        return {"status": "UNKNOWN", "reason": "INVALID_RUN_LIST"}
    matches = []
    for item in payload["workflow_runs"]:
        if not isinstance(item, dict) or item.get("event") != "schedule":
            continue
        started = item.get("created_at")
        if not isinstance(started, str):
            continue
        try:
            instant = datetime.fromisoformat(started.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
        # Scheduled workflows can run late. Associate by a bounded forward
        # observation window; never use runs from before the expected slot.
        if 0 <= (instant - target).total_seconds() < 3600:
            matches.append((instant, item))
    if not matches:
        return {"status": "UNKNOWN", "reason": "NO_SCHEDULE_RUN_IN_WINDOW"}
    if len(matches) != 1:
        return {"status": "UNKNOWN", "reason": "AMBIGUOUS_SCHEDULE_RUNS"}
    _, latest = max(matches, key=lambda pair: pair[0])
    status = latest.get("status")
    conclusion = latest.get("conclusion")
    if status != "completed":
        observed = "IN_PROGRESS"
    elif conclusion == "success":
        observed = "WORKFLOW_SUCCESS_ONLY"
    elif conclusion in ("failure", "cancelled", "timed_out", "action_required"):
        observed = "WORKFLOW_FAILED"
    else:
        observed = "UNKNOWN"
    return {"status": observed, "run_id": latest.get("id"), "run_url": latest.get("html_url"),
            "conclusion": conclusion, "note": "This does not verify the projection-cache job, all markers, or downstream Pages."}



def classify_projection_job(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        return {"status": "UNKNOWN", "reason": "INVALID_JOBS"}
    jobs = [j for j in payload["jobs"] if isinstance(j, dict) and j.get("name") == "projection-cache"]
    if len(jobs) != 1:
        return {"status": "UNKNOWN", "reason": "MISSING_OR_DUPLICATE_JOB"}
    job = jobs[0]
    if job.get("status") != "completed":
        status = "IN_PROGRESS"
    elif job.get("conclusion") == "success":
        status = "PRODUCER_JOB_SUCCESS_ONLY"
    elif job.get("conclusion") in ("failure", "cancelled", "timed_out"):
        status = "PRODUCER_JOB_FAILED"
    else:
        status = "UNKNOWN"
    return {"status": status, "job_id": job.get("id"),
            "note": "Marker freshness and downstream publication unverified."}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--expected-utc", required=True)
    p.add_argument("--token-env", default="GITHUB_TOKEN")
    a = p.parse_args(argv)
    request = urllib.request.Request(API + "?per_page=50&event=schedule",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "devflow-projection-schedule-probe"})
    token = os.environ.get(a.token_env)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
        result = classify_run(payload, expected_utc=a.expected_utc)
        if result["status"] == "WORKFLOW_SUCCESS_ONLY" and isinstance(result.get("run_id"), int):
            jobs_url = ("https://api.github.com/repos/kinoko34077/devflow/actions/runs/"
                        + str(result["run_id"]) + "/jobs?per_page=100")
            jobs_request = urllib.request.Request(jobs_url, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "devflow-projection-schedule-probe",
            })
            if token:
                jobs_request.add_header("Authorization", "Bearer " + token)
            with urllib.request.urlopen(jobs_request, timeout=15) as response:
                result = {**result, **classify_projection_job(json.load(response))}
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        result = {"status": "UNKNOWN", "reason": type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PRODUCER_JOB_SUCCESS_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
