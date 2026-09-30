"""Pure Task Checkpoint Cursor v1 parsing and transition helpers.

This module deliberately performs no GitHub network writes.  It models the
canonical cursor comment, trust inspection, drift comparison, forward advance
preparation, post-write verification and explicit reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Mapping, Sequence


SENTINEL = "<!-- devflow-task-checkpoint-cursor:v1 -->"

_TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_ALLOWED_KEYS = (
    "schema_version",
    "task",
    "revision",
    "last_completed",
    "first_unfinished",
    "head",
    "evidence",
    "updated_at",
)
_TASK_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*$")
_CHECKPOINT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_YAML_BLOCK_RE = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


class CursorFormatError(ValueError):
    """Raised when a recognized cursor comment violates the v1 contract."""


@dataclass(frozen=True)
class CursorState:
    schema_version: int
    task: str
    revision: int
    last_completed: str | None
    first_unfinished: str | None
    head: str | None
    evidence: tuple[str, ...]
    updated_at: str

    def __post_init__(self) -> None:
        _validate_state(self)


@dataclass(frozen=True)
class CursorResult:
    code: str
    cursor: CursorState | None = None
    live: CursorState | None = None
    warnings: tuple[str, ...] = ()


def _validate_checkpoint(value: str | None, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _CHECKPOINT_RE.fullmatch(value):
        raise CursorFormatError(f"invalid {field}")


def _validate_timestamp(value: str) -> None:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise CursorFormatError("invalid updated_at")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CursorFormatError("invalid updated_at") from exc


def _validate_state(cursor: CursorState) -> None:
    if cursor.schema_version != 1:
        raise CursorFormatError("unsupported schema_version")
    if not isinstance(cursor.task, str) or not _TASK_RE.fullmatch(cursor.task):
        raise CursorFormatError("invalid task")
    if not isinstance(cursor.revision, int) or isinstance(cursor.revision, bool) or cursor.revision < 1:
        raise CursorFormatError("invalid revision")
    _validate_checkpoint(cursor.last_completed, "last_completed")
    _validate_checkpoint(cursor.first_unfinished, "first_unfinished")
    if cursor.head is not None and (
        not isinstance(cursor.head, str) or not _HEAD_RE.fullmatch(cursor.head)
    ):
        raise CursorFormatError("invalid head")
    if not isinstance(cursor.evidence, tuple):
        raise CursorFormatError("evidence must be a tuple")
    for item in cursor.evidence:
        if not isinstance(item, str) or not item or item.strip() != item or "\n" in item or "\r" in item:
            raise CursorFormatError("invalid evidence item")
    _validate_timestamp(cursor.updated_at)


def _parse_nullable_checkpoint(raw: str, field: str) -> str | None:
    if raw == "null":
        return None
    _validate_checkpoint(raw, field)
    return raw


def _parse_nullable_head(raw: str) -> str | None:
    if raw == "null":
        return None
    if not _HEAD_RE.fullmatch(raw):
        raise CursorFormatError("invalid head")
    return raw


def parse_cursor_comment(body: str) -> CursorState:
    """Parse one canonical cursor comment body.

    The parser intentionally accepts only the v1 canonical YAML subset rather
    than a general YAML language.  This keeps the helper dependency-free and
    rejects ambiguous duplicate/unknown keys.
    """

    if not isinstance(body, str) or body.count(SENTINEL) != 1:
        raise CursorFormatError("cursor sentinel missing or duplicated")

    marker_index = body.index(SENTINEL) + len(SENTINEL)
    blocks = _YAML_BLOCK_RE.findall(body[marker_index:])
    if len(blocks) != 1:
        raise CursorFormatError("expected exactly one yaml block")

    values: dict[str, object] = {}
    current_list: str | None = None

    for raw_line in blocks[0].splitlines():
        if not raw_line.strip():
            continue

        if raw_line.startswith("  - "):
            if current_list != "evidence":
                raise CursorFormatError("unexpected list item")
            item = raw_line[4:]
            if not item or item.strip() != item:
                raise CursorFormatError("invalid evidence item")
            evidence = values["evidence"]
            assert isinstance(evidence, list)
            evidence.append(item)
            continue

        if raw_line.startswith(" "):
            raise CursorFormatError("invalid indentation")
        if ":" not in raw_line:
            raise CursorFormatError("invalid yaml field")

        key, raw_value = raw_line.split(":", 1)
        if key not in _ALLOWED_KEYS:
            raise CursorFormatError(f"unknown key: {key}")
        if key in values:
            raise CursorFormatError(f"duplicate key: {key}")

        raw_value = raw_value.lstrip(" ")
        if key == "evidence":
            if raw_value:
                raise CursorFormatError("evidence must be a sequence")
            values[key] = []
            current_list = key
            continue

        current_list = None
        if not raw_value:
            raise CursorFormatError(f"missing value: {key}")
        values[key] = raw_value

    missing = [key for key in _ALLOWED_KEYS if key not in values]
    if missing:
        raise CursorFormatError("missing keys: " + ", ".join(missing))

    try:
        schema_version = int(str(values["schema_version"]))
        revision = int(str(values["revision"]))
    except ValueError as exc:
        raise CursorFormatError("schema_version and revision must be integers") from exc

    evidence_value = values["evidence"]
    if not isinstance(evidence_value, list):
        raise CursorFormatError("evidence must be a sequence")

    return CursorState(
        schema_version=schema_version,
        task=str(values["task"]),
        revision=revision,
        last_completed=_parse_nullable_checkpoint(str(values["last_completed"]), "last_completed"),
        first_unfinished=_parse_nullable_checkpoint(str(values["first_unfinished"]), "first_unfinished"),
        head=_parse_nullable_head(str(values["head"])),
        evidence=tuple(evidence_value),
        updated_at=str(values["updated_at"]),
    )


def render_cursor_comment(cursor: CursorState) -> str:
    """Render the canonical v1 Issue-comment representation."""

    _validate_state(cursor)
    lines = [
        SENTINEL,
        "",
        "# Task Checkpoint Cursor",
        "",
        "```yaml",
        "schema_version: 1",
        f"task: {cursor.task}",
        f"revision: {cursor.revision}",
        f"last_completed: {cursor.last_completed if cursor.last_completed is not None else 'null'}",
        f"first_unfinished: {cursor.first_unfinished if cursor.first_unfinished is not None else 'null'}",
        f"head: {cursor.head if cursor.head is not None else 'null'}",
        "evidence:",
    ]
    lines.extend(f"  - {item}" for item in cursor.evidence)
    lines.extend((f"updated_at: {cursor.updated_at}", "```", ""))
    return "\n".join(lines)


def _comment_login(comment: Mapping[str, object]) -> str | None:
    user = comment.get("user")
    if not isinstance(user, Mapping):
        return None
    login = user.get("login")
    return login if isinstance(login, str) else None


def _is_trusted_comment(comment: Mapping[str, object]) -> bool:
    association = comment.get("author_association")
    if isinstance(association, str) and association in _TRUSTED_ASSOCIATIONS:
        return True
    return _comment_login(comment) == "github-actions[bot]"


def inspect_cursor_comments(
    comments: Sequence[Mapping[str, object]], task: str
) -> CursorResult:
    """Inspect Issue comments and return the unique trusted v1 cursor if any."""

    if not _TASK_RE.fullmatch(task):
        raise ValueError("invalid task identity")

    trusted: list[str] = []
    untrusted_seen = False

    for comment in comments:
        body = comment.get("body")
        if not isinstance(body, str) or SENTINEL not in body:
            continue
        if _is_trusted_comment(comment):
            trusted.append(body)
        else:
            untrusted_seen = True

    warnings = ("WARN_UNTRUSTED_MARKER",) if untrusted_seen else ()

    if not trusted:
        return CursorResult(code="NO_MARKER", warnings=warnings)
    if len(trusted) > 1:
        return CursorResult(code="WARN_DUPLICATE_MARKER", warnings=warnings)

    try:
        cursor = parse_cursor_comment(trusted[0])
    except CursorFormatError:
        return CursorResult(code="WARN_MALFORMED_MARKER", warnings=warnings)

    if cursor.task != task:
        return CursorResult(code="WARN_MALFORMED_MARKER", warnings=warnings)
    return CursorResult(code="OK_CURSOR", cursor=cursor, live=cursor, warnings=warnings)


def compare_cursor(
    live: CursorState, expected_revision: int, expected_first_unfinished: str | None
) -> CursorResult:
    """Compare observed worker expectations with the live cursor.

    Checkpoint drift takes precedence because v1 deliberately does not infer
    ordering from checkpoint spelling.  Revision drift is reported only when
    the checkpoint still matches.
    """

    if live.first_unfinished != expected_first_unfinished:
        return CursorResult(code="WARN_CHECKPOINT_DRIFT", live=live)
    if live.revision != expected_revision:
        return CursorResult(code="WARN_REVISION_DRIFT", live=live)
    return CursorResult(code="OK_MATCH", live=live)


def initialize_cursor(
    *,
    task: str,
    last_completed: str | None,
    first_unfinished: str | None,
    head: str | None,
    evidence: Sequence[str],
    updated_at: str,
) -> CursorState:
    """Create the initial revision after the caller has verified NO_MARKER."""

    return CursorState(
        schema_version=1,
        task=task,
        revision=1,
        last_completed=last_completed,
        first_unfinished=first_unfinished,
        head=head,
        evidence=tuple(evidence),
        updated_at=updated_at,
    )


def verify_initialization(written: CursorState, observed: CursorState) -> CursorResult:
    """Classify immediate initialization readback without claiming atomicity."""

    if written == observed:
        return CursorResult(code="OK_INITIALIZED", cursor=observed, live=observed)
    return CursorResult(code="WARN_POST_WRITE_DRIFT", live=observed)


def advance_cursor(
    live: CursorState,
    *,
    expected_revision: int,
    expected_first_unfinished: str | None,
    completed_checkpoint: str,
    next_first_unfinished: str | None,
    head: str | None,
    evidence: Sequence[str],
    updated_at: str,
) -> CursorResult:
    """Prepare one forward movement only when expected/live state matches."""

    if completed_checkpoint != expected_first_unfinished:
        raise ValueError("completed_checkpoint must equal expected_first_unfinished")
    _validate_checkpoint(completed_checkpoint, "completed_checkpoint")
    _validate_checkpoint(next_first_unfinished, "next_first_unfinished")

    comparison = compare_cursor(live, expected_revision, expected_first_unfinished)
    if comparison.code != "OK_MATCH":
        return comparison

    prepared = CursorState(
        schema_version=1,
        task=live.task,
        revision=live.revision + 1,
        last_completed=completed_checkpoint,
        first_unfinished=next_first_unfinished,
        head=head,
        evidence=tuple(evidence),
        updated_at=updated_at,
    )
    return CursorResult(code="OK_PREPARED", cursor=prepared, live=live)


def verify_post_write(written: CursorState, observed: CursorState) -> CursorResult:
    """Classify immediate post-write readback without claiming atomicity."""

    if written == observed:
        return CursorResult(code="OK_ADVANCED", cursor=observed, live=observed)
    return CursorResult(code="WARN_POST_WRITE_DRIFT", live=observed)


def reconcile_cursor(
    live: CursorState,
    *,
    last_completed: str | None,
    first_unfinished: str | None,
    head: str | None,
    evidence: Sequence[str],
    updated_at: str,
) -> CursorState:
    """Explicitly repair the projection from verified durable evidence."""

    return CursorState(
        schema_version=1,
        task=live.task,
        revision=live.revision + 1,
        last_completed=last_completed,
        first_unfinished=first_unfinished,
        head=head,
        evidence=tuple(evidence),
        updated_at=updated_at,
    )
