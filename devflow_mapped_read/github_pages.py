"""Shared native GitHub Issue/comment query and bounded page progression.

No transport, credentials, projection, or domain identity authority.
The trusted source owner supplies the GET callback and completion semantics.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from . import MappedReadError, _REPOSITORY, parse_utc_timestamp


@dataclass(frozen=True)
class RepositoryIssueQuery:
    repository: str
    kind: str
    per_page: int = 100
    state: str | None = None
    sort: str | None = None
    direction: str | None = None
    native_since: str | None = None

    def __post_init__(self) -> None:
        if (type(self.repository) is not str
                or not _REPOSITORY.fullmatch(self.repository)
                or any(part in (".", "..") for part in self.repository.split("/"))):
            raise MappedReadError("INVALID_REPOSITORY_SCOPE")
        if self.kind not in ("issue", "issue_comment"):
            raise MappedReadError("UNSUPPORTED_DATASET")
        if (self.state not in (None, "all", "open", "closed")
                or self.kind == "issue_comment" and self.state is not None):
            raise MappedReadError("UNSUPPORTED_FILTER")
        if (self.sort not in (None, "updated", "created")
                or self.direction not in (None, "asc", "desc")):
            raise MappedReadError("UNSUPPORTED_FILTER")
        if type(self.per_page) is not int or not 1 <= self.per_page <= 100:
            raise MappedReadError("INVALID_SOURCE_OPTIONS")
        if self.native_since is not None:
            parse_utc_timestamp(self.native_since, seconds_only=True)

    def path(self, page: int) -> str:
        if type(page) is not int or page < 1:
            raise MappedReadError("INVALID_SOURCE_OPTIONS")
        owner, name = self.repository.split("/")
        endpoint = "issues" if self.kind == "issue" else "issues/comments"
        query = {}
        if self.sort is not None:
            query["sort"] = self.sort
        if self.direction is not None:
            query["direction"] = self.direction
        query["per_page"] = self.per_page
        if self.state is not None:
            query["state"] = self.state
        query["page"] = page
        if self.native_since is not None:
            query["since"] = self.native_since
        return (f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}/{endpoint}?"
                + urlencode(query, safe=":"))


@dataclass(frozen=True)
class ListPage:
    number: int
    rows: list[Any]
    has_next: bool


def observe_page(number: int, rows: Any, *, per_page: int,
                 has_next: bool | None = None) -> ListPage:
    """Explicit Link evidence wins; without it a full page is uncertain."""
    if (type(number) is not int or number < 1
            or type(per_page) is not int or not 1 <= per_page <= 100):
        raise MappedReadError("INVALID_SOURCE_OPTIONS")
    if (not isinstance(rows, list) or len(rows) > per_page
            or has_next is not None and type(has_next) is not bool
            or has_next is True and not rows):
        raise MappedReadError("INVALID_LIST_PAGE")
    return ListPage(number, rows, len(rows) == per_page if has_next is None else has_next)


def iter_list_pages(
    fetch_page: Callable[[int], tuple[Any, bool | None]], *, per_page: int,
    max_pages: int, start_page: int = 1,
) -> Iterator[ListPage]:
    """Fetch at most the owner's budget; preserve last-page uncertainty."""
    if (type(max_pages) is not int or max_pages < 1
            or type(start_page) is not int or start_page < 1
            or type(per_page) is not int or not 1 <= per_page <= 100):
        raise MappedReadError("INVALID_SOURCE_OPTIONS")
    for page in range(start_page, start_page + max_pages):
        rows, has_next = fetch_page(page)
        observed = observe_page(page, rows, per_page=per_page, has_next=has_next)
        yield observed
        if not observed.has_next:
            return
