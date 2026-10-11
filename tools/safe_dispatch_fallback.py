"""Offline-only, fail-closed route diagnostics for devflow #448.

This module is NOT a trusted authenticated adapter, executable dispatcher,
credential manager, GitHub billing detector, or execution authorization.
EvidenceSnapshot is caller-supplied and has NO provenance proof. A PLAN_ONLY
result must never become a runtime execution approval.
"""
from __future__ import annotations

from dataclasses import dataclass

from tools.safe_dispatch_contract import Admission


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Reported conditions: future adapter must independently prove each one."""

    visibility: str                         # public | private
    connector_operation: str = "unknown"    # verified | unsupported | unknown
    local_gh_cli: str = "unknown"          # authenticated_owner_observed | unavailable | unknown
    fixed_workflow_trigger: str = "unknown"  # verified | unavailable | unknown
    hosted_runner: str = "unknown"          # available | private_quota_exhausted
                                             # private_billing_blocked | all_actions_disabled | unknown
    self_hosted_runner: str = "unknown"     # ready | unavailable | unknown
    self_hosted_isolation: str = "unknown"  # verified | unsafe | unknown
    self_hosted_approved: bool = False      # human approval; not provable here


@dataclass(frozen=True)
class RouteDiagnostic:
    status: str   # PLAN_ONLY or HOLD, NEVER ADMITTED/EXECUTED
    route: str | None
    reason: str


_ENUMS = {
    "visibility": frozenset(("public", "private")),
    "connector_operation": frozenset(("verified", "unsupported", "unknown")),
    "local_gh_cli": frozenset(("authenticated_owner_observed", "unavailable", "unknown")),
    "fixed_workflow_trigger": frozenset(("verified", "unavailable", "unknown")),
    "hosted_runner": frozenset((
        "available", "private_quota_exhausted", "private_billing_blocked",
        "all_actions_disabled", "unknown"
    )),
    "self_hosted_runner": frozenset(("ready", "unavailable", "unknown")),
    "self_hosted_isolation": frozenset(("verified", "unsafe", "unknown")),
}


def _facts_valid(facts: EvidenceSnapshot) -> bool:
    if type(facts) is not EvidenceSnapshot:
        return False
    for field, choices in _ENUMS.items():
        value = getattr(facts, field)
        if type(value) is not str or value not in choices:
            return False
    return type(facts.self_hosted_approved) is bool


def plan_fallback(admission: object, facts: object) -> RouteDiagnostic:
    """Recommend a possible route only. Never perform or authorize execution."""
    def hold(reason: str) -> RouteDiagnostic:
        return RouteDiagnostic("HOLD", None, reason)

    def candidate(route: str, reason: str) -> RouteDiagnostic:
        return RouteDiagnostic("PLAN_ONLY", route, reason)

    if not _facts_valid(facts):
        return hold("INVALID_OR_UNVERIFIED_FACT_SHAPE")
    if type(admission) is not Admission or admission.status != "ADMITTED" or (
        admission.reason != "POLICY_ADMITTED_NOT_EXECUTED"
    ):
        return hold("G1_POLICY_NOT_ADMITTED")
    if (type(admission.request_id) is not str
            or type(admission.repository) is not str
            or type(admission.action) is not str
            or type(admission.executor) is not str
            or type(admission.head_sha) is not str):
        return hold("INCOMPLETE_ADMISSION")
    if admission.backend == "github_api":
        if admission.reviewed_workflow_sha is not None:
            return hold("BACKEND_PIN_MISMATCH")
        if facts.connector_operation == "verified":
            return candidate(
                "GITHUB_CONNECTOR_INTERACTIVE",
                "DIRECT_TYPED_OPERATION_ONLY_NOT_MACHINE_ENFORCED",
            )
        if facts.connector_operation == "unsupported":
            if facts.local_gh_cli == "authenticated_owner_observed":
                return candidate(
                    "OWNER_LOCAL_GH_CLI_API",
                    "OPERATION_PERMISSION_AND_LOCAL_SESSION_MUST_BE_RECHECKED_NOT_EXECUTED",
                )
            return hold("NEEDS_SEPARATELY_AUTHORIZED_API_TRANSPORT")
        return hold("CONNECTOR_OPERATION_CAPABILITY_UNKNOWN")

    if admission.backend != "github_actions":
        return hold("UNSUPPORTED_CATALOG_BACKEND")
    if (type(admission.reviewed_workflow_sha) is not str
            or len(admission.reviewed_workflow_sha) != 40
            or any(c not in "0123456789abcdef"
                   for c in admission.reviewed_workflow_sha)):
        return hold("REVIEWED_WORKFLOW_NOT_PINNED")
    # Existing fixed ISSUE receiver is not a general workflow_dispatch endpoint.
    if facts.fixed_workflow_trigger != "verified":
        return hold("FIXED_OPERATION_TRIGGER_NOT_VERIFIED")
    if facts.hosted_runner == "all_actions_disabled":
        return hold("ALL_ACTIONS_DISABLED_NO_RUNNER_BYPASS")
    if facts.hosted_runner == "available":
        return candidate(
            "GITHUB_HOSTED_FIXED_WORKFLOW",
            "HOSTED_CAPACITY_REPORTED_NOT_EXECUTED",
        )
    if facts.hosted_runner == "unknown":
        return hold("HOSTED_CAPACITY_CAUSE_UNVERIFIED")
    if facts.visibility != "private":
        return hold("PRIVATE_QUOTA_STATE_ON_PUBLIC_REPO")
    if facts.hosted_runner == "private_billing_blocked":
        return hold("PRIVATE_BILLING_BLOCK_NEEDS_FRESH_RUNNER_ELIGIBILITY")

    # Only a confirmed PRIVATE hosted-minute exhaustion may try this
    # route. This does NOT prove self-hosted scheduling or GitHub auth.
    if facts.self_hosted_runner == "ready":
        if facts.self_hosted_isolation != "verified":
            return hold("SELF_HOSTED_UNTRUSTED_OR_UNISOLATED")
        if not facts.self_hosted_approved:
            return hold("SELF_HOSTED_HUMAN_GATE")
        return candidate(
            "PRIVATE_SELF_HOSTED_FIXED_WORKFLOW",
            "NO_HOSTED_MINUTES_PLAN_ONLY_NOT_SCHEDULED",
        )
    return hold("INDEPENDENT_COMPUTE_BACKEND_REQUIRED")


__all__ = ["EvidenceSnapshot", "RouteDiagnostic", "plan_fallback"]
