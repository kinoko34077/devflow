from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


def prepare_target(
    service: Any,
    repository: str,
    control_issue_number: int,
    *,
    generated_at: str,
) -> CacheWritePlan:
    del service, repository, control_issue_number, generated_at
    raise RepositoryProjectionCacheProducerError("cache producer plan not implemented")


def apply_plan(writer: Any, plan: CacheWritePlan) -> dict[str, Any]:
    del writer, plan
    raise RepositoryProjectionCacheProducerError("cache producer apply not implemented")
