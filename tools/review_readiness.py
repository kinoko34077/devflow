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


_ALLOWED_ROLES = {"independent-review", "self-review", "none"}
_ACCEPTED_REVIEW_STATES = {"COMMENTED", "APPROVED"}
_ACCEPTED_DECISIONS = {"COMMENT", "APPROVE"}


@dataclass(frozen=True)
class ReadinessResult:
    ready: bool
    reason: str
    matched_review_id: int | None = None


def _single_field(body: str, name: str) -> tuple[str | None, bool]:
    pattern = re.compile(
        rf"(?mi)^\s*-\s*{re.escape(name)}\s*:\s*(.*?)\s*$"
    )
    values = [match.group(1).strip() for match in pattern.finditer(body or "")]
    if len(values) != 1:
        return None, False
    return values[0], True


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
        "Review-Role",
        "Implementer-System",
        "Reviewed-Commit",
        "Review-Scope",
        "Independence",
        "Decision",
        "Review-Provenance-Version",
    }
    if not required.issubset(fields):
        return None
    return fields


def _blocking_findings(body: str) -> str | None:
    value, unique = _single_field(body, "Blocking findings")
    return value if unique else None


def _review_rejection(
    review: dict[str, Any], *, required_role: str, implementer: str, head_sha: str
) -> str | None:
    state = str(review.get("state") or "").upper()
    if state not in _ACCEPTED_REVIEW_STATES:
        return "Formal review is not in an accepted submitted state"

    commit_id = review.get("commit_id")
    if commit_id and str(commit_id) != head_sha:
        return "Formal review API commit does not match current head"

    body = str(review.get("body") or "")
    fields = _provenance_fields(body)
    if fields is None:
        return "No valid formal review provenance found"

    if fields["Review-Provenance-Version"] != "1":
        return "Unsupported formal review provenance version"
    if fields["Reviewed-Commit"] != head_sha:
        return "Formal review does not target current head"
    if fields["Implementer-System"] != implementer:
        return "Formal review implementer provenance does not match PR"
    if fields["Decision"] not in _ACCEPTED_DECISIONS:
        return "Formal review decision is not merge-ready evidence"

    blocking = _blocking_findings(body)
    if blocking is None or blocking.casefold() != "none":
        return "Formal review declares blocking findings or lacks a clear none result"

    reviewer = fields["Reviewer-System"]
    role = fields["Review-Role"]
    independence = fields["Independence"]

    if required_role == "independent-review":
        if role != "independent-review":
            return "Independent review role is missing"
        if independence != "DIFFERENT_AGENT" or reviewer == implementer:
            return "Independent review requires a different agent"
    elif required_role == "self-review":
        if role != "self-review":
            return "Self-review role is missing"
        if independence != "SAME_AGENT_SELF_REVIEW" or reviewer != implementer:
            return "Self-review provenance is inconsistent with implementer"

    return None


def evaluate(pr: dict[str, Any], reviews: list[dict[str, Any]]) -> ReadinessResult:
    body = str(pr.get("body") or "")
    required_role, unique_role = _single_field(body, "Required review role")
    if not unique_role or required_role not in _ALLOWED_ROLES:
        return ReadinessResult(False, "Required review role is missing, ambiguous, or invalid")

    if required_role == "none":
        return ReadinessResult(True, "No formal review required by explicit PR classification")

    implementer, unique_implementer = _single_field(body, "Implementer-System")
    if not unique_implementer or not implementer:
        return ReadinessResult(False, "Implementer-System is missing or ambiguous")

    head = pr.get("head") or {}
    head_sha = str(head.get("sha") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        return ReadinessResult(False, "Current head SHA is missing or invalid")

    rejections: list[str] = []
    for candidate in reversed(reviews):
        rejection = _review_rejection(
            candidate,
            required_role=required_role,
            implementer=implementer,
            head_sha=head_sha,
        )
        if rejection is None:
            return ReadinessResult(
                True,
                f"Current-head {required_role} provenance is present",
                candidate.get("id"),
            )
        rejections.append(rejection)

    if not rejections:
        return ReadinessResult(False, f"No formal review satisfies required role {required_role}")
    if len(rejections) == 1:
        return ReadinessResult(False, rejections[0])
    if any("blocking" in reason.casefold() for reason in rejections):
        return ReadinessResult(False, "No acceptable formal review; blocking findings remain")
    if any("current head" in reason.casefold() for reason in rejections):
        return ReadinessResult(False, "No acceptable formal review targets the current head")
    return ReadinessResult(False, f"No formal review satisfies required role {required_role}")


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
