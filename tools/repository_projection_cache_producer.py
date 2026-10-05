from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tools import devflow_mcp_core
from tools import maintenance_sync_check
from tools import repository_projection_cache


class RepositoryProjectionCacheProducerError(ValueError):
    pass


@dataclass(frozen=True)
class CacheWritePlan:
    repository: str
    control_issue_number: int
    expected_body_sha256: str
    desired_body: str
    generation_id: str
    changed: bool
    source_status: str
    coverage_status: str


def _require_control_issue_number(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RepositoryProjectionCacheProducerError(
            "Control issue number must be a positive integer"
        )
    return value


def _generation_not_before_observation(
    generated_at: str,
    observed_at: object,
) -> str:
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise RepositoryProjectionCacheProducerError(
            "generated_at must be an RFC-3339 timestamp"
        )
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise RepositoryProjectionCacheProducerError(
            "live projection observed_at is unavailable"
        )
    try:
        generated = datetime.fromisoformat(
            generated_at.strip().replace("Z", "+00:00")
        )
        observed = datetime.fromisoformat(
            observed_at.strip().replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise RepositoryProjectionCacheProducerError(
            "projection timestamps must be RFC-3339"
        ) from exc
    if generated.tzinfo is None or observed.tzinfo is None:
        raise RepositoryProjectionCacheProducerError(
            "projection timestamps must include timezone offsets"
        )
    return observed_at.strip() if observed > generated else generated_at.strip()


def prepare_target(
    service: Any,
    repository: str,
    control_issue_number: int,
    *,
    generated_at: str,
) -> CacheWritePlan:
    control_issue_number = _require_control_issue_number(control_issue_number)

    try:
        control = service.get_repository_control(repository)
    except Exception as exc:
        raise RepositoryProjectionCacheProducerError(
            f"failed to resolve canonical Repository Control: {exc}"
        ) from exc

    canonical_number = control.get("issue_number")
    if canonical_number != control_issue_number:
        raise RepositoryProjectionCacheProducerError(
            "Control issue number does not match canonical Repository Control"
        )

    devflow_repository = getattr(
        service,
        "devflow_repository",
        devflow_mcp_core.DEVFLOW_REPOSITORY,
    )
    try:
        issue = service.reader.get_issue(
            devflow_repository,
            control_issue_number,
        )
    except Exception as exc:
        raise RepositoryProjectionCacheProducerError(
            f"failed to read canonical Repository Control: {exc}"
        ) from exc

    try:
        trusted = bool(
            service.is_repository_control_trusted(
                issue,
                repository,
            )
        )
    except Exception as exc:
        raise RepositoryProjectionCacheProducerError(
            f"failed to verify Repository Control trust: {exc}"
        ) from exc
    if not trusted:
        raise RepositoryProjectionCacheProducerError(
            "Repository Control is not trusted by the shared verifier"
        )

    body = issue.get("body")
    if not isinstance(body, str):
        raise RepositoryProjectionCacheProducerError(
            "Repository Control body is unavailable"
        )

    try:
        live_projection = service.get_repository_projection(repository)
    except Exception as exc:
        raise RepositoryProjectionCacheProducerError(
            f"failed to read live Repository Projection: {exc}"
        ) from exc
    if not isinstance(live_projection, dict):
        raise RepositoryProjectionCacheProducerError(
            "live Repository Projection was not an object"
        )

    observed_at = live_projection.get("observed_at")
    effective_generated_at = _generation_not_before_observation(
        generated_at,
        observed_at,
    )
    control_trust = {
        "status": "VERIFIED",
        "freshness": "CURRENT",
        "source": repository_projection_cache.CONTROL_TRUST_SOURCE,
        "observed_at": observed_at,
        "detail": None,
    }
    try:
        payload = repository_projection_cache.build_cached_projection(
            repository,
            live_projection,
            generated_at=effective_generated_at,
            control_trust=control_trust,
        )
    except repository_projection_cache.RepositoryProjectionCacheError as exc:
        raise RepositoryProjectionCacheProducerError(str(exc)) from exc

    expected_body_sha256 = maintenance_sync_check.canonical_body_sha256(body)
    try:
        desired_body = repository_projection_cache.replace_cached_projection(
            body,
            repository,
            payload,
            expected_body_sha256=expected_body_sha256,
        )
    except repository_projection_cache.RepositoryProjectionCacheError as exc:
        raise RepositoryProjectionCacheProducerError(str(exc)) from exc

    return CacheWritePlan(
        repository=repository,
        control_issue_number=control_issue_number,
        expected_body_sha256=expected_body_sha256,
        desired_body=desired_body,
        generation_id=str(payload["generation_id"]),
        changed=desired_body != body,
        source_status=str(payload["source"]["status"]),
        coverage_status=str(payload["coverage"]["status"]),
    )


def apply_plan(writer: Any, plan: CacheWritePlan) -> dict[str, Any]:
    repository = plan.repository
    devflow_repository = devflow_mcp_core.DEVFLOW_REPOSITORY

    try:
        current = writer.get_issue(
            devflow_repository,
            plan.control_issue_number,
        )
    except Exception as exc:
        raise RepositoryProjectionCacheProducerError(
            f"pre-write Control read failed: {exc}"
        ) from exc
    if not isinstance(current, dict):
        raise RepositoryProjectionCacheProducerError(
            "pre-write Control read did not return an object"
        )
    current_body = current.get("body")
    if not isinstance(current_body, str):
        raise RepositoryProjectionCacheProducerError(
            "pre-write Control body is unavailable"
        )
    if (
        maintenance_sync_check.canonical_body_sha256(current_body)
        != plan.expected_body_sha256
    ):
        raise RepositoryProjectionCacheProducerError(
            "pre-write Control body digest changed"
        )

    if not plan.changed:
        return {
            "status": "NO_ACTION",
            "repository": repository,
            "control_issue_number": plan.control_issue_number,
            "generation_id": plan.generation_id,
            "source_status": plan.source_status,
            "coverage_status": plan.coverage_status,
        }

    try:
        accepted = writer.update_issue_body(
            devflow_repository,
            plan.control_issue_number,
            plan.desired_body,
        )
    except Exception as exc:
        raise RepositoryProjectionCacheProducerError(
            f"Control cache write failed: {exc}"
        ) from exc
    if accepted is not True:
        raise RepositoryProjectionCacheProducerError(
            "Control cache write was not accepted"
        )

    try:
        observed = writer.get_issue(
            devflow_repository,
            plan.control_issue_number,
        )
    except Exception as exc:
        raise RepositoryProjectionCacheProducerError(
            f"post-write Control read failed: {exc}"
        ) from exc
    if not isinstance(observed, dict) or observed.get("body") != plan.desired_body:
        raise RepositoryProjectionCacheProducerError(
            "post-write Control body does not match intended marker-only write"
        )

    try:
        cached = repository_projection_cache.parse_cached_projection(
            plan.desired_body,
            repository,
        )
    except repository_projection_cache.RepositoryProjectionCacheError as exc:
        raise RepositoryProjectionCacheProducerError(
            f"post-write cache readback failed: {exc}"
        ) from exc
    if (
        cached is None
        or cached.payload.get("generation_id") != plan.generation_id
    ):
        raise RepositoryProjectionCacheProducerError(
            "post-write cache generation identity mismatch"
        )

    return {
        "status": "UPDATED",
        "repository": repository,
        "control_issue_number": plan.control_issue_number,
        "generation_id": plan.generation_id,
        "source_status": plan.source_status,
        "coverage_status": plan.coverage_status,
    }

def run_fleet(
    service: Any,
    writer: Any,
    *,
    generated_at: str,
    apply: bool,
) -> dict[str, Any]:
    """Generate Repository Projection caches serially for managed repositories.

    One repository failure is isolated to that repository. Failed preparation or
    write never falls through to a cache mutation for that repository.
    """
    try:
        repositories = list(service.list_managed_repositories())
    except Exception as exc:
        raise RepositoryProjectionCacheProducerError(
            f"failed to list managed repositories: {exc}"
        ) from exc

    results: list[dict[str, Any]] = []
    success_count = 0
    failure_count = 0

    for repository in repositories:
        try:
            control = service.get_repository_control(repository)
            control_number = _require_control_issue_number(
                control.get("issue_number")
            )
            plan = prepare_target(
                service,
                repository,
                control_number,
                generated_at=generated_at,
            )
            if apply:
                item = apply_plan(writer, plan)
            else:
                item = {
                    "status": "PREVIEW",
                    "repository": plan.repository,
                    "control_issue_number": plan.control_issue_number,
                    "generation_id": plan.generation_id,
                    "source_status": plan.source_status,
                    "coverage_status": plan.coverage_status,
                    "changed": plan.changed,
                    "expected_body_sha256": plan.expected_body_sha256,
                }
            results.append(item)
            success_count += 1
        except Exception as exc:
            results.append(
                {
                    "status": "FAILED",
                    "repository": str(repository),
                    "error": str(exc),
                }
            )
            failure_count += 1

    return {
        "mode": "FLEET",
        "repository_count": len(repositories),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
    }

