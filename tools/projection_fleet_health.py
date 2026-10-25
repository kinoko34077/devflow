"""Independent, read-only fleet cache freshness assessment.

The canonical managed repository listing and Control trust remain owned by
DevflowService. Cache semantics are delegated to existing validated parsers.
No cache repair, consumer admission or scheduling is performed here.
"""
from __future__ import annotations

import re
from typing import Any

from tools import devflow_mcp_core
from tools import human_portfolio_cache
from tools import repository_projection_cache

_REPOSITORY_PATTERN = re.compile(r"^kinoko34077/[A-Za-z0-9_.-]+$")


def _observe_one(service: Any, repository: str, now: str) -> dict[str, object]:
    result: dict[str, object] = {
        "repository": repository,
        "status": "UNKNOWN",
    }
    try:
        control = service.get_repository_control(repository)
        number = control.get("issue_number") if isinstance(control, dict) else None
        if type(number) is not int or number <= 0:
            return {**result, "reason": "INVALID_CONTROL_REFERENCE"}
        issue = service.reader.get_issue(devflow_mcp_core.DEVFLOW_REPOSITORY, number)
        if not isinstance(issue, dict) or issue.get("number") != number:
            return {**result, "reason": "CONTROL_IDENTITY_MISMATCH"}
        if service.is_repository_control_trusted(issue, repository) is not True:
            return {**result, "reason": "CONTROL_UNTRUSTED"}
        body = issue.get("body")
        if not isinstance(body, str):
            return {**result, "reason": "CONTROL_BODY_MISSING"}

        projection = repository_projection_cache.parse_cached_projection(body, repository)
        human = human_portfolio_cache.parse_cached_human_portfolio(body, repository)
        if projection is None or human is None:
            return {**result, "reason": "CACHE_MARKER_MISSING"}

        projection_state = repository_projection_cache.effective_cache_freshness(
            projection.payload, now=now,
        )
        human_state = human_portfolio_cache.effective_cache_freshness(
            human.payload, now=now,
        )
        result.update({
            "control_issue_number": number,
            "projection": projection_state,
            "human_portfolio": human_state,
            "projection_valid_until": projection.payload["valid_until"],
            "human_portfolio_valid_until": human.payload["valid_until"],
        })
        if projection_state == human_state == "CURRENT":
            result["status"] = "CURRENT"
        elif projection_state in ("STALE", "UNAVAILABLE", "UNTRUSTED", "INVALID") or human_state in ("STALE", "UNAVAILABLE", "UNTRUSTED", "INVALID"):
            result["status"] = "DEGRADED"
        else:
            result["status"] = "UNKNOWN"
        return result
    except Exception:
        # Never print source data, token, provider error body or untrusted metadata.
        return {**result, "reason": "CONTROL_OBSERVATION_FAILED"}


def assess_fleet(service: Any, *, now: str) -> dict[str, object]:
    """Assess current trusted caches without inferring missing sources as healthy."""
    try:
        repositories = list(service.list_managed_repositories())
    except Exception:
        return {"status": "UNKNOWN", "reason": "MANAGED_FLEET_DISCOVERY_FAILED",
                "repository_count": None, "results": []}
    if (
        not repositories
        or any(not isinstance(repo, str) or _REPOSITORY_PATTERN.fullmatch(repo) is None
               for repo in repositories)
        or len(set(repositories)) != len(repositories)
    ):
        return {"status": "UNKNOWN", "reason": "INVALID_FLEET_ROSTER",
                "repository_count": None, "results": []}

    results = [_observe_one(service, repository, now) for repository in repositories]
    current = sum(item["status"] == "CURRENT" for item in results)
    degraded = sum(item["status"] == "DEGRADED" for item in results)
    unknown = len(results) - current - degraded
    status = "CURRENT" if current == len(results) else "UNKNOWN" if unknown else "DEGRADED"
    return {
        "status": status,
        "repository_count": len(results),
        "current_count": current,
        "degraded_count": degraded,
        "unknown_count": unknown,
        "results": results,
    }
