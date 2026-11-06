"""Shared read-only KAEP mailbox and actor helpers.

The helpers in this module are transport concerns shared by REQUEST, REPLY,
discovery, and two-phase routing. They do not grant work authority, Claim, or
write permission.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from tools.github_issue_trust import is_trusted_principal
from tools.kaep_inbox_reader import (
    InvalidMessage, MAX_RESPONSE_BYTES, REPOSITORY, parse_pages,
)
from tools.kaep_mailbox_codec import (
    encode_comment, fail, fingerprint, isolate_cross_exchange_replies,
    read_mailbox,
)

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


def post_comment(*, repository: str, issue: int, body: str, run_func=None) -> int:
    """Post one ordinary Issue comment; never an Action or Claim operation."""
    if not REPOSITORY.fullmatch(repository) or type(issue) is not int or issue < 1:
        fail("INVALID_TARGET")
    data = json.dumps({"body": body}, ensure_ascii=False)
    try:
        runner = subprocess.run if run_func is None else run_func
        response = runner(
            ["gh", "api", "-X", "POST", "-H",
             "Accept: application/vnd.github+json",
             f"/repos/{repository}/issues/{issue}/comments", "--input", "-"],
            input=data, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidMessage("POST_AMBIGUOUS_READ_BEFORE_RETRY") from exc
    if response.returncode != 0:
        fail("POST_UNKNOWN_READ_BEFORE_RETRY")
    if len(response.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
        fail("POST_UNKNOWN_READ_BEFORE_RETRY")
    try:
        info = json.loads(response.stdout)
    except (ValueError, TypeError) as exc:
        raise InvalidMessage("POST_UNKNOWN_READ_BEFORE_RETRY") from exc
    if type(info) is not dict or type(info.get("id")) is not int or info["id"] < 1:
        fail("POST_UNKNOWN_READ_BEFORE_RETRY")
    return info["id"]


def post_and_verify(
    *, repository: str, issue: int, message: dict[str, Any],
    post_func, fetch_func, expected_post_actor: str,
) -> int:
    """POST once and confirm exact message, actor, and mailbox readback."""
    if type(expected_post_actor) is not str or not ACTOR.fullmatch(expected_post_actor):
        fail("INVALID_POST_ACTOR")
    posted_id = post_func(repository=repository, issue=issue,
                          body=encode_comment(message))
    after = fetch_func(repository, issue)
    comments, observed = mailbox(after, repository=repository, issue=issue)
    exact = [(cid, msg) for cid, msg in observed if cid == posted_id and
             msg["message_id"] == message["message_id"] and
             fingerprint(msg) == fingerprint(message)]
    if len(exact) != 1:
        fail("READBACK_UNCONFIRMED_READ_BEFORE_RETRY")
    actors = {comment["id"]: comment for comment in comments}
    if not matching_actor(actors[posted_id], expected_post_actor):
        fail("READBACK_ACTOR_MISMATCH")
    return posted_id


