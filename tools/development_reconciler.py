from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


VALID_SHA_LEN = 40

DISPOSITIONS: tuple[str, ...] = (
    "AUTO_ADVANCE",
    "NEEDS_REVIEWER",
    "NEEDS_RECOVERY",
    "NEEDS_HUMAN",
    "WAIT_EXTERNAL",
    "NEEDS_EVIDENCE",
    "NO_ACTION",
)


@dataclass(frozen=True)
class Decision:
    disposition: str
    reason_codes: tuple[str, ...]
    transition: str | None = None
    expected_head_sha: str | None = None
    actions: tuple[str, ...] = ()
    pr_number: int | None = None
    task_ref: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    applied: bool
    already_applied: bool = False
    disposition: str = "NO_ACTION"
    reason: str = ""


class PullRequestTransport(Protocol):
    def get_pr(self, repository: str, pr_number: int) -> dict[str, Any]: ...

    def merge_pr(
        self,
        repository: str,
        pr_number: int,
        expected_head_sha: str,
    ) -> bool: ...


class PostMergeTransport(Protocol):
    def get_reconciliation_state(
        self,
        task_ref: str,
        pr_number: int,
    ) -> dict[str, Any]: ...

    def close_task(self, task_ref: str) -> bool: ...

    def update_current_state(self, task_ref: str) -> bool: ...

    def update_control(self, task_ref: str) -> bool: ...


def _invalid_sha(value: str) -> bool:
    return (
        not isinstance(value, str)
        or len(value) != VALID_SHA_LEN
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    )


def evaluate_pr(evidence: dict[str, Any]) -> Decision:
    required = (
        "task_ref",
        "task_kind",
        "task_open",
        "acceptance_satisfied",
        "pr_number",
        "pr_state",
        "pr_head_sha",
        "expected_head_sha",
        "checks",
        "formal_review",
        "different_reviewer_required",
        "different_reviewer",
        "request_changes",
        "blocking_finding",
        "owning_blocker",
        "human_gate",
        "external_wait",
        "mergeable",
        "revertible",
        "current_state_changed",
        "control_changed",
        "evidence_complete",
    )
    if any(key not in evidence for key in required) or not evidence.get(
        "evidence_complete", False
    ):
        return Decision("NEEDS_EVIDENCE", ("INCOMPLETE_EVIDENCE",))

    task_ref = str(evidence["task_ref"])
    pr_head_sha = str(evidence["pr_head_sha"])
    expected_head_sha = str(evidence["expected_head_sha"])
    if (
        _invalid_sha(pr_head_sha)
        or _invalid_sha(expected_head_sha)
        or pr_head_sha != expected_head_sha
    ):
        return Decision(
            "NEEDS_EVIDENCE",
            ("HEAD_IDENTITY_MISMATCH",),
            task_ref=task_ref,
        )

    if evidence["human_gate"] or not evidence["revertible"]:
        return Decision(
            "NEEDS_HUMAN",
            (
                "HUMAN_GATE"
                if evidence["human_gate"]
                else "NON_REVERTIBLE_OPERATION",
            ),
            task_ref=task_ref,
        )
    if evidence["external_wait"]:
        return Decision(
            "WAIT_EXTERNAL",
            ("EXTERNAL_DEPENDENCY",),
            task_ref=task_ref,
        )

    state = str(evidence["pr_state"]).upper()
    if state == "OPEN":
        checks = str(evidence["checks"]).upper()
        if checks in {"MISSING", "STALE", "UNKNOWN"}:
            return Decision(
                "NEEDS_EVIDENCE",
                (f"REQUIRED_CHECKS_{checks}",),
                task_ref=task_ref,
            )
        if checks == "PENDING":
            return Decision(
                "WAIT_EXTERNAL",
                ("REQUIRED_CHECKS_PENDING",),
                task_ref=task_ref,
            )
        if checks != "PASS":
            return Decision(
                "NO_ACTION",
                ("REQUIRED_CHECKS_FAILED",),
                task_ref=task_ref,
            )

        review = str(evidence["formal_review"]).upper()
        if review in {"MISSING", "STALE", "UNKNOWN"}:
            return Decision(
                "NEEDS_EVIDENCE",
                (f"FORMAL_REVIEW_{review}",),
                task_ref=task_ref,
            )
        if (
            review != "PASS"
            or evidence["request_changes"]
            or evidence["blocking_finding"]
        ):
            reasons: list[str] = []
            if review != "PASS":
                reasons.append("FORMAL_REVIEW_BLOCKING")
            if evidence["request_changes"]:
                reasons.append("REQUEST_CHANGES")
            if evidence["blocking_finding"]:
                reasons.append("BLOCKING_FINDING")
            return Decision("NO_ACTION", tuple(reasons), task_ref=task_ref)

        if evidence["different_reviewer_required"]:
            different_reviewer = str(evidence["different_reviewer"]).upper()
            if different_reviewer != "PASS":
                return Decision(
                    "NEEDS_REVIEWER",
                    (f"DIFFERENT_REVIEWER_{different_reviewer}",),
                    expected_head_sha=pr_head_sha,
                    pr_number=evidence["pr_number"],
                    task_ref=task_ref,
                )

        if (
            evidence["owning_blocker"]
            or not evidence["task_open"]
            or not evidence["acceptance_satisfied"]
        ):
            reasons = []
            if evidence["owning_blocker"]:
                reasons.append("OWNING_TASK_BLOCKED")
            if not evidence["task_open"]:
                reasons.append("OWNING_TASK_NOT_OPEN")
            if not evidence["acceptance_satisfied"]:
                reasons.append("ACCEPTANCE_UNSATISFIED")
            return Decision("NO_ACTION", tuple(reasons), task_ref=task_ref)

        if evidence["mergeable"] is None:
            return Decision(
                "NEEDS_EVIDENCE",
                ("MERGEABILITY_UNKNOWN",),
                task_ref=task_ref,
            )
        if not evidence["mergeable"]:
            return Decision("NO_ACTION", ("PR_NOT_MERGEABLE",), task_ref=task_ref)
        return Decision(
            "AUTO_ADVANCE",
            (
                "REQUIRED_CHECKS_PASS",
                "FORMAL_REVIEW_FRESH",
                "ACCEPTANCE_SATISFIED",
            ),
            transition="MERGE_PR",
            expected_head_sha=pr_head_sha,
            pr_number=evidence["pr_number"],
            task_ref=task_ref,
        )

    if state == "MERGED":
        if not evidence["acceptance_satisfied"]:
            return Decision(
                "NO_ACTION",
                ("ACCEPTANCE_UNSATISFIED",),
                task_ref=task_ref,
            )
        actions: list[str] = []
        if evidence["task_kind"] == "FINITE" and evidence["task_open"]:
            actions.append("CLOSE_OWNING_TASK")
        if evidence["current_state_changed"]:
            actions.append("UPDATE_CURRENT_STATE")
        if evidence["control_changed"]:
            actions.append("UPDATE_CONTROL")
        if actions:
            return Decision(
                "AUTO_ADVANCE",
                ("PR_MERGED", "ACCEPTANCE_SATISFIED"),
                transition="POST_MERGE_RECONCILE",
                expected_head_sha=pr_head_sha,
                actions=tuple(actions),
                pr_number=evidence["pr_number"],
                task_ref=task_ref,
            )
        return Decision(
            "NO_ACTION",
            ("POST_MERGE_ALREADY_RECONCILED",),
            task_ref=task_ref,
        )

    return Decision("NO_ACTION", ("PR_NOT_ACTIVE",), task_ref=task_ref)


def execute_merge(
    decision: Decision,
    transport: PullRequestTransport,
    repository: str,
) -> ExecutionResult:
    if (
        decision.disposition != "AUTO_ADVANCE"
        or decision.transition != "MERGE_PR"
        or decision.pr_number is None
        or decision.expected_head_sha is None
    ):
        return ExecutionResult(
            False,
            False,
            decision.disposition,
            "not a merge transition",
        )

    current = transport.get_pr(repository, decision.pr_number)
    if current.get("merged") is True:
        if str(current.get("head_sha")) == decision.expected_head_sha:
            return ExecutionResult(
                False,
                True,
                "AUTO_ADVANCE",
                "already merged at expected head",
            )
        return ExecutionResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "merged PR head differs from transition guard",
        )

    if (
        str(current.get("state")).lower() != "open"
        or str(current.get("head_sha")) != decision.expected_head_sha
    ):
        return ExecutionResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "PR state/head changed before merge",
        )

    merged = transport.merge_pr(
        repository,
        decision.pr_number,
        decision.expected_head_sha,
    )
    if not merged:
        return ExecutionResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "merge attempt not confirmed",
        )

    observed = transport.get_pr(repository, decision.pr_number)
    if (
        observed.get("merged") is not True
        or str(observed.get("head_sha")) != decision.expected_head_sha
    ):
        return ExecutionResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "post-merge readback did not confirm expected head",
        )
    return ExecutionResult(
        True,
        False,
        "AUTO_ADVANCE",
        "merge confirmed by post-merge readback",
    )


def execute_post_merge(
    decision: Decision,
    transport: PostMergeTransport,
) -> ExecutionResult:
    if (
        decision.disposition != "AUTO_ADVANCE"
        or decision.transition != "POST_MERGE_RECONCILE"
        or decision.task_ref is None
        or decision.pr_number is None
        or decision.expected_head_sha is None
    ):
        return ExecutionResult(
            False,
            False,
            decision.disposition,
            "not a post-merge reconciliation transition",
        )

    observed = transport.get_reconciliation_state(
        decision.task_ref,
        decision.pr_number,
    )
    required = {
        "task_ref",
        "pr_number",
        "pr_head_sha",
        "pr_merged",
        "acceptance_satisfied",
        "human_gate",
        "external_wait",
        "owning_blocker",
    }
    if not required.issubset(observed):
        return ExecutionResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "post-merge re-observation is incomplete",
        )
    if (
        str(observed["task_ref"]) != decision.task_ref
        or observed["pr_number"] != decision.pr_number
        or str(observed["pr_head_sha"]) != decision.expected_head_sha
        or observed["pr_merged"] is not True
    ):
        return ExecutionResult(
            False,
            False,
            "NEEDS_EVIDENCE",
            "post-merge identity/head evidence changed",
        )
    if observed["human_gate"]:
        return ExecutionResult(
            False,
            False,
            "NEEDS_HUMAN",
            "a Human Gate appeared before reconciliation",
        )
    if observed["external_wait"]:
        return ExecutionResult(
            False,
            False,
            "WAIT_EXTERNAL",
            "an external dependency appeared before reconciliation",
        )
    if observed["owning_blocker"] or observed["acceptance_satisfied"] is not True:
        return ExecutionResult(
            False,
            False,
            "NO_ACTION",
            "owning task is not currently eligible for reconciliation",
        )

    operations = {
        "CLOSE_OWNING_TASK": transport.close_task,
        "UPDATE_CURRENT_STATE": transport.update_current_state,
        "UPDATE_CONTROL": transport.update_control,
    }
    applied_any = False
    for action in decision.actions:
        operation = operations.get(action)
        if operation is None:
            return ExecutionResult(
                applied_any,
                False,
                "NEEDS_EVIDENCE",
                f"unsupported post-merge action: {action}",
            )
        applied_any = bool(operation(decision.task_ref)) or applied_any

    return ExecutionResult(
        applied_any,
        not applied_any,
        "AUTO_ADVANCE",
        (
            "post-merge reconciliation applied"
            if applied_any
            else "post-merge reconciliation already applied"
        ),
    )
