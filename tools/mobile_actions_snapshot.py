"""Generate sanitized build-time fallback for the existing public mobile Pages app.

No browser credentials, write APIs, scheduling, or Issue mutation. This is
only a timestamped snapshot; it must never imply current liveness.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com/repos/kinoko34077/devflow"
ISSUE_PATH = "/issues/554"
RUNS_PATH = "/actions/workflows/gpt-liveness-f8-manual.yml/runs?per_page=5"
SCHEMA = "devflow.mobile-actions-snapshot.v1"
ENROLLMENT_RE = re.compile(r"<!-- gpt-liveness:enrollment:v0\.1 (\{[^\n]*\}) -->")


def iso_time(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def enrollment_status(body: object, now: datetime) -> str:
    if not isinstance(body, str):
        return "判定不可"
    marks = ENROLLMENT_RE.findall(body)
    if not marks:
        return "未登録"
    if len(marks) != 1:
        return "判定不可（複数）"
    try:
        obj = json.loads(marks[0])
    except (ValueError, TypeError):
        return "判定不可"
    if not isinstance(obj, dict) or obj.get("schema") != "gpt.liveness.v0.1":
        return "判定不可"
    if type(obj.get("enabled")) is not bool:
        return "判定不可"
    if not obj["enabled"]:
        return "無効"
    start, end = iso_time(obj.get("started_at")), iso_time(obj.get("expires_at"))
    if start is None or end is None or end <= start:
        return "判定不可"
    if now >= end:
        return "期限切れ"
    if now < start:
        return "開始前"
    return "登録マーカー有効（要再検証）"


def sanitize_issue(data: object, now: datetime) -> tuple[dict[str, object] | None, str | None]:
    if not isinstance(data, dict) or data.get("number") != 554:
        return None, None
    if data.get("state") not in ("open", "closed"):
        return None, None
    comments = data.get("comments")
    if type(comments) is not int or comments < 0:
        comments = None
    return {"number": 554, "state": data["state"], "comments": comments}, enrollment_status(data.get("body"), now)


def sanitize_runs(data: object) -> dict[str, list[dict[str, object]]] | None:
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        return None
    selected = []
    for run in data["workflow_runs"][:5]:
        if not isinstance(run, dict):
            continue
        selected.append({
            "run_number": run.get("run_number") if type(run.get("run_number")) is int else None,
            "event": run.get("event") if isinstance(run.get("event"), str) else None,
            "status": run.get("status") if isinstance(run.get("status"), str) else None,
            "conclusion": run.get("conclusion") if isinstance(run.get("conclusion"), str) else None,
            "created_at": run.get("created_at") if isinstance(run.get("created_at"), str) else None,
        })
    return {"workflow_runs": selected}


def build_snapshot(issue: object, runs: object, now: datetime) -> dict[str, object]:
    issue_info, enrollment = sanitize_issue(issue, now)
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "issue": issue_info,
        "enrollment_status": enrollment,
        "runs": sanitize_runs(runs),
        "source": "github-actions-build",
    }


def github_get(path: str, token: str) -> object:
    if path not in (ISSUE_PATH, RUNS_PATH):
        raise ValueError("Unapproved GitHub API resource")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "kinotch-mobile-actions-snapshot",
        "Authorization": "Bearer " + token,
    }
    request = urllib.request.Request(API_ROOT + path, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # Env token is for the GitHub-hosted Pages build runner only; never serialized.
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise SystemExit("GH_TOKEN required for build-time read-only snapshot")
    now = datetime.now(timezone.utc)
    results: list[object | None] = []
    errors: list[str] = []
    for kind, path in (("issue", ISSUE_PATH), ("runs", RUNS_PATH)):
        try:
            results.append(github_get(path, token))
        except urllib.error.HTTPError as exc:
            results.append(None)
            errors.append(f"{kind}: HTTP {exc.code}")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            results.append(None)
            errors.append(f"{kind}: 通信失敗")
    output = build_snapshot(results[0], results[1], now)
    output["errors"] = errors
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    # Errors are reflected as "unconfirmed" in JSON and must not turn into "stopped".
    print("MOBILE_SNAPSHOT_READONLY " + ("OK" if not errors else "PARTIAL_UNCONFIRMED"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
