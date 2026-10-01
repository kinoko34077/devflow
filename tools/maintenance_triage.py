from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tools.development_reconciler import DISPOSITIONS


ACTIONS: tuple[str, ...] = (
    "NO_TRACK",
    "ROUTE_EXISTING_GATE",
    "RECORD_NONRUNNABLE_FINDING",
    "PUBLISH_EXISTING_OWNER",
    "PLAN_SYNC_CHECK",
)
_ALLOWLISTED_SYNC_TRANSITIONS = frozenset(
    {"WITHDRAW_STALE_CONTROL_CANDIDATE"}
)
_REPORT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class TriageContractError(ValueError):
    pass


@dataclass(frozen=True)
class TriageDecision:
    action: str
    report_id: str
    disposition: str
    work_class: str | None
    owner_ref: str | None
    reason_codes: tuple[str, ...]


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise TriageContractError(
            f"{field} must be an array of strings"
        )
    return tuple(value)


def _owner_ref(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or "#" not in value:
        raise TriageContractError(
            "owner_ref must be owner/repository#number or null"
        )
    return value


def _decision(
    *,
    action: str,
    report_id: str,
    disposition: str,
    work_class: str | None,
    owner_ref: str | None,
    reason_codes: tuple[str, ...],
) -> TriageDecision:
    if action not in ACTIONS:
        raise TriageContractError(
            f"unknown triage action: {action}"
        )
    return TriageDecision(
        action=action,
        report_id=report_id,
        disposition=disposition,
        work_class=work_class,
        owner_ref=owner_ref,
        reason_codes=reason_codes,
    )


def triage(report: dict[str, object]) -> TriageDecision:
    if not isinstance(report, dict):
        raise TriageContractError("report must be an object")

    report_id = report.get("report_id")
    if (
        not isinstance(report_id, str)
        or _REPORT_ID.fullmatch(report_id) is None
    ):
        raise TriageContractError(
            "report_id must be a canonical sha256 identity"
        )

    disposition = report.get("disposition")
    if disposition not in DISPOSITIONS:
        raise TriageContractError(
            f"unknown reconciliation disposition: {disposition}"
        )

    reason_codes = _strings(
        report.get("reason_codes"),
        "reason_codes",
    )
    finding_classes = _strings(
        report.get("finding_classes"),
        "finding_classes",
    )
    owner_ref = _owner_ref(report.get("owner_ref"))
    transition = report.get("next_transition")
    if transition is not None and not isinstance(
        transition, str
    ):
        raise TriageContractError(
            "next_transition must be a string or null"
        )

    if disposition == "NO_ACTION":
        return _decision(
            action="NO_TRACK",
            report_id=report_id,
            disposition=disposition,
            work_class=None,
            owner_ref=owner_ref,
            reason_codes=reason_codes,
        )

    if disposition in {
        "NEEDS_REVIEWER",
        "NEEDS_HUMAN",
        "WAIT_EXTERNAL",
    }:
        return _decision(
            action="ROUTE_EXISTING_GATE",
            report_id=report_id,
            disposition=disposition,
            work_class=None,
            owner_ref=owner_ref,
            reason_codes=reason_codes,
        )

    if disposition == "NEEDS_EVIDENCE":
        return _decision(
            action="RECORD_NONRUNNABLE_FINDING",
            report_id=report_id,
            disposition=disposition,
            work_class=None,
            owner_ref=owner_ref,
            reason_codes=reason_codes,
        )

    if (
        disposition == "AUTO_ADVANCE"
        and transition in _ALLOWLISTED_SYNC_TRANSITIONS
        and owner_ref is not None
    ):
        return _decision(
            action="PLAN_SYNC_CHECK",
            report_id=report_id,
            disposition=disposition,
            work_class="sync-check",
            owner_ref=owner_ref,
            reason_codes=reason_codes,
        )

    if (
        disposition in {"AUTO_ADVANCE", "NEEDS_RECOVERY"}
        and owner_ref is not None
    ):
        return _decision(
            action="PUBLISH_EXISTING_OWNER",
            report_id=report_id,
            disposition=disposition,
            work_class="triage",
            owner_ref=owner_ref,
            reason_codes=reason_codes,
        )

    return _decision(
        action="RECORD_NONRUNNABLE_FINDING",
        report_id=report_id,
        disposition=disposition,
        work_class=None,
        owner_ref=owner_ref,
        reason_codes=reason_codes,
    )
