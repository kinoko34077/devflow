from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CACHE_MARKER_BEGIN = "<!-- DEVFLOW_REPOSITORY_PROJECTION_V1_BEGIN -->"
CACHE_MARKER_END = "<!-- DEVFLOW_REPOSITORY_PROJECTION_V1_END -->"
CACHE_SCHEMA_VERSION = "repository-projection-cache.v1"


class RepositoryProjectionCacheError(ValueError):
    pass


@dataclass(frozen=True)
class CachedRepositoryProjection:
    payload: dict[str, Any]


def parse_cached_projection(body: str, repository: str) -> CachedRepositoryProjection | None:
    text = str(body or "")
    if CACHE_MARKER_BEGIN not in text and CACHE_MARKER_END not in text:
        return None
    raise RepositoryProjectionCacheError("repository projection cache parser not implemented")


def replace_cached_projection(
    body: str,
    repository: str,
    payload: dict[str, Any],
    *,
    expected_body_sha256: str,
) -> str:
    del body, repository, payload, expected_body_sha256
    raise RepositoryProjectionCacheError("repository projection cache replacement not implemented")


def build_cached_projection(
    repository: str,
    live_projection: dict[str, Any],
    *,
    generated_at: str,
    control_trust: dict[str, Any],
    machine_metadata_complete: bool,
) -> dict[str, Any]:
    del repository, live_projection, generated_at, control_trust, machine_metadata_complete
    raise RepositoryProjectionCacheError("repository projection cache builder not implemented")
