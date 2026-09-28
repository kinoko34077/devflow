"""Pure stale/interrupted Execution Session assessment.

This module only classifies observed evidence.  It does not mutate a Session
Record, claim work, launch a successor, or perform GitHub reconciliation.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Optional, Sequence


STALE_AFTER = timedelta(hours=1)
CONTRACT_VERSION = "development-reconciliation.v1"
ACTIVE_STATUSES = frozenset({"CLAIMED", "RUNNING", "WAITING"})
TERMINAL_STATUSES = frozenset({"HANDOFF", "FAILED", "RELEASED"})
KNOWN_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class SessionEvidence:
    task_ref: str
    session_id: str
    status: str
    last_trusted_update: datetime
    checkpoint: str
    named_blocker: Optional[str] = None
    blocker_resolved: bool = False
    linked_activity_after_checkpoint: bool = False
    branch_ref: Optional[str] = None
    successor_present: bool = False


@dataclass(frozen=True)
class ArtifactEvidence:
    has_durable_artifact: bool = False
    complete_enough: bool = False
    pr_number: Optional[int] = None
    head_sha: Optional[str] = None
    first_unfinished_action: Optional[str] = None
    human_gate: Optional[str] = None
    contradictory: bool = False


def _require_aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _timestamp(value: datetime) -> str:
    return (
        _require_aware(value, "timestamp")
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _base_result(
    session: SessionEvidence,
    observed_at: datetime,
    *,
    stale: bool,
    disposition: str,
    assessment_kind: str,
    reason_codes: Sequence[str],
    next_action: Optional[str],
    transition: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "task_ref": session.task_ref,
        "predecessor_session_id": session.session_id,
        "observed_status": session.status,
        "checkpoint": session.checkpoint,
        "observed_at": _timestamp(observed_at),
        "stale_rule": {
            "threshold_hours": STALE_AFTER.total_seconds() / 3600,
            "last_trusted_update": _timestamp(session.last_trusted_update),
            "linked_activity_after_checkpoint": session.linked_activity_after_checkpoint,
            "stale": stale,
        },
        "disposition": disposition,
        "assessment_kind": assessment_kind,
        "reason_codes": list(reason_codes),
        "next_action": next_action,
        "transition": transition,
    }


def assess_session(
    session: SessionEvidence,
    artifacts: ArtifactEvidence,
    *,
    observed_at: datetime,
) -> Dict[str, Any]:
    """Return a deterministic, non-mutating recovery assessment.

    The result is an observation and a bounded transition proposal.  Callers
    must separately verify any proposed transition against live evidence.
    """

    if not isinstance(session, SessionEvidence):
        raise TypeError("session must be SessionEvidence")
    if not isinstance(artifacts, ArtifactEvidence):
        raise TypeError("artifacts must be ArtifactEvidence")

    observed_at = _require_aware(observed_at, "observed_at")
    _require_aware(session.last_trusted_update, "last_trusted_update")

    if not session.task_ref or not session.session_id or not session.checkpoint:
        return _base_result(
            session,
            observed_at,
            stale=False,
            disposition="NEEDS_EVIDENCE",
            assessment_kind="INVALID_SESSION_EVIDENCE",
            reason_codes=["MISSING_SESSION_IDENTITY_OR_CHECKPOINT"],
            next_action="re-read the owning task and Session Record before recovery",
            transition=None,
        )

    if session.status not in KNOWN_STATUSES:
        return _base_result(
            session,
            observed_at,
            stale=False,
            disposition="NEEDS_EVIDENCE",
            assessment_kind="UNKNOWN_STATUS",
            reason_codes=["UNKNOWN_SESSION_STATUS"],
            next_action="confirm the Session Record status from live evidence",
            transition=None,
        )

    if session.last_trusted_update > observed_at:
        return _base_result(
            session,
            observed_at,
            stale=False,
            disposition="NEEDS_EVIDENCE",
            assessment_kind="INVALID_TIME_ORDER",
            reason_codes=["LAST_UPDATE_AFTER_OBSERVATION"],
            next_action="confirm timestamps from the live Session Record",
            transition=None,
        )

    age = observed_at - session.last_trusted_update
    stale = age >= STALE_AFTER and not session.linked_activity_after_checkpoint

    if artifacts.contradictory:
        return _base_result(
            session,
            observed_at,
            stale=stale,
            disposition="NEEDS_EVIDENCE",
            assessment_kind="AMBIGUOUS_EVIDENCE",
            reason_codes=["CONTRADICTORY_ARTIFACT_EVIDENCE"],
            next_action="resolve the conflicting artifact identities before any recovery",
            transition=None,
        )

    if session.successor_present:
        return _base_result(
            session,
            observed_at,
            stale=stale,
            disposition="NEEDS_EVIDENCE",
            assessment_kind="AMBIGUOUS_COLLISION",
            reason_codes=["SUCCESSOR_COLLISION"],
            next_action="resolve the existing successor before any recovery",
            transition=None,
        )

    if artifacts.human_gate:
        return _base_result(
            session,
            observed_at,
            stale=stale,
            disposition="NEEDS_HUMAN",
            assessment_kind="HUMAN_GATE",
            reason_codes=["EXPLICIT_HUMAN_GATE"],
            next_action=artifacts.human_gate,
            transition=None,
        )

    if session.status in TERMINAL_STATUSES:
        return _base_result(
            session,
            observed_at,
            stale=False,
            disposition="NO_ACTION",
            assessment_kind="EXPLICIT_TERMINAL",
            reason_codes=["EXPLICIT_SESSION_TERMINAL"],
            next_action=None,
            transition=None,
        )

    if (
        session.status == "WAITING"
        and session.named_blocker
        and not session.blocker_resolved
    ):
        return _base_result(
            session,
            observed_at,
            stale=stale,
            disposition="WAIT_EXTERNAL",
            assessment_kind="STILL_WAITING",
            reason_codes=["NAMED_BLOCKER_ACTIVE"],
            next_action=session.named_blocker,
            transition=None,
        )

    if not stale:
        return _base_result(
            session,
            observed_at,
            stale=False,
            disposition="NO_ACTION",
            assessment_kind="ACTIVE_SESSION",
            reason_codes=["TRUSTED_ACTIVITY_RECENT"],
            next_action=None,
            transition=None,
        )

    if artifacts.complete_enough:
        if (
            not artifacts.has_durable_artifact
            or not artifacts.pr_number
            or not artifacts.head_sha
            or not SHA_RE.fullmatch(artifacts.head_sha)
        ):
            return _base_result(
                session,
                observed_at,
                stale=True,
                disposition="NEEDS_EVIDENCE",
                assessment_kind="INCOMPLETE_IDENTITY",
                reason_codes=["COMPLETE_ARTIFACT_LACKS_EXACT_PR_IDENTITY"],
                next_action="confirm the exact PR number and head SHA before reconciliation",
                transition=None,
            )

        return _base_result(
            session,
            observed_at,
            stale=True,
            disposition="AUTO_ADVANCE",
            assessment_kind="COMPLETE_ENOUGH_ARTIFACT",
            reason_codes=["ARTIFACTS_COMPLETE_ENOUGH"],
            next_action=None,
            transition={
                "kind": "PR_RECONCILIATION",
                "pr_number": artifacts.pr_number,
                "expected_head_sha": artifacts.head_sha.lower(),
            },
        )

    if artifacts.has_durable_artifact:
        next_action = (
            artifacts.first_unfinished_action
            or "re-read the owning task and live artifacts before takeover"
        )
        return _base_result(
            session,
            observed_at,
            stale=True,
            disposition="NEEDS_RECOVERY",
            assessment_kind="RECOVERABLE_PARTIAL_ARTIFACT",
            reason_codes=["STALE_SESSION_WITH_PARTIAL_ARTIFACT"],
            next_action=next_action,
            transition={
                "kind": "RECOVERY_ASSESSMENT",
                "predecessor_session_id": session.session_id,
                "checkpoint": session.checkpoint,
            },
        )

    return _base_result(
        session,
        observed_at,
        stale=True,
        disposition="NEEDS_RECOVERY",
        assessment_kind="NO_ARTIFACT",
        reason_codes=["STALE_SESSION_WITHOUT_ARTIFACT"],
        next_action="re-read the owning task and evaluate successor eligibility",
        transition={
            "kind": "SUCCESSOR_ELIGIBILITY_EVALUATION",
            "predecessor_session_id": session.session_id,
        },
    )
