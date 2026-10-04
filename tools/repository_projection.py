from __future__ import annotations

from dataclasses import dataclass


ISSUE_METADATA_MARKER_BEGIN = "<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V1_BEGIN -->"
ISSUE_METADATA_MARKER_END = "<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V1_END -->"


class ProjectionContractError(ValueError):
    pass


@dataclass(frozen=True)
class IssueMetadata:
    schema_version: int
    record_role: str
    type: str
    work_status: str
    scope_ready: bool
    requires_user_confirmation: bool
    external_wait: bool

    @property
    def is_task(self) -> bool:
        return self.record_role == "TASK"


def parse_issue_metadata(body: str) -> IssueMetadata | None:
    text = str(body or "")
    if (
        ISSUE_METADATA_MARKER_BEGIN not in text
        and ISSUE_METADATA_MARKER_END not in text
    ):
        return None
    raise ProjectionContractError("repository Issue metadata parser not implemented")
