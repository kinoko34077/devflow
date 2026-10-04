from __future__ import annotations

from dataclasses import dataclass
from typing import Any


METADATA_BEGIN = "<!-- DEVFLOW_ISSUE_METADATA_V1_BEGIN -->"
METADATA_END = "<!-- DEVFLOW_ISSUE_METADATA_V1_END -->"


class ProjectionMetadataError(ValueError):
    """Raised when a recognized Repository Projection metadata block is invalid."""


@dataclass(frozen=True)
class IssueMetadata:
    schema_version: int
    record_role: str
    type: str
    work_status: str
    scope_ready: bool
    requires_user_confirmation: bool
    external_wait: bool
    priority: str | None = None
    risk: str | None = None
    blocked_by: tuple[str, ...] = ()
    work_order_ref: str | None = None
    implementation_ref: str | None = None
    next_action_tag: str | None = None

    @property
    def is_task(self) -> bool:
        return self.record_role == "TASK"


@dataclass(frozen=True)
class IssueObservation:
    number: int
    url: str
    title: str
    state: str
    author: str
    assignees: tuple[str, ...]
    created_at: str
    updated_at: str
    metadata_status: str
    metadata: IssueMetadata | None = None
    metadata_error: str | None = None


def parse_issue_metadata(body: str) -> IssueMetadata | None:
    """Parse the optional v1 metadata block.

    M1.1 RED seam: absence is already distinguishable from invalid metadata,
    while recognized blocks intentionally remain unimplemented until the RED
    contract is observed in CI.
    """
    if not isinstance(body, str):
        raise ProjectionMetadataError("Issue body must be a string")
    begin_count = body.count(METADATA_BEGIN)
    end_count = body.count(METADATA_END)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise ProjectionMetadataError("Issue metadata markers must occur exactly once")
    raise ProjectionMetadataError("Issue metadata parser not implemented")


def observe_issue(issue: dict[str, Any]) -> IssueObservation:
    """Capture GitHub-native facts and classify metadata without mutating the Issue."""
    user = issue.get("user")
    author = str(user.get("login") or "") if isinstance(user, dict) else ""
    assignees_raw = issue.get("assignees") or []
    assignees = tuple(
        str(item.get("login"))
        for item in assignees_raw
        if isinstance(item, dict) and item.get("login")
    )
    try:
        metadata = parse_issue_metadata(str(issue.get("body") or ""))
        status = "MACHINE" if metadata is not None else "UNCLASSIFIED"
        error = None
    except ProjectionMetadataError as exc:
        metadata = None
        status = "INVALID"
        error = str(exc)
    return IssueObservation(
        number=int(issue.get("number") or 0),
        url=str(issue.get("html_url") or ""),
        title=str(issue.get("title") or ""),
        state=str(issue.get("state") or ""),
        author=author,
        assignees=assignees,
        created_at=str(issue.get("created_at") or ""),
        updated_at=str(issue.get("updated_at") or ""),
        metadata_status=status,
        metadata=metadata,
        metadata_error=error,
    )
