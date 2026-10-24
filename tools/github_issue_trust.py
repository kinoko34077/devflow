from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# The numeric GitHub user ID is the canonical authority key.  The login is
# retained as secondary consistency evidence and is never used as the key.
TRUSTED_PRINCIPAL_IDS = MappingProxyType({79015263: "kinoko34077"})


def normalized_author_association(issue: Mapping[str, Any]) -> str:
    return str(issue.get("author_association") or "").strip().upper()


def is_trusted_issue_author(issue: Mapping[str, Any]) -> bool:
    """Return direct GitHub Issue author trust from the numeric user ID.

    ``author_association`` is provenance/defense-in-depth metadata only.  A
    missing, malformed, unlisted, or login-only identity fails closed.  The
    expected login is checked when GitHub supplies it so a renamed or spoofed
    display name is not silently trusted.  Provenance-derived trust, when
    applicable to a specific control plane, remains owned by that control
    plane and is intentionally not inferred here.
    """
    user = issue.get("user")
    if not isinstance(user, Mapping):
        return False
    principal_id = user.get("id")
    if isinstance(principal_id, bool) or not isinstance(principal_id, int):
        return False
    expected_login = TRUSTED_PRINCIPAL_IDS.get(principal_id)
    if expected_login is None:
        return False
    observed_login = user.get("login")
    if observed_login is not None and observed_login != expected_login:
        return False
    return True


# Issue comments and Issue objects expose the same ``user.id`` identity
# shape.  Keep one canonical implementation while retaining the historical
# function name for callers that deal specifically with Issues.
is_trusted_principal = is_trusted_issue_author
