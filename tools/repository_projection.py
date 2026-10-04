from __future__ import annotations

ISSUE_METADATA_BEGIN = "<!-- DEVFLOW_ISSUE_METADATA_V1_BEGIN -->"
ISSUE_METADATA_END = "<!-- DEVFLOW_ISSUE_METADATA_V1_END -->"


class RepositoryProjectionError(ValueError):
    """Malformed or unsupported Repository Projection input."""


def parse_issue_metadata(body: str):
    """Parse one optional repository-local machine metadata block."""
    raise NotImplementedError("M1.1 RED seam")


def classify_issue(issue: dict):
    """Classify one GitHub Issue without treating open state as task authority."""
    raise NotImplementedError("M1.1 RED seam")
