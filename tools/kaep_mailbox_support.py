"""Shared read-only KAEP mailbox and actor helpers.

The helpers in this module are transport concerns shared by REQUEST, REPLY,
discovery, and two-phase routing. They do not grant work authority, Claim, or
write permission.
"""
from __future__ import annotations

import re
from typing import Any

from tools.github_issue_trust import is_trusted_principal
from tools.kaep_inbox_reader import parse_pages
from tools.kaep_mailbox_codec import isolate_cross_exchange_replies, read_mailbox

ACTOR = re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9-]{0,38}|github-actions\[bot\])\Z")


def matching_actor(comment: dict[str, Any], expected_login: str) -> bool:
    """Require the configured transport actor and trusted numeric identity."""
    if comment["actor_login"].casefold() != expected_login.casefold():
        return False
    if expected_login.casefold() == "kinoko34077":
        return is_trusted_principal({"user": {
            "id": comment.get("actor_id"), "login": comment["actor_login"]
        }})
    return True


def mailbox_snapshot(
    text: str, *, repository: str, issue: int,
) -> tuple[
    list[dict[str, Any]],
    list[tuple[int, dict[str, Any]]],
    list[tuple[int, dict[str, Any]]],
]:
    """Decode one complete mailbox and retain eligible plus reserved items."""
    comments = parse_pages(text, repository=repository, issue=issue)
    all_items = read_mailbox(comments, task_ref=f"{repository}#{issue}")
    accepted, _quarantined = isolate_cross_exchange_replies(
        [item for _, item in all_items]
    )
    accepted_ids = {item["message_id"] for item in accepted}
    eligible = [
        (cid, item) for cid, item in all_items
        if item["message_id"] in accepted_ids
    ]
    return comments, eligible, all_items


def mailbox(
    text: str, *, repository: str, issue: int,
) -> tuple[list[dict[str, Any]], list[tuple[int, dict[str, Any]]]]:
    """Return the existing two-result eligible-mailbox contract."""
    comments, eligible, _all_items = mailbox_snapshot(
        text, repository=repository, issue=issue,
    )
    return comments, eligible

