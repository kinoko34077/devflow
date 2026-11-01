"""Read-only, bounded KAEP v0.2 discovery index with source revalidation.

A malformed/untrusted *index comment* is quarantined, not promoted to task
authority and not allowed to starve following messages. Incomplete GitHub
pagination and unavailable or inconsistent owning-Issue mailboxes still fail
closed; this does not loosen the shared KAEP codec or Claim protections.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import json
import re
import sys
from typing import Callable, Any

from tools.kaep_inbox_reader import InvalidMessage, fetch_gh_pages, parse_pages
from tools.kaep_mailbox_codec import (
    MARKER, decode_comment, fingerprint, reject_constant, unique_pairs,
    matches,
)
from tools.kaep_reply_sender import ACTOR, _mailbox, _matching_actor
from tools.kaep_route_notice import (
    DISCOVERY_REPOSITORY, DISCOVERY_ISSUE, POINTER_VERSION,
    _verify_source_request_from_snapshot, SourceMailbox,
)

SOURCE_URL = re.compile(
    r"https://github\.com/(kinoko34077/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)\Z")
POINTER_FIELDS = {"type", "owning_issue", "message_id", "comment_id"}
MAX_INDEX_BATCH = 20
REPLY_KINDS = {"ACK", "ANSWER", "BLOCKED"}


def _fail(code: str) -> None:
    raise InvalidMessage(code)


def parse_pointer(text: str) -> dict[str, Any] | None:
    """Recognize only a structured object with the exact pointer type.

    Ordinary prose mentioning the pointer protocol is not a pointer, and may
    coexist with real discovery messages.
    """
    try:
        obj = json.loads(text, object_pairs_hook=unique_pairs,
                         parse_constant=reject_constant)
    except InvalidMessage:
        raise
    except (ValueError, RecursionError, TypeError) as exc:
        # Malformed JSON that attempts to be a typed pointer is rejected.
        # Ordinary prose, including an incidental version mention, is ignored.
        stripped = text.lstrip()
        if stripped.startswith("{") and '"type"' in stripped and POINTER_VERSION in stripped:
            raise InvalidMessage("INVALID_DISCOVERY_POINTER") from exc
        return None
    if type(obj) is not dict or obj.get("type") != POINTER_VERSION:
        return None
    if set(obj) != POINTER_FIELDS or type(obj["owning_issue"]) is not str:
        _fail("INVALID_DISCOVERY_POINTER")
    target = SOURCE_URL.fullmatch(obj["owning_issue"])
    if target is None or not matches(r"msg_[A-Za-z0-9_-]{1,72}", obj["message_id"]):
        _fail("INVALID_DISCOVERY_POINTER")
    if type(obj["comment_id"]) is not int or obj["comment_id"] < 1:
        _fail("INVALID_DISCOVERY_POINTER")
    if target.group(1) == DISCOVERY_REPOSITORY and int(target.group(2)) == DISCOVERY_ISSUE:
        _fail("DISCOVERY_LOOP")
    return obj


def _source_context(
    snapshot: SourceMailbox,
    *, message_id: str, expected_actor: str,
) -> dict[str, Any]:
    """Observe original scope/replies from the same validated source snapshot."""
    comments, items = snapshot
    matches_found = [(cid, msg) for cid, msg in items if msg["message_id"] == message_id]
    if len(matches_found) != 1:
        _fail("SOURCE_MESSAGE_NOT_UNIQUE")
    _, root = matches_found[0]
    actors = {comment["id"]: comment for comment in comments}
    replies = sorted({
        msg["kind"] for cid, msg in items
        if msg["in_reply_to"] == message_id
        and msg["exchange_id"] == root["exchange_id"]
        and msg["recipient"] == "chatgpt"
        and msg["intent"] == root["intent"]
        and msg["scope"] == root["scope"]
        and msg["kind"] in REPLY_KINDS
        and _matching_actor(actors[cid], expected_actor)
    })
    return {"expected_head": root["scope"]["expected_head"],
            "observed_reply_kinds": replies}


def _verify_pointer_source(
    pointer: dict[str, Any], *, repository: str, issue: int,
    fetch_source: Callable[[str, int], str], expected_actor: str,
    source_mailboxes: dict[tuple[str, int], SourceMailbox],
    source_proofs: dict[
        tuple[str, int, str], tuple[dict[str, Any], dict[str, Any]]
    ],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Revalidate original-source evidence, caching only verified scan-local proof.

    The full source mailbox is strictly decoded once within this scan. A cache
    hit never permits altered pointer content, including a forged comment ID.
    """
    key = (repository, issue)
    if key not in source_mailboxes:
        source_mailboxes[key] = _mailbox(
            fetch_source(repository, issue), repository=repository, issue=issue,
        )
    snapshot = source_mailboxes[key]
    proof_key = (repository, issue, pointer["message_id"])
    if proof_key not in source_proofs:
        verified = _verify_source_request_from_snapshot(
            snapshot, repository=repository, issue=issue,
            message_id=pointer["message_id"], expected_actor=expected_actor)
        # Preserve original failure ordering: source mismatch precedes context.
        if verified != pointer:
            _fail("DISCOVERY_SOURCE_MISMATCH")
        context = _source_context(
            snapshot, message_id=pointer["message_id"],
            expected_actor=expected_actor)
        source_proofs[proof_key] = (verified, context)
    verified, context = source_proofs[proof_key]
    if verified != pointer:
        _fail("DISCOVERY_SOURCE_MISMATCH")
    return verified, context


def _discover_batch(
    index_pages: str, *, expected_notice_actor: str,
    expected_source_actor: str, fetch_source: Callable[[str, int], str],
    after_id: int = 0, index_issue: int = DISCOVERY_ISSUE,
    additional_forbidden_issue: int | None = None,
    source_mailboxes: dict[tuple[str, int], SourceMailbox] | None = None,
    index_comments: list[dict[str, Any]] | None = None,
    replay_history: tuple[dict[str, str], dict[str, str]] | None = None,
    source_proofs: dict[
        tuple[str, int, str], tuple[dict[str, Any], dict[str, Any]]
    ] | None = None,
) -> dict[str, Any]:
    if (type(index_issue) is not int or index_issue <= 0
            or additional_forbidden_issue is not None
            and (type(additional_forbidden_issue) is not int
                 or additional_forbidden_issue <= 0)):
        _fail("INVALID_DISCOVERY_INDEX")
    if type(after_id) is not int or after_id < 0:
        _fail("INVALID_CURSOR")
    if (type(expected_notice_actor) is not str or not ACTOR.fullmatch(expected_notice_actor)
            or type(expected_source_actor) is not str or not ACTOR.fullmatch(expected_source_actor)):
        _fail("INVALID_ACTOR")
    # Provider pagination/order/user metadata remains globally verified. Only
    # individual untrusted Issue comment content gets per-item isolation.
    # The public entry validates complete GitHub pages here. Shadow scans
    # pass the same already-validated immutable-by-convention snapshot through
    # successive batches instead of decoding the whole JSON input repeatedly.
    comments = (parse_pages(index_pages, repository=DISCOVERY_REPOSITORY,
                            issue=index_issue)
                if index_comments is None else index_comments)
    # parse_pages guarantees ascending IDs. Binary cursor lookup avoids
    # copying/rechecking every prior index comment on each bounded batch.
    start = bisect_right(comments, after_id, key=lambda item: item["id"])
    subset = comments[start:start + MAX_INDEX_BATCH]
    result: dict[str, Any] = {
        "status": "READ_ONLY",
        "hints": [],
        "rejected": [],
        "blocked": [],
        "truncated": start + len(subset) < len(comments),
        # Commit cursor stops at the first failed source; scan cursor is only
        # for traversing subsequent batches in this active check-in.
        "next_after_id": subset[-1]["id"] if subset else after_id,
        "next_scan_after_id": subset[-1]["id"] if subset else after_id,
        "read_only": True,
        "peer_identity_verified": False,
    }
    source_cache: dict[tuple[str, int], SourceMailbox] = (
        {} if source_mailboxes is None else source_mailboxes
    )
    # Proofs are valid only for the exact immutable source snapshot and fixed
    # expected actor of this call. Never carry them into a later live read.
    proof_cache: dict[
        tuple[str, int, str], tuple[dict[str, Any], dict[str, Any]]
    ] = {} if source_proofs is None else source_proofs
    seen_msg: dict[str, str] = {}
    seen_keys: dict[str, str] = {}
    for position, comment in enumerate(subset):
        source_validation = False
        cid = comment["id"]
        body = comment["body"]
        if not body.startswith(MARKER):
            continue
        if not _matching_actor(comment, expected_notice_actor):
            result["rejected"].append({"index_comment_id": cid,
                                       "reason_code": "UNTRUSTED_DISCOVERY_ACTOR"})
            continue
        try:
            msg = decode_comment(body, task_ref=f"{DISCOVERY_REPOSITORY}#{index_issue}")
            identity = fingerprint(msg)
            old_msg = seen_msg.get(msg["message_id"])
            old_key = seen_keys.get(msg["idempotency_key"])
            if replay_history is not None:
                # The shadow's multi-batch scan must detect conflicting index
                # identities from *earlier* batches as well as this batch.
                # Identical cross-batch replays still reach source-root
                # accounting, preserving duplicate_verified_pointers.
                earlier_messages, earlier_keys = replay_history
                previous_message = earlier_messages.get(msg["message_id"])
                previous_key = earlier_keys.get(msg["idempotency_key"])
                if (previous_message is not None and previous_message != identity
                        or previous_key is not None and previous_key != identity):
                    _fail("CONFLICTING_INDEX_REPLAY")
            if (old_msg is not None and old_msg != identity
                    or old_key is not None and old_key != identity):
                _fail("CONFLICTING_INDEX_REPLAY")
            if old_msg == identity or old_key == identity:
                # Identical repeated stored comments are transport replays,
                # not two separately actionable task hints.
                continue
            seen_msg[msg["message_id"]] = identity
            seen_keys[msg["idempotency_key"]] = identity
            if replay_history is not None:
                earlier_messages[msg["message_id"]] = identity
                earlier_keys[msg["idempotency_key"]] = identity
            if (msg["recipient"] != "claude-code" or msg["kind"] != "REQUEST"
                    or msg["intent"] != "REPORT" or msg["in_reply_to"] is not None
                    or msg["scope"]["effect"] != "READ_ONLY"):
                continue
            pointer = parse_pointer(msg["payload"]["text"])
            if pointer is None:
                continue
            match = SOURCE_URL.fullmatch(pointer["owning_issue"])
            assert match is not None
            repo, issue = match.group(1), int(match.group(2))
            # A registered discovery index may not recursively designate itself
            # or a second recognized index as an original task source.
            if (repo == DISCOVERY_REPOSITORY
                    and (issue == index_issue or issue == additional_forbidden_issue)):
                _fail("DISCOVERY_LOOP")
            source_validation = True
            verified, context = _verify_pointer_source(
                pointer, repository=repo, issue=issue,
                fetch_source=fetch_source, expected_actor=expected_source_actor,
                source_mailboxes=source_cache, source_proofs=proof_cache,
            )
            result["hints"].append({
                "index_comment_id": cid,
                "owning_issue": pointer["owning_issue"],
                "source_comment_id": verified["comment_id"],
                "source_message_id": verified["message_id"],
                "expected_head": context["expected_head"],
                "observed_reply_kinds": list(context["observed_reply_kinds"]),
                "status": "POINTER_SOURCE_VERIFIED_ONLY",
            })
        except InvalidMessage as exc:
            # Invalid index content/actor cannot starve later entries. Never
            # claim the invalid item is a verified task. Owning-Issue transport
            # corruption or unavailable reads are still globally fatal.
            if source_validation and str(exc) not in {
                "SOURCE_MESSAGE_NOT_UNIQUE", "SOURCE_ACTOR_MISMATCH",
                "SOURCE_NOT_SUPPORTED_REQUEST", "DISCOVERY_SOURCE_MISMATCH",
            }:
                # Preserve source fail-closed: no results from this pointer.
                # Other independent sources can still be checked in this run,
                # but a durable cursor may NEVER skip the first blocked item.
                if not result["blocked"]:
                    result["next_after_id"] = (
                        subset[position - 1]["id"] if position else after_id)
                result["blocked"].append({
                    "index_comment_id": cid, "reason_code": str(exc)})
                continue
            result["rejected"].append({
                "index_comment_id": cid, "reason_code": str(exc)})
    if result["blocked"]:
        result["status"] = "PARTIAL_BLOCKED"
    return result


def discover_batch(
    index_pages: str, *, expected_notice_actor: str,
    expected_source_actor: str, fetch_source: Callable[[str, int], str],
    after_id: int = 0, index_issue: int = DISCOVERY_ISSUE,
    additional_forbidden_issue: int | None = None,
) -> dict[str, Any]:
    """Public entry never accepts a prevalidated cache from its caller."""
    return _discover_batch(
        index_pages, expected_notice_actor=expected_notice_actor,
        expected_source_actor=expected_source_actor, fetch_source=fetch_source,
        after_id=after_id, index_issue=index_issue,
        additional_forbidden_issue=additional_forbidden_issue,
    )


MAX_SHADOW_BATCHES = 10


def discover_index_shadow(
    index_pages: str, *, expected_notice_actor: str,
    expected_source_actor: str, fetch_source: Callable[[str, int], str],
    after_id: int = 0, max_batches: int = MAX_SHADOW_BATCHES,
    index_issue: int = DISCOVERY_ISSUE,
    additional_forbidden_issue: int | None = None,
) -> dict[str, Any]:
    """Opt-in bounded #503 index shadow, using the unchanged strict reader.

    Exhausting this *index* does not prove complete original-Issue discovery,
    active requests, peer identity, current HEAD, or M3/Agent Inbox authority.
    """
    if type(max_batches) is not int or not (1 <= max_batches <= MAX_SHADOW_BATCHES):
        _fail("INVALID_SHADOW_LIMIT")
    # Preserve fail-closed provider transport/page validation in discover_batch.
    # Strictly validate the complete provider history once per shadow scan.
    # Repeated _discover_batch calls only traverse its validated comment data.
    # No raw or caller-provided prevalidated snapshot enters this public API.
    index_comments = parse_pages(
        index_pages, repository=DISCOVERY_REPOSITORY, issue=index_issue,
    )
    cursor = after_id
    source_cache: dict[tuple[str, int], SourceMailbox] = {}
    source_proofs: dict[
        tuple[str, int, str], tuple[dict[str, Any], dict[str, Any]]
    ] = {}
    replay_history: tuple[dict[str, str], dict[str, str]] = ({}, {})
    hints: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    seen_roots: set[tuple[str, str, int]] = set()
    duplicate_verified_pointers = 0
    batches = 0

    for _ in range(max_batches):
        batch = _discover_batch(
            index_pages, expected_notice_actor=expected_notice_actor,
            expected_source_actor=expected_source_actor,
            fetch_source=fetch_source, after_id=cursor,
            index_issue=index_issue,
            additional_forbidden_issue=additional_forbidden_issue,
            source_mailboxes=source_cache,
            index_comments=index_comments,
            replay_history=replay_history,
            source_proofs=source_proofs,
        )
        batches += 1
        for hint in batch["hints"]:
            root_key = (hint["owning_issue"], hint["source_message_id"],
                        hint["source_comment_id"])
            if root_key in seen_roots:
                duplicate_verified_pointers += 1
                continue
            seen_roots.add(root_key)
            hints.append(hint)
        rejected.extend(batch["rejected"])
        blocked.extend(batch["blocked"])
        if blocked:
            # Do not advance a durable cursor past an unreadable original.
            cursor = batch["next_after_id"]
            status = "PARTIAL_BLOCKED"
            truncated = True
            break
        cursor = batch["next_after_id"]
        if not batch["truncated"]:
            status = "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY"
            truncated = False
            break
    else:
        status = "BOUNDED_TRUNCATED"
        truncated = True

    if rejected and status == "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY":
        status = "INDEX_EXHAUSTED_WITH_REJECTIONS"
    return {
        "status": status, "hints": hints, "rejected": rejected,
        "blocked": blocked, "next_after_id": cursor,
        "truncated": truncated, "scanned_batches": batches,
        "distinct_source_issue_count": len(source_cache),
        "duplicate_verified_pointers": duplicate_verified_pointers,
        "read_only": True, "peer_identity_verified": False,
        "complete_work_inventory": False, "fallback_retirement_authorized": False,
    }


def discover_dual_index_shadow(
    legacy_pages: str, successor_pages: str, *,
    successor_issue: int, expected_notice_actor: str,
    expected_source_actor: str, fetch_source: Callable[[str, int], str],
    max_batches: int = MAX_SHADOW_BATCHES,
) -> dict[str, Any]:
    """Offline/read-only successor compatibility experiment, NOT an index cutover.

    Both candidate indexes use the existing strict original verifier. An
    invalid source or index never becomes trusted work; each index retains
    its own cursor/status. No successor Issue is fetched/created here.
    """
    if (type(successor_issue) is not int or successor_issue <= 0
            or successor_issue == DISCOVERY_ISSUE):
        _fail("INVALID_SUCCESSOR_INDEX")
    source_cache: dict[tuple[str, int], str] = {}

    def cached_source(repository: str, issue: int) -> str:
        key = (repository, issue)
        if key not in source_cache:
            source_cache[key] = fetch_source(repository, issue)
        return source_cache[key]

    old = discover_index_shadow(
        legacy_pages, expected_notice_actor=expected_notice_actor,
        expected_source_actor=expected_source_actor, fetch_source=cached_source,
        max_batches=max_batches, index_issue=DISCOVERY_ISSUE,
        additional_forbidden_issue=successor_issue,
    )
    new = discover_index_shadow(
        successor_pages, expected_notice_actor=expected_notice_actor,
        expected_source_actor=expected_source_actor, fetch_source=cached_source,
        max_batches=max_batches, index_issue=successor_issue,
        additional_forbidden_issue=DISCOVERY_ISSUE,
    )
    by_root: dict[tuple[str, str, int], dict[str, Any]] = {}
    by_message: dict[tuple[str, str], tuple[str, str, int]] = {}
    by_comment: dict[tuple[str, int], tuple[str, str, int]] = {}
    conflict_roots: set[tuple[str, str, int]] = set()
    duplicate_count = 0
    for origin, snapshot in (("legacy", old), ("successor", new)):
        for hint in snapshot["hints"]:
            key = (hint["owning_issue"], hint["source_message_id"],
                   hint["source_comment_id"])
            message_key = key[:2]
            comment_key = (key[0], key[2])
            other = by_message.get(message_key) or by_comment.get(comment_key)
            if other is not None and other != key:
                conflict_roots.update((other, key))
                continue
            by_message[message_key] = key
            by_comment[comment_key] = key
            if key not in by_root:
                by_root[key] = {
                    "owning_issue": key[0],
                    "source_message_id": key[1],
                    "source_comment_id": key[2],
                    "expected_head": hint["expected_head"],
                    "observed_reply_kinds": hint["observed_reply_kinds"],
                    "index_origins": [origin],
                    "index_comment_ids": {origin: hint["index_comment_id"]},
                    "status": "POINTER_SOURCE_VERIFIED_ONLY",
                }
            else:
                current = by_root[key]
                if (current["expected_head"] != hint["expected_head"]
                        or current["observed_reply_kinds"] != hint["observed_reply_kinds"]):
                    conflict_roots.add(key)
                    continue
                duplicate_count += 1
                current["index_origins"].append(origin)
                current["index_comment_ids"][origin] = hint["index_comment_id"]
    accepted = [v for k, v in sorted(by_root.items()) if k not in conflict_roots]
    partial = bool(
        conflict_roots
        or old["status"] != "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY"
        or new["status"] != "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY"
    )
    return {
        "schema_version": "kaep.dual-index-shadow.v0.1",
        "status": "PARTIAL_UNKNOWN" if partial else "BOUNDED_DUAL_INDEX_READ",
        "index_status": {
            "legacy": old["status"], "successor": new["status"],
        },
        "index_issue_numbers": {
            "legacy": DISCOVERY_ISSUE, "successor": successor_issue,
        },
        "index_diagnostics": {
            origin: {
                "rejected": report["rejected"], "blocked": report["blocked"],
                "truncated": report["truncated"],
                "next_after_id": report["next_after_id"],
            }
            for origin, report in (("legacy", old), ("successor", new))
        },
        "source_verified_roots": accepted,
        "cross_index_duplicate_count": duplicate_count,
        "cross_index_identity_conflicts": len(conflict_roots),
        "distinct_source_issue_count": len(source_cache),
        "read_only": True,
        "has_unknown_work": True,
        "complete_source_universe": False,
        "complete_work_inventory": False,
        "recipient_pickup_proven": False,
        "current_head_verified": False,
        "can_authorize_execution": False,
        "fallback_retirement_authorized": False,
        "index_migration_approved": False,
    }


def discover(
    index_pages: str, *, expected_notice_actor: str,
    expected_source_actor: str, fetch_source: Callable[[str, int], str],
    after_id: int = 0,
) -> list[dict[str, Any]]:
    """Backward-compatible list projection; use discover_batch for cursor."""
    batch = discover_batch(
        index_pages, expected_notice_actor=expected_notice_actor,
        expected_source_actor=expected_source_actor,
        fetch_source=fetch_source, after_id=after_id)
    # Legacy consumers cannot receive blocked/cursor metadata. Preserve their
    # previous strict failure semantics instead of silently accepting partial.
    if batch["blocked"]:
        _fail("DISCOVERY_SOURCE_BLOCKED")
    return batch["hints"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--shadow-all", action="store_true",
                        help="GET-only bounded selected-index shadow; never promotes authority")
    parser.add_argument("--index-issue", type=int, default=DISCOVERY_ISSUE,
                        help="Read only approved #503 legacy or #789 successor")
    parser.add_argument("--dual-shadow", action="store_true",
                        help="GET-only #503 + approved #789 original-verifying bounded union")
    parser.add_argument("--expect-notice-actor", required=True)
    parser.add_argument("--expect-source-actor", required=True)
    args = parser.parse_args(argv)
    try:
        # Public Issue #789 is approved for successor READ. This is NOT
        # authority to write any new KAEP requests, mark work complete, or
        # retire legacy #503. Other caller-provided Issue IDs are rejected.
        if args.index_issue not in (DISCOVERY_ISSUE, 789) or type(args.index_issue) is not int:
            _fail("DISCOVERY_INDEX_NOT_APPROVED")
        if args.dual_shadow:
            if args.index_issue != DISCOVERY_ISSUE or args.after_id != 0 or args.shadow_all:
                _fail("INVALID_DUAL_INDEX_ARGUMENTS")
            legacy_pages = fetch_gh_pages(DISCOVERY_REPOSITORY, DISCOVERY_ISSUE)
            successor_pages = fetch_gh_pages(DISCOVERY_REPOSITORY, 789)
            result = discover_dual_index_shadow(
                legacy_pages, successor_pages, successor_issue=789,
                expected_notice_actor=args.expect_notice_actor,
                expected_source_actor=args.expect_source_actor,
                fetch_source=fetch_gh_pages,
            )
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0 if result["status"] == "BOUNDED_DUAL_INDEX_READ" else 2
        index_pages = fetch_gh_pages(DISCOVERY_REPOSITORY, args.index_issue)
        if args.shadow_all:
            result = discover_index_shadow(
                index_pages, expected_notice_actor=args.expect_notice_actor,
                expected_source_actor=args.expect_source_actor,
                fetch_source=fetch_gh_pages, after_id=args.after_id,
                index_issue=args.index_issue,
                additional_forbidden_issue=(789 if args.index_issue == DISCOVERY_ISSUE else DISCOVERY_ISSUE))
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0 if result["status"] == "INDEX_EXHAUSTED_SOURCE_VERIFIED_ONLY" else 2
        result = discover_batch(
            index_pages, expected_notice_actor=args.expect_notice_actor,
            expected_source_actor=args.expect_source_actor,
            fetch_source=fetch_gh_pages, after_id=args.after_id,
            index_issue=args.index_issue,
            additional_forbidden_issue=(789 if args.index_issue == DISCOVERY_ISSUE else DISCOVERY_ISSUE))
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (InvalidMessage, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, InvalidMessage) else "DISCOVERY_IO_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason_code": reason}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
