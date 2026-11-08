from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# The numeric GitHub user ID is the canonical authority key.  The login is
# retained as secondary consistency evidence and is never used as the key.
TRUSTED_PRINCIPAL_IDS = MappingProxyType({79015263: "kinoko34077"})
PRINCIPAL_TRUSTED = "TRUSTED"
PRINCIPAL_UNTRUSTED = "UNTRUSTED"
ISSUE_AUTHOR_TRUSTED = PRINCIPAL_TRUSTED
ISSUE_AUTHOR_UNTRUSTED = PRINCIPAL_UNTRUSTED
EXPECTED_LOGIN_RECONCILIATION_REQUIRED = "EXPECTED_LOGIN_RECONCILIATION_REQUIRED"
TRUSTED_ISSUE_EVENT_ACTIONS = frozenset({"opened", "edited", "reopened"})


def _event_actor_id(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 and str(parsed) == value else None


def is_trusted_issue_event_actor(
    event: object,
    *,
    event_name: object,
    actor_id: object,
    actor_login: object,
    triggering_actor: object,
    repository: object,
    expected_repository: str,
) -> bool:
    """Admit only the allowlisted principal that initiated an Issue event.

    The event payload sender and GitHub Actions context must describe the same
    canonical principal. Issue authorship is checked separately by the
    consumer; an authorized editor does not make an untrusted request author
    trusted.
    """
    if (
        not isinstance(event, Mapping)
        or event_name != "issues"
        or repository != expected_repository
    ):
        return False
    repo = event.get("repository")
    issue = event.get("issue")
    action = event.get("action")
    if (
        not isinstance(repo, Mapping)
        or repo.get("full_name") != expected_repository
        or not isinstance(issue, Mapping)
        or "pull_request" in issue
        or not isinstance(action, str)
        or action not in TRUSTED_ISSUE_EVENT_ACTIONS
    ):
        return False
    number = issue.get("number")
    if type(number) is not int or number <= 0:
        return False
    if issue.get("html_url") != f"https://github.com/{expected_repository}/issues/{number}":
        return False

    parsed_actor_id = _event_actor_id(actor_id)
    if parsed_actor_id is None:
        return False
    expected_login = TRUSTED_PRINCIPAL_IDS.get(parsed_actor_id)
    if (
        expected_login is None
        or actor_login != expected_login
        or triggering_actor != expected_login
    ):
        return False
    sender = event.get("sender")
    return (
        isinstance(sender, Mapping)
        and type(sender.get("id")) is int
        and sender.get("id") == parsed_actor_id
        and sender.get("login") == expected_login
    )


def normalized_author_association(issue: Mapping[str, Any]) -> str:
    return str(issue.get("author_association") or "").strip().upper()


def assess_principal(principal: object) -> str:
    """Return the canonical GitHub-principal trust decision.

    ``author_association`` is provenance/defense-in-depth metadata only. A
    missing, malformed, or unlisted numeric ID fails closed. A missing login
    does not contradict the numeric ID in this shared decision; consumers with
    stricter event contracts must check its presence themselves. A supplied
    malformed login fails closed, while a different nonempty login for an
    allowlisted ID is distinguished so a consumer may surface reconciliation
    without weakening the decision or echoing untrusted content. Provenance-
    derived trust remains owned by its control plane and is not inferred here.
    """
    if not isinstance(principal, Mapping):
        return PRINCIPAL_UNTRUSTED
    principal_id = principal.get("id")
    if isinstance(principal_id, bool) or not isinstance(principal_id, int):
        return PRINCIPAL_UNTRUSTED
    expected_login = TRUSTED_PRINCIPAL_IDS.get(principal_id)
    if expected_login is None:
        return PRINCIPAL_UNTRUSTED
    observed_login = principal.get("login")
    if observed_login is not None:
        if not isinstance(observed_login, str) or not observed_login:
            return PRINCIPAL_UNTRUSTED
        if observed_login != expected_login:
            return EXPECTED_LOGIN_RECONCILIATION_REQUIRED
    return PRINCIPAL_TRUSTED


def assess_issue_author(issue: Mapping[str, Any]) -> str:
    """Return direct Issue-author trust from the shared principal decision."""
    return assess_principal(issue.get("user"))


def is_trusted_issue_author(issue: Mapping[str, Any]) -> bool:
    """Return direct GitHub Issue author trust from the canonical decision."""
    return assess_issue_author(issue) == ISSUE_AUTHOR_TRUSTED


# Issue comments and Issue objects expose the same ``user.id`` identity
# shape.  Keep one canonical implementation while retaining the historical
# function name for callers that deal specifically with Issues.
is_trusted_principal = is_trusted_issue_author
