"""Read-first, bounded GitHub Issue section transition with stale-plan refusal.

Pure A5 library for #487. It does NOT fetch GitHub state, authenticate callers,
authorize writes, serialize writers, or issue PATCH. A caller must obtain real
GitHub GET observations and a separately authorized native effect method.
Even a fresh read here is NOT an atomic expected-old-body condition on PATCH.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping

_REPO = re.compile(r"kinoko34077/[a-zA-Z0-9_.-]{1,80}\Z")
_UPDATED = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")
_MAX_BODY = 262_144
_MAX_SECTION = 8_192
_MAX_DELTA = 4_096


class MetadataPreflightRejected(ValueError):
    """Fixed denial: no secret/input text exposed in this error."""


@dataclass(frozen=True)
class IssueSnapshot:
    """An observation, not a verified GitHub authentication or lock."""
    repository: str
    number: int
    updated_at: str
    body: str


@dataclass(frozen=True)
class SectionTransition:
    """Pure, immutable proposed effect; not write authority."""
    repository: str
    number: int
    observed_updated_at: str
    observed_body_sha256: str
    after_body_sha256: str
    before_body: str
    after_body: str
    changed_section_before: str
    changed_section_after: str
    effect_authorized: bool = False
    atomic_compare_available: bool = False


def _digest(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _bytes(s: str) -> int:
    return len(s.encode("utf-8"))


def snapshot_issue(raw: Mapping[str, Any], *, repository: str, number: int) -> IssueSnapshot:
    """Normalize caller-observed GET; verified identity is caller's responsibility.

    The repository must come from the independently authenticated endpoint,
    never from user-supplied Issue Markdown. This function cannot prove that.
    """
    if type(repository) is not str or _REPO.fullmatch(repository) is None:
        raise MetadataPreflightRejected("INVALID_REPOSITORY")
    if type(number) is not int or number <= 0:
        raise MetadataPreflightRejected("INVALID_ISSUE_NUMBER")
    if not isinstance(raw, Mapping):
        raise MetadataPreflightRejected("MISSING_OBSERVATION")
    repo = raw.get("repository")
    actual = raw.get("number")
    updated = raw.get("updated_at")
    body = raw.get("body")
    state = raw.get("state")
    if (repo != repository or type(repo) is not str or
            type(actual) is not int or actual != number or
            type(updated) is not str or _UPDATED.fullmatch(updated) is None or
            type(body) is not str or _bytes(body) > _MAX_BODY or
            state != "open"):
        raise MetadataPreflightRejected("TARGET_OR_OBSERVATION_MISMATCH")
    return IssueSnapshot(repository, number, updated, body)


def plan_section_transition(
    observed: IssueSnapshot,
    *,
    start_anchor: str,
    end_anchor: str,
    replacement_section: str,
) -> SectionTransition:
    """Replace one precisely bounded existing section, preserving every other byte.

    New section is complete including heading and trailing newlines. Anchors
    must be unique in the observed source; this isn't a free-text regex patch.
    """
    if type(observed) is not IssueSnapshot:
        raise MetadataPreflightRejected("UNTRUSTED_OBSERVATION_SHAPE")
    original = observed.body
    if (not all(type(v) is str for v in (start_anchor, end_anchor, replacement_section))
            or not (8 <= _bytes(start_anchor) <= 240)
            or not (8 <= _bytes(end_anchor) <= 240)
            or not start_anchor.startswith("### ")
            or not end_anchor.startswith("### ")
            or not replacement_section.startswith("### ")
            or start_anchor == end_anchor
            or original.count(start_anchor) != 1
            or original.count(end_anchor) != 1):
        raise MetadataPreflightRejected("NONUNIQUE_OR_INVALID_SECTION")
    start = original.index(start_anchor)
    end = original.index(end_anchor)
    if end <= start or (start > 0 and original[start - 1] != "\n"):
        raise MetadataPreflightRejected("INVALID_SECTION_BOUNDARY")
    before_section = original[start:end]
    if (not before_section.startswith(start_anchor + "\n")
            or _bytes(before_section) > _MAX_SECTION
            or _bytes(replacement_section) > _MAX_SECTION
            or not replacement_section.endswith("\n\n")
            or end_anchor in replacement_section
            or start_anchor in replacement_section
            or _bytes(replacement_section) + _bytes(before_section) > 2 * _MAX_SECTION):
        raise MetadataPreflightRejected("UNBOUNDED_OR_UNSAFE_SECTION")
    after = original[:start] + replacement_section + original[end:]
    if (_bytes(after) > _MAX_BODY
            or _bytes(replacement_section) + _bytes(before_section) > 2 * _MAX_SECTION
            or abs(_bytes(replacement_section) - _bytes(before_section)) > _MAX_DELTA
            or after == original
            or after.count(end_anchor) != 1):
        raise MetadataPreflightRejected("CHANGE_OUTSIDE_BOUNDS_OR_NOOP")
    return SectionTransition(
        repository=observed.repository, number=observed.number,
        observed_updated_at=observed.updated_at,
        observed_body_sha256=_digest(original),
        after_body_sha256=_digest(after),
        before_body=original, after_body=after,
        changed_section_before=before_section,
        changed_section_after=replacement_section,
    )


def prewrite_verdict(plan: SectionTransition, current: IssueSnapshot) -> str:
    """READY only after a new caller GET equal to the complete observed state.

    READY is not authorization and does not make GitHub Issue PATCH atomic.
    Caller must stop/replan on STALE and not infer a lock or reusable grant.
    """
    if type(plan) is not SectionTransition or type(current) is not IssueSnapshot:
        return "REJECTED"
    if current.repository != plan.repository or current.number != plan.number:
        return "REJECTED"
    if (current.body == plan.after_body and
            _digest(current.body) == plan.after_body_sha256):
        return "NO_OP"
    if (current.updated_at != plan.observed_updated_at
            or current.body != plan.before_body
            or _digest(current.body) != plan.observed_body_sha256):
        return "STALE"
    return "READY"


def postwrite_verdict(plan: SectionTransition, fresh: IssueSnapshot) -> str:
    """Reconcile a potentially ambiguous effect; never auto-issue another PATCH."""
    if type(plan) is not SectionTransition or type(fresh) is not IssueSnapshot:
        return "REJECTED"
    if fresh.repository != plan.repository or fresh.number != plan.number:
        return "REJECTED"
    if fresh.body == plan.after_body and _digest(fresh.body) == plan.after_body_sha256:
        return "POSTREAD_VERIFIED"
    if fresh.body == plan.before_body and _digest(fresh.body) == plan.observed_body_sha256:
        return "NOT_APPLIED"
    return "UNKNOWN_RECONCILE"
