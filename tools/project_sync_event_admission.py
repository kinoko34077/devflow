"""Fail-closed, no-secret entry gate for Project Sync GitHub Actions events.

The human principal policy is owned by tools.github_issue_trust.
Bot Issues are admitted for *further canonical provenance validation* only;
this preflight alone does not authorize a bot-authored Control.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import github_issue_trust

REPOSITORY = "kinoko34077/devflow"
BOT_ID = 41898282  # GitHub's github-actions[bot] identity, not a human allowlist member.
BOT_LOGIN = "github-actions[bot]"
COMMANDS = frozenset({"/kinotch sync verify", "/kinotch sync reconcile"})
ISSUE_ACTIONS = frozenset({"opened", "edited", "reopened", "closed"})


def _principal_id(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    return None


def _actor_id(value: object) -> int | None:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        return None
    parsed = int(value)
    return parsed if parsed > 0 and str(parsed) == value else None


def _identity(value: object, principal_id: int, login: str) -> bool:
    return (
        isinstance(value, Mapping)
        and _principal_id(value.get("id")) == principal_id
        and value.get("login") == login
    )


def _login_mismatch_has_valid_event_shape(
    event: Mapping[str, object],
    *,
    event_name: str,
    principal_id: int,
    observed_login: str,
) -> bool:
    """Recognize only supported owner events for a bounded reconciliation diagnostic."""
    if (
        not isinstance(observed_login, str)
        or not observed_login
        or not _identity(event.get("sender"), principal_id, observed_login)
    ):
        return False

    if event_name == "workflow_dispatch":
        inputs = event.get("inputs")
        return isinstance(inputs, Mapping) and inputs.get("mode") in {"verify", "reconcile"}

    issue = event.get("issue")
    if not isinstance(issue, Mapping) or "pull_request" in issue:
        return False
    if event_name == "issues":
        creator = issue.get("user")
        owner_authored = (
            isinstance(creator, Mapping)
            and _principal_id(creator.get("id")) == principal_id
            and isinstance(creator.get("login"), str)
            and bool(creator.get("login"))
        )
        bot_control_candidate = (
            _identity(creator, BOT_ID, BOT_LOGIN)
            and str(issue.get("title") or "").startswith("[REPO] ")
        )
        return event.get("action") in ISSUE_ACTIONS and (owner_authored or bot_control_candidate)
    if event_name == "issue_comment":
        comment = event.get("comment")
        comment_user = comment.get("user") if isinstance(comment, Mapping) else None
        issue_author = issue.get("user")
        return (
            event.get("action") == "created"
            and isinstance(issue_author, Mapping)
            and _principal_id(issue_author.get("id")) == principal_id
            and isinstance(issue_author.get("login"), str)
            and bool(issue_author.get("login"))
            and isinstance(comment, Mapping)
            and _identity(comment_user, principal_id, observed_login)
            and comment.get("body") in COMMANDS
        )
    return False


def admitted(
    event: object, *,
    event_name: str,
    actor_id: str,
    actor_login: str,
    triggering_actor: str,
    repository: str,
) -> bool:
    return admission_decision(
        event,
        event_name=event_name,
        actor_id=actor_id,
        actor_login=actor_login,
        triggering_actor=triggering_actor,
        repository=repository,
    ) == "ADMITTED"


def admission_decision(
    event: object, *,
    event_name: str,
    actor_id: str,
    actor_login: str,
    triggering_actor: str,
    repository: str,
) -> str:
    """Return admission status without granting effects on a login mismatch."""
    if not isinstance(event, Mapping) or repository != REPOSITORY:
        return "UNTRUSTED"
    repo = event.get("repository")
    if not isinstance(repo, Mapping) or repo.get("full_name") != REPOSITORY:
        return "UNTRUSTED"
    principal_id = _actor_id(actor_id)
    if principal_id is None:
        return "UNTRUSTED"
    owner_login = github_issue_trust.TRUSTED_PRINCIPAL_IDS.get(principal_id)
    if owner_login is not None:
        if actor_login != owner_login:
            if (
                triggering_actor == actor_login
                and _login_mismatch_has_valid_event_shape(
                    event,
                    event_name=event_name,
                    principal_id=principal_id,
                    observed_login=actor_login,
                )
            ):
                return github_issue_trust.EXPECTED_LOGIN_RECONCILIATION_REQUIRED
            return "UNTRUSTED"
        if triggering_actor != owner_login:
            return "UNTRUSTED"
    elif principal_id == BOT_ID and event_name == "issues":
        if actor_login != BOT_LOGIN or triggering_actor != BOT_LOGIN:
            return "UNTRUSTED"
    else:
        return "UNTRUSTED"
    sender = event.get("sender")
    if not _identity(sender, principal_id, owner_login or BOT_LOGIN):
        return "UNTRUSTED"

    if event_name == "workflow_dispatch":
        if owner_login is None:
            return "UNTRUSTED"
        inputs = event.get("inputs")
        if isinstance(inputs, Mapping) and inputs.get("mode") in {"verify", "reconcile"}:
            return "ADMITTED"
        return "UNTRUSTED"

    issue = event.get("issue")
    if not isinstance(issue, Mapping) or "pull_request" in issue:
        return "UNTRUSTED"
    if event_name == "issue_comment":
        if owner_login is None:
            return "UNTRUSTED"
        if event.get("action") != "created":
            return "UNTRUSTED"
        creator = issue.get("user")
        creator_decision = github_issue_trust.assess_principal(creator)
        comment = event.get("comment")
        comment_user = comment.get("user") if isinstance(comment, Mapping) else None
        comment_decision = github_issue_trust.assess_principal(comment_user)
        if not isinstance(comment, Mapping) or comment.get("body") not in COMMANDS:
            return "UNTRUSTED"
        if (
            creator_decision == github_issue_trust.EXPECTED_LOGIN_RECONCILIATION_REQUIRED
            and isinstance(creator, Mapping)
            and _principal_id(creator.get("id")) == principal_id
            and _identity(comment_user, principal_id, owner_login)
        ):
            return creator_decision
        if (
            comment_decision == github_issue_trust.EXPECTED_LOGIN_RECONCILIATION_REQUIRED
            and _identity(creator, principal_id, owner_login)
        ):
            return comment_decision
        if (
            creator_decision == github_issue_trust.PRINCIPAL_TRUSTED
            and _identity(creator, principal_id, owner_login)
            and _identity(comment_user, principal_id, owner_login)
        ):
            return "ADMITTED"
        return "UNTRUSTED"

    if event_name != "issues" or event.get("action") not in ISSUE_ACTIONS:
        return "UNTRUSTED"
    creator = issue.get("user")
    if owner_login is not None:
        # A canonical bot-created Control may be edited by the owner;
        # the sync script subsequently checks its devflow-owned provenance.
        creator_decision = github_issue_trust.assess_principal(creator)
        if creator_decision == github_issue_trust.EXPECTED_LOGIN_RECONCILIATION_REQUIRED:
            return creator_decision
        if (
            (
                creator_decision == github_issue_trust.PRINCIPAL_TRUSTED
                and _identity(creator, principal_id, owner_login)
            )
            or (
                _identity(creator, BOT_ID, BOT_LOGIN)
                and str(issue.get("title") or "").startswith("[REPO] ")
            )
        ):
            return "ADMITTED"
        return "UNTRUSTED"
    # The sole machine exception is a bot event on a bot-authored Control;
    # this does NOT remove the canonical downstream provenance verifier.
    if (
        _identity(creator, BOT_ID, BOT_LOGIN)
        and str(issue.get("title") or "").startswith("[REPO] ")
    ):
        return "ADMITTED"
    return "UNTRUSTED"


def admission_decision_from_env(env: Mapping[str, str] = os.environ) -> str:
    try:
        payload = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (OSError, KeyError, ValueError, TypeError):
        return "UNTRUSTED"
    return admission_decision(
        payload,
        event_name=env.get("GITHUB_EVENT_NAME", ""),
        actor_id=env.get("GITHUB_ACTOR_ID", ""),
        actor_login=env.get("GITHUB_ACTOR", ""),
        triggering_actor=env.get("GITHUB_TRIGGERING_ACTOR", ""),
        repository=env.get("GITHUB_REPOSITORY", ""),
    )


def admitted_from_env(env: Mapping[str, str] = os.environ) -> bool:
    return admission_decision_from_env(env) == "ADMITTED"


def main() -> int:
    decision = admission_decision_from_env()
    accepted = decision == "ADMITTED"
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("admitted=" + ("true" if accepted else "false") + "\n")
    if decision == github_issue_trust.EXPECTED_LOGIN_RECONCILIATION_REQUIRED:
        diagnostic = "EXPECTED_LOGIN_RECONCILIATION_REQUIRED"
        print("project-sync event admission: SKIPPED; reason=" + diagnostic)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(
                    "## Project Sync event admission\n\n"
                    "- Result: SKIPPED (no privileged sync job started)\n"
                    f"- Reason: {diagnostic}\n"
                )
    else:
        print("project-sync event admission: " + ("ADMITTED" if accepted else "SKIPPED"))
    return 0  # An unauthorized event must not cause the privileged job to start.


if __name__ == "__main__":
    raise SystemExit(main())
