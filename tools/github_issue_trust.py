from __future__ import annotations

from typing import Any, Mapping


TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def normalized_author_association(issue: Mapping[str, Any]) -> str:
    return str(issue.get("author_association") or "").strip().upper()


def is_trusted_issue_author(issue: Mapping[str, Any]) -> bool:
    """Return direct GitHub Issue author trust from author_association.

    Missing association data and bot/outsider associations fail closed.
    Provenance-derived trust, when applicable to a specific control plane,
    remains owned by that control plane and is intentionally not inferred here.
    """
    return normalized_author_association(issue) in TRUSTED_AUTHOR_ASSOCIATIONS
