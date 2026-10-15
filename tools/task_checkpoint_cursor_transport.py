"""Bounded GitHub Issue-comment transport for Task Checkpoint Cursor.

The caller supplies an authenticated GitHub API adapter. This module is not an
authorization grant, scheduler or atomic transaction. Only state already
justified by owning durable evidence may be passed as a proposed write.
"""
from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from tools.task_checkpoint_cursor import (
    SENTINEL, CursorResult, CursorState, compare_cursor,
    inspect_cursor_comments, render_cursor_comment,
    verify_initialization, verify_post_write,
)


class IssueCommentTransport(Protocol):
    def list_comments(self, task: str) -> Sequence[Mapping[str, object]]: ...
    def create_comment(self, task: str, body: str) -> object: ...
    def update_comment(self, task: str, comment_id: int, body: str) -> object: ...


def _trusted_cursor_id(comments: Sequence[Mapping[str, object]]) -> int | None:
    """Locate same canonical marker without interpreting body as authorization."""
    matches: list[int] = []
    for comment in comments:
        body = comment.get("body")
        if not isinstance(body, str):
            continue
        if body.replace("\r\n", "\n").replace("\r", "\n").lstrip().split("\n", 1)[0] != SENTINEL:
            continue
        # This historical trust rule mirrors the v1 reader. Caller must
        # independently authenticate its write token and repository scope.
        association = comment.get("author_association")
        login = (comment.get("user") or {}).get("login") if isinstance(comment.get("user"), Mapping) else None
        if association in ("OWNER", "MEMBER", "COLLABORATOR") or login == "github-actions[bot]":
            cid = comment.get("id")
            if not isinstance(cid, int) or cid <= 0:
                raise ValueError("trusted cursor comment missing GitHub ID")
            matches.append(cid)
    if len(matches) > 1:
        raise ValueError("duplicate trusted cursor comments")
    return matches[0] if matches else None


def apply_cursor_write(
    transport: IssueCommentTransport,
    *,
    task: str,
    proposed: CursorState,
    expected_revision: int | None,
    expected_first_unfinished: str | None,
    reconcile_reason: str | None = None,
) -> CursorResult:
    """One checked initialize/forward advance or *explicit* evidenced reconcile.

    Missing marker -> revision-one initialization. Existing marker -> exact
    expected position/revision match, revision +1. Normal advance must move
    first_unfinished and set last_completed to previously unfinished checkpoint.
    Reconcile is never implicit: caller records reason and verified evidence
    on the owning task first.
    """
    if proposed.task != task:
        raise ValueError("proposed task must equal owning task")
    body = render_cursor_comment(proposed)
    comments = list(transport.list_comments(task))
    inspected = inspect_cursor_comments(comments, task)
    # Do not automatically create or update authoritative state in the
    # presence of an untrusted competing marker. The trusted reader may
    # still expose the canonical marker for read-only recovery, but an
    # effectful caller must explicitly reconcile the suspicious signal.
    if "WARN_UNTRUSTED_MARKER" in inspected.warnings:
        return CursorResult(
            code="WARN_UNTRUSTED_MARKER", live=inspected.live,
            warnings=inspected.warnings,
        )
    if inspected.code == "NO_MARKER":
        if expected_revision is not None or proposed.revision != 1 or reconcile_reason:
            return CursorResult(code="WARN_REVISION_DRIFT")
        transport.create_comment(task, body)
        readback = inspect_cursor_comments(list(transport.list_comments(task)), task)
        if readback.code != "OK_CURSOR" or readback.cursor is None:
            return CursorResult(code="WARN_POST_WRITE_DRIFT", warnings=readback.warnings + (readback.code,))
        return verify_initialization(proposed, readback.cursor)
    if inspected.code != "OK_CURSOR" or inspected.cursor is None:
        return inspected
    live = inspected.cursor
    if expected_revision is None:
        return CursorResult(code="WARN_REVISION_DRIFT", live=live)
    comparison = compare_cursor(live, expected_revision, expected_first_unfinished)
    if comparison.code != "OK_MATCH":
        return comparison
    if proposed.revision != live.revision + 1:
        raise ValueError("proposed revision must advance once")
    if not reconcile_reason:
        if live.first_unfinished is None or proposed.last_completed != live.first_unfinished:
            raise ValueError("normal advance requires current unfinished checkpoint")
        if proposed.first_unfinished == live.first_unfinished:
            raise ValueError("normal advance cannot be a no-op")
    elif not reconcile_reason.strip() or not proposed.evidence:
        raise ValueError("explicit reconciliation requires a reason and durable evidence")
    marker_id = _trusted_cursor_id(comments)
    if marker_id is None:
        return CursorResult(code="WARN_MALFORMED_MARKER", live=live)
    transport.update_comment(task, marker_id, body)
    readback = inspect_cursor_comments(list(transport.list_comments(task)), task)
    if readback.code != "OK_CURSOR" or readback.cursor is None:
        return CursorResult(code="WARN_POST_WRITE_DRIFT", live=live, warnings=readback.warnings + (readback.code,))
    return verify_post_write(proposed, readback.cursor)
