"""Read-only KAEP v0.2 GitHub Issue inbox inspection.

Only accepts GitHub REST comments as fetched by the existing authenticated gh CLI,
or a complete offline test fixture. Does not post messages, call an agent, claim
work, inspect credentials, change permissions or launch Actions.

A GitHub actor login is transport metadata and NOT Claude/ChatGPT proof.
All payload text is untrusted and deliberately hidden from default output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from tools.kaep_mailbox_codec import (
    InvalidMessage,
    MARKER,
    read_mailbox,
    isolate_cross_exchange_replies,
)

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_COMMENT_PAGES = 100
PAGE_SIZE = 100
RECIPIENTS = {"claude-code", "chatgpt", "codex", "coordinator"}
REPOSITORY = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+\Z")


def _fail(reason: str) -> None:
    raise InvalidMessage(reason)


def _no_duplicate_json_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in items:
        if key in output:
            _fail("DUPLICATE_GITHUB_FIELD")
        output[key] = value
    return output


def parse_pages(text: str, *, repository: str, issue: int) -> list[dict[str, Any]]:
    """Flatten a complete gh api --paginate --slurp result (pages-of-comments).

    Fail closed on malformed, oversize, unordered or duplicate pages. Caller
    must still require gh exit code zero to establish transport completion.
    """
    if type(text) is not str or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        _fail("MAILBOX_TOO_LARGE")
    if not REPOSITORY.fullmatch(repository) or type(issue) is not int or issue < 1:
        _fail("INVALID_TARGET")
    try:
        pages = json.loads(text, object_pairs_hook=_no_duplicate_json_keys)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise InvalidMessage("INVALID_GITHUB_JSON") from exc
    if type(pages) is not list or len(pages) > MAX_COMMENT_PAGES:
        _fail("INVALID_PAGES")
    if not pages:
        _fail("MISSING_PAGES")
    output: list[dict[str, Any]] = []
    prev = 0
    for n, page in enumerate(pages):
        if type(page) is not list or len(page) > PAGE_SIZE:
            _fail("INVALID_PAGE")
        # All nonterminal pages of GitHub's per_page=100 paginated response are full.
        if n < len(pages) - 1 and len(page) != PAGE_SIZE:
            _fail("INCOMPLETE_PAGE")
        if not page and n < len(pages) - 1:
            _fail("INCOMPLETE_PAGE")
        for comment in page:
            if type(comment) is not dict:
                _fail("INVALID_COMMENT")
            cid = comment.get("id")
            body = comment.get("body")
            user = comment.get("user")
            if type(cid) is not int or cid <= prev or type(body) is not str:
                _fail("INVALID_COMMENT_SEQUENCE")
            if type(user) is not dict or not isinstance(user.get("login"), str) or not user["login"]:
                _fail("MISSING_GITHUB_ACTOR")
            if not body.startswith(MARKER):
                # Ordinary discussion is not agent instruction and is not emitted.
                pass
            prev = cid
            output.append({
                "id": cid,
                "body": body,
                "actor_login": user["login"],
                "actor_id": user.get("id"),
            })
    return output


def inspect_pages(
    text: str, *, repository: str, issue: int, recipient: str,
    after_id: int = 0, include_text: bool = False,
) -> dict[str, Any]:
    if recipient not in RECIPIENTS or type(after_id) is not int or after_id < 0:
        _fail("INVALID_FILTER")
    comments = parse_pages(text, repository=repository, issue=issue)
    task_ref = f"{repository}#{issue}"
    # Validate whole mailbox before filtering so conflicts before the cursor
    # cannot be hidden by a partial read.
    full = read_mailbox(comments, task_ref=task_ref)
    valid, quarantined = isolate_cross_exchange_replies(
        [msg for _, msg in full]
    )
    accepted_ids = {msg["message_id"] for msg in valid}
    accepted = [
        (cid, msg) for cid, msg in full
        if cid > after_id and msg["recipient"] == recipient
        and msg["message_id"] in accepted_ids
    ]
    actors = {c["id"]: c["actor_login"] for c in comments}
    messages: list[dict[str, Any]] = []
    for cid, msg in accepted:
        item = {
            "comment_id": cid,
            "github_actor_login": actors[cid],
            "provider_identity_verified": False,
            "exchange_id": msg["exchange_id"],
            "message_id": msg["message_id"],
            "in_reply_to": msg["in_reply_to"],
            "kind": msg["kind"],
            "intent": msg["intent"],
            "effect_intent": msg["scope"]["effect"],
        }
        if include_text:
            item["untrusted_payload_text"] = msg["payload"]["text"]
        messages.append(item)
    return {
        "task_ref": task_ref,
        "recipient": recipient,
        "after_id": after_id,
        "observed_latest_comment_id": comments[-1]["id"] if comments else 0,
        "messages": messages,
        "quarantined_exchanges": [
            {"exchange_id": exchange_id, "reason": "CROSS_EXCHANGE_REPLY"}
            for exchange_id in quarantined
        ],
        "read_only": True,
        "claim_or_agent_execution_proven": False,
        "complete_paginated_read_required": True,
    }


def fetch_gh_pages(repository: str, issue: int) -> str:
    if not REPOSITORY.fullmatch(repository) or type(issue) is not int or issue < 1:
        _fail("INVALID_TARGET")
    api_path = f"/repos/{repository}/issues/{issue}/comments?per_page={PAGE_SIZE}"
    try:
        response = subprocess.run(
            ["gh", "api", "--paginate", "--slurp",
             "-H", "Accept: application/vnd.github+json", api_path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidMessage("GITHUB_READ_UNAVAILABLE") from exc
    # Never include gh stderr: it may contain sensitive provider context.
    if response.returncode != 0:
        _fail("GITHUB_READ_FAILED")
    if len(response.stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
        _fail("MAILBOX_TOO_LARGE")
    return response.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--recipient", choices=sorted(RECIPIENTS), required=True)
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--offline-pages", type=Path)
    parser.add_argument("--include-text", action="store_true",
                        help="Explicitly include untrusted payload; not authority")
    args = parser.parse_args(argv)
    try:
        if args.offline_pages:
            text = args.offline_pages.read_text(encoding="utf-8")
        else:
            text = fetch_gh_pages(args.repository, args.issue)
        result = inspect_pages(
            text, repository=args.repository, issue=args.issue,
            recipient=args.recipient, after_id=args.after_id,
            include_text=args.include_text,
        )
    except (InvalidMessage, OSError, UnicodeError) as exc:
        code = str(exc) if isinstance(exc, InvalidMessage) else "OFFLINE_READ_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason_code": code}))
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
