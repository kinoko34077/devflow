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


def admitted(
    event: object, *,
    event_name: str,
    actor_id: str,
    actor_login: str,
    triggering_actor: str,
    repository: str,
) -> bool:
    if not isinstance(event, Mapping) or repository != REPOSITORY:
        return False
    repo = event.get("repository")
    if not isinstance(repo, Mapping) or repo.get("full_name") != REPOSITORY:
        return False
    principal_id = _actor_id(actor_id)
    if principal_id is None:
        return False
    owner_login = github_issue_trust.TRUSTED_PRINCIPAL_IDS.get(principal_id)
    if owner_login is not None:
        if actor_login != owner_login or triggering_actor != owner_login:
            return False
    elif principal_id == BOT_ID and event_name == "issues":
        if actor_login != BOT_LOGIN or triggering_actor != BOT_LOGIN:
            return False
    else:
        return False
    if not _identity(event.get("sender"), principal_id, owner_login or BOT_LOGIN):
        return False

    if event_name == "workflow_dispatch":
        if owner_login is None:
            return False
        inputs = event.get("inputs")
        return isinstance(inputs, Mapping) and inputs.get("mode") in {"verify", "reconcile"}

    issue = event.get("issue")
    if not isinstance(issue, Mapping) or "pull_request" in issue:
        return False
    if event_name == "issue_comment":
        return (
            owner_login is not None
            and _identity(issue.get("user"), principal_id, owner_login)
            and _identity(event.get("comment", {}).get("user") if isinstance(event.get("comment"), Mapping) else None, principal_id, owner_login)
            and event["comment"].get("body") in COMMANDS
        )

    if event_name != "issues" or event.get("action") not in ISSUE_ACTIONS:
        return False
    creator = issue.get("user")
    if owner_login is not None:
        # A canonical bot-created Control may be edited by the owner;
        # the sync script subsequently checks its devflow-owned provenance.
        return (
            _identity(creator, principal_id, owner_login)
            or (_identity(creator, BOT_ID, BOT_LOGIN) and
                str(issue.get("title") or "").startswith("[REPO] "))
        )
    # The sole machine exception is a bot event on a bot-authored Control;
    # this does NOT remove the canonical downstream provenance verifier.
    return (
        _identity(creator, BOT_ID, BOT_LOGIN)
        and str(issue.get("title") or "").startswith("[REPO] ")
    )


def admitted_from_env(env: Mapping[str, str] = os.environ) -> bool:
    try:
        payload = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (OSError, KeyError, ValueError, TypeError):
        return False
    return admitted(
        payload,
        event_name=env.get("GITHUB_EVENT_NAME", ""),
        actor_id=env.get("GITHUB_ACTOR_ID", ""),
        actor_login=env.get("GITHUB_ACTOR", ""),
        triggering_actor=env.get("GITHUB_TRIGGERING_ACTOR", ""),
        repository=env.get("GITHUB_REPOSITORY", ""),
    )


def main() -> int:
    accepted = admitted_from_env()
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("admitted=" + ("true" if accepted else "false") + "\n")
    print("project-sync event admission: " + ("ADMITTED" if accepted else "SKIPPED"))
    return 0  # An unauthorized event must not cause the privileged job to start.


if __name__ == "__main__":
    raise SystemExit(main())
