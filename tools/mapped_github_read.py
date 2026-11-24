"""Representative GitHub metadata adapter using the existing GET-only Reader."""
from __future__ import annotations

from tools.devflow_mcp_core import (
    DevflowMCPError, GitHubReader, MAX_GITHUB_REST_PER_PAGE,
    validate_updated_range_options,
)
from tools.devflow_read_errors import failure_reason_code
from tools.mapped_read import MappedReadError, SourceMap, SourceObservation


def github_source_maps(reader: GitHubReader) -> dict[str, SourceMap]:
    """Bind to one existing Reader; no new credential or HTTP client."""
    def source(kind: str, fields: frozenset[str]) -> SourceMap:
        def prepare(lower, upper, filters, budget):
            if not filters.keys() <= ({"state"} if kind == "issue" else set()):
                raise MappedReadError("UNSUPPORTED_FILTER")
            if not budget.keys() <= {"per_page", "max_pages"}:
                raise MappedReadError("UNSUPPORTED_BUDGET")
            state = filters.get("state")
            per_page = budget.get("per_page", MAX_GITHUB_REST_PER_PAGE)
            max_pages = budget.get("max_pages", 3)
            try:
                state, _, _ = validate_updated_range_options(
                    kind, state, lower, upper, per_page, max_pages)
            except DevflowMCPError:
                raise MappedReadError("INVALID_SOURCE_OPTIONS") from None

            def read(repository: str) -> SourceObservation:
                try:
                    result = reader.read_updated_range(
                        repository, kind=kind, from_utc=lower, to_utc=upper,
                        state=state, per_page=per_page, max_pages=max_pages)
                except DevflowMCPError as exc:
                    return SourceObservation((), "BLOCKED", "GITHUB_READ_FAILED",
                                             (failure_reason_code(exc),))
                if result["status"] not in ("BOUNDED_WINDOW_READ", "PARTIAL_UNKNOWN"):
                    raise MappedReadError("INVALID_SOURCE_OBSERVATION")
                return SourceObservation(
                    tuple(result["items"]),
                    "BOUNDED_READ" if result["status"] == "BOUNDED_WINDOW_READ" else "PARTIAL_UNKNOWN",
                    result["status"], tuple(result["reason_codes"]),
                    snapshot_atomic=result["snapshot_atomic"],
                    requires_source_revalidation=result["requires_source_revalidation"],
                    read_units=result["read_pages"],
                )
            return read
        return SourceMap("kinoko34077/devflow", "github.updated_at", fields, prepare)

    common = frozenset({"id", "html_url", "created_at", "updated_at"})
    return {
        "github.issue": source("issue", common | {"number", "state", "title"}),
        "github.issue_comment": source("issue_comment", common | {"issue_url"}),
    }
