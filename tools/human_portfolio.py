from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from tools import reconciliation_publication, repository_projection


ATTENTION_DISPOSITIONS = frozenset(
    {"NEEDS_HUMAN", "WAIT_EXTERNAL", "NEEDS_EVIDENCE"}
)
RECONCILIATION_DISPOSITIONS = frozenset(
    {"NEEDS_REVIEWER", "NEEDS_RECOVERY"}
)
TASK_QUEUE_DISPOSITIONS = frozenset({"READY", "IMPLEMENTING"})
ALL_DISPOSITIONS = (
    ATTENTION_DISPOSITIONS
    | RECONCILIATION_DISPOSITIONS
    | TASK_QUEUE_DISPOSITIONS
)


@dataclass(frozen=True)
class HumanPortfolioEntry:
    repository: str
    task_ref: str
    entry_ref: str | None
    disposition: str
    role: str
    source_kind: str
    observed_at: str
    work_status: str | None = None
    publication_id: str | None = None

    def __post_init__(self) -> None:
        if self.disposition not in ALL_DISPOSITIONS:
            raise ValueError(f"unsupported Human Portfolio disposition: {self.disposition}")
        if not self.task_ref.startswith(self.repository + "#"):
            raise ValueError("task_ref must belong to repository")
        if not self.role:
            raise ValueError("role must not be empty")
        if self.source_kind not in {"REPOSITORY_PROJECTION", "RECONCILIATION"}:
            raise ValueError("unsupported Human Portfolio source_kind")


@dataclass(frozen=True)
class HumanPortfolioRead:
    repository: str
    observed_at: str
    source_status: str
    source_freshness: str
    source_error: str | None
    complete: bool
    entries: tuple[HumanPortfolioEntry, ...]


def _projection_entries(
    projection: repository_projection.RepositoryProjection,
) -> list[HumanPortfolioEntry]:
    entries: list[HumanPortfolioEntry] = []
    for record in projection.records:
        task_ref = f"{projection.repository}#{record.number}"
        role = record.record_role or "UNKNOWN"

        if record.attention_disposition is not None:
            if record.attention_disposition not in ATTENTION_DISPOSITIONS:
                raise ValueError(
                    "Repository Projection produced an unsupported attention disposition"
                )
            entries.append(
                HumanPortfolioEntry(
                    repository=projection.repository,
                    task_ref=task_ref,
                    entry_ref=record.html_url,
                    disposition=record.attention_disposition,
                    role=role,
                    source_kind="REPOSITORY_PROJECTION",
                    observed_at=projection.observed_at,
                    work_status=record.work_status,
                )
            )
            continue

        if not record.is_task:
            continue
        disposition = {
            "READY_FOR_IMPLEMENTATION": "READY",
            "IMPLEMENTING": "IMPLEMENTING",
        }.get(record.work_status)
        if disposition is None:
            continue
        entries.append(
            HumanPortfolioEntry(
                repository=projection.repository,
                task_ref=task_ref,
                entry_ref=record.html_url,
                disposition=disposition,
                role=role,
                source_kind="REPOSITORY_PROJECTION",
                observed_at=projection.observed_at,
                work_status=record.work_status,
            )
        )
    return entries


def _validated_publications(
    repository: str,
    publications: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    # Reuse the accepted projection renderer/parser as the only publication
    # validation authority instead of implementing a second validator here.
    block = reconciliation_publication.render_publication_projection(
        repository,
        list(publications),
    )
    return reconciliation_publication.parse_publication_projection(
        block,
        repository,
    )


def _reconciliation_entries(
    repository: str,
    publications: Iterable[dict[str, Any]],
) -> list[HumanPortfolioEntry]:
    entries: list[HumanPortfolioEntry] = []
    seen_task_roles: set[tuple[str, str]] = set()
    for publication in _validated_publications(repository, publications):
        task_ref = str(publication["task_ref"])
        role = str(publication["role"])
        key = (task_ref, role)
        if key in seen_task_roles:
            raise ValueError(
                "Human Portfolio reconciliation demand contains duplicate task/role"
            )
        seen_task_roles.add(key)

        disposition = str(publication["disposition"])
        if disposition not in RECONCILIATION_DISPOSITIONS:
            raise ValueError("unsupported reconciliation disposition")
        entries.append(
            HumanPortfolioEntry(
                repository=repository,
                task_ref=task_ref,
                entry_ref=str(publication["entry_ref"]),
                disposition=disposition,
                role=role,
                source_kind="RECONCILIATION",
                observed_at=str(publication["observed_at"]),
                publication_id=str(publication["publication_id"]),
            )
        )
    return entries


def build_repository_human_portfolio(
    projection: repository_projection.RepositoryProjection,
    *,
    reconciliation_publications: Iterable[dict[str, Any]] = (),
) -> HumanPortfolioRead:
    """Build one read-only operator queue from already-validated authorities.

    Source unavailability or non-current freshness is fail-closed: the source
    state remains visible, but no task/reviewer/recovery entry is promoted.
    """

    if not isinstance(projection, repository_projection.RepositoryProjection):
        raise TypeError("projection must be a RepositoryProjection")

    current = (
        projection.source_status == "AVAILABLE"
        and projection.source_freshness == "CURRENT"
    )
    if not current:
        return HumanPortfolioRead(
            repository=projection.repository,
            observed_at=projection.observed_at,
            source_status=projection.source_status,
            source_freshness=projection.source_freshness,
            source_error=projection.source_error,
            complete=False,
            entries=(),
        )

    entries = _projection_entries(projection)
    entries.extend(
        _reconciliation_entries(
            projection.repository,
            reconciliation_publications,
        )
    )
    entries.sort(
        key=lambda item: (
            item.disposition,
            item.task_ref,
            item.role,
            item.source_kind,
            item.publication_id or "",
        )
    )
    return HumanPortfolioRead(
        repository=projection.repository,
        observed_at=projection.observed_at,
        source_status=projection.source_status,
        source_freshness=projection.source_freshness,
        source_error=projection.source_error,
        complete=True,
        entries=tuple(entries),
    )


def build_human_portfolio(
    projections: Iterable[repository_projection.RepositoryProjection],
    *,
    reconciliation_publications: dict[
        str, Iterable[dict[str, Any]]
    ] | None = None,
) -> tuple[HumanPortfolioRead, ...]:
    """Build deterministic multi-repository Human Portfolio reads."""

    publication_map = reconciliation_publications or {}
    by_repository: dict[str, repository_projection.RepositoryProjection] = {}
    for projection in projections:
        if projection.repository in by_repository:
            raise ValueError("duplicate repository projection")
        by_repository[projection.repository] = projection

    unknown_publication_repositories = set(publication_map) - set(by_repository)
    if unknown_publication_repositories:
        raise ValueError(
            "reconciliation publications reference repositories without projections"
        )

    return tuple(
        build_repository_human_portfolio(
            by_repository[repository],
            reconciliation_publications=publication_map.get(repository, ()),
        )
        for repository in sorted(by_repository)
    )
