#!/usr/bin/env python3
"""Advisory Review Provenance readiness evaluator.

This validates declared metadata consistency only. It does not prove reviewer
identity or replace semantic code review.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


_STATE_TO_DECISION = {
    "COMMENTED": "COMMENT",
    "APPROVED": "APPROVE",
    "CHANGES_REQUESTED": "REQUEST_CHANGES",
}
_READY_REVIEW_STATES = {"COMMENTED", "APPROVED"}
_FORBIDDEN_DERIVED_FIELDS = {"Review-Role", "Independence"}


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    reason: str
    matched_review_id: int | None = None


def _single_field(body: str, name: str) -> tuple[str | None, bool]:
    pattern = re.compile(rf"(?mi)^\s*-\s*{re.escape(name)}\s*:\s*(.*?)\s*$")
    values = [match.group(1).strip() for match in pattern.finditer(body or "")]
    if len(values) != 1:
        return None, False
    return values[0], True


def _yes_no_field(body: str, name: str) -> tuple[bool | None, bool]:
    value, unique = _single_field(body, name)
    if not unique or value is None:
        return None, False
    normalized = value.casefold()
    if normalized == "yes":
        return True, True
    if normalized == "no":
        return False, True
    return None, False


def _provenance_fields(body: str) -> dict[str, str] | None:
    match = re.search(r"(?mi)^###\s+Review Provenance\s*$", body or "")
    if not match:
        return None
    tail = (body or "")[match.end() :]
    next_heading = re.search(r"(?m)^#{1,6}\s+", tail)
    section = tail[: next_heading.start()] if next_heading else tail
    fields: dict[str, str] = {}
    for key, value in re.findall(
        r"(?m)^\s*-\s*([A-Za-z][A-Za-z0-9-]*)\s*:\s*(.*?)\s*$",
        section,
    ):
        if key in fields:
            return None
        fields[key] = value.strip()
    required = {
        "Reviewer-System",
        "Reviewer-Model",
        "Implementer-System",
        "Implementer-Model",
        "Reviewed-Commit",
        "Review-Scope",
        "Decision",
        "Review-Provenance-Version",
    }
    if not required.issubset(fields):
        return None
    return fields


def _blocking_findings(body: str) -> str | None:
    value, unique = _single_field(body, "Blocking findings")
    return value if unique else None


def _signature(system: str, model: str) -> tuple[str, str]:
    return system.strip(), model.strip()


def _review_rejection(
    review: dict[str, Any],
    *,
    implementer_signature: tuple[str, str],
    head_sha: str,
) -> str | None:
    body = str(review.get("body") or "")
    fields = _provenance_fields(body)
    if fields is None:
        return "No valid formal review provenance found"

    if fields["Review-Provenance-Version"] != "2":
        return "Unsupported formal review provenance version"
    if _FORBIDDEN_DERIVED_FIELDS.intersection(fields):
        return "Review Provenance v2 must not persist derived reviewer-relation fields"
    if fields["Reviewed-Commit"] != head_sha:
        return "Formal review does not target current head"

    commit_id = review.get("commit_id")
    if commit_id and str(commit_id) != head_sha:
        return "Formal review API commit does not match current head"

    declared_implementer = _signature(
        fields["Implementer-System"], fields["Implementer-Model"]
    )
    if declared_implementer != implementer_signature:
        return "Formal review implementer provenance does not match PR"

    blocking = _blocking_findings(body)
    if blocking is None or blocking.casefold() != "none":
        return "Formal review declares blocking findings or lacks a clear none result"

    state = str(review.get("state") or "").upper()
    expected_decision = _STATE_TO_DECISION.get(state)
    if expected_decision is None:
        return "Formal review is not in a recognized submitted state"
    if fields["Decision"] != expected_decision:
        return "Formal review API state and declared decision do not match"
    if state not in _READY_REVIEW_STATES:
        return "Formal review requests changes and remains blocking"

    return None


def _managed_reviews(reviews: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, str]]]:
    managed: list[tuple[dict[str, Any], dict[str, str]]] = []
    for candidate in reviews:
        fields = _provenance_fields(str(candidate.get("body") or ""))
        if fields is not None:
            managed.append((candidate, fields))
    return managed


def evaluate(pr: dict[str, Any], reviews: list[dict[str, Any]]) -> ReadinessResult:
    body = str(pr.get("body") or "")
    formal_required, valid_formal_gate = _yes_no_field(body, "Formal review required")
    different_required, valid_different_gate = _yes_no_field(
        body, "Different reviewer required"
    )
    if not valid_formal_gate or not valid_different_gate:
        return ReadinessResult(False, "Formal/different review gate is missing, ambiguous, or invalid")
    assert formal_required is not None
    assert different_required is not None

    if different_required and not formal_required:
        return ReadinessResult(False, "Review gate is inconsistent: different reviewer requires formal review")
    if not formal_required:
        return ReadinessResult(True, "Formal review is not required by explicit PR classification")

    implementer_system, unique_system = _single_field(body, "Implementer-System")
    implementer_model, unique_model = _single_field(body, "Implementer-Model")
    if (
        not unique_system
        or not unique_model
        or not implementer_system
        or not implementer_model
    ):
        return ReadinessResult(False, "Implementer signature is missing or ambiguous")
    implementer_signature = _signature(implementer_system, implementer_model)

    head = pr.get("head") or {}
    head_sha = str(head.get("sha") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        return ReadinessResult(False, "Current head SHA is missing or invalid")

    managed = _managed_reviews(reviews)
    if not managed:
        if any(
            re.search(r"(?mi)^###\s+Review Provenance\s*$", str(item.get("body") or ""))
            for item in reviews
        ):
            return ReadinessResult(False, "No valid formal review provenance satisfies v2 schema")
        return ReadinessResult(False, "No formal review provenance found")

    latest_review, _latest_fields = managed[-1]
    latest_rejection = _review_rejection(
        latest_review,
        implementer_signature=implementer_signature,
        head_sha=head_sha,
    )
    if latest_rejection is not None:
        return ReadinessResult(False, latest_rejection)

    if not different_required:
        return ReadinessResult(
            True,
            "Current-head formal Review Provenance v2 is present",
            latest_review.get("id"),
        )

    for candidate, fields in reversed(managed):
        reviewer_signature = _signature(fields["Reviewer-System"], fields["Reviewer-Model"])
        if reviewer_signature == implementer_signature:
            continue
        rejection = _review_rejection(
            candidate,
            implementer_signature=implementer_signature,
            head_sha=head_sha,
        )
        if rejection is None:
            return ReadinessResult(
                True,
                "Current-head formal Review Provenance v2 from a different reviewer signature is present",
                candidate.get("id"),
            )
        return ReadinessResult(False, rejection)

    return ReadinessResult(False, "Different reviewer is required but no differing current-head signature qualifies")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-json", required=True, type=Path)
    parser.add_argument("--reviews-json", required=True, type=Path)
    args = parser.parse_args()

    pr = json.loads(args.pr_json.read_text(encoding="utf-8"))
    reviews = json.loads(args.reviews_json.read_text(encoding="utf-8"))
    if not isinstance(pr, dict) or not isinstance(reviews, list):
        raise SystemExit("PR JSON must be an object and reviews JSON must be a list")

    result = evaluate(pr, reviews)
    status = "PASS" if result.ready else "FAIL"
    matched = f" review_id={result.matched_review_id}" if result.matched_review_id else ""
    print(f"review-readiness: {status}{matched} — {result.reason}")
    print("identity-note: Review Provenance is self-asserted metadata, not cryptographic identity.")
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
