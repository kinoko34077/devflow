"""Read-only trusted-base evaluator for optional PR outcome declarations.

The evaluator detects contradictions inside a packet supplied by a PR body. It
does not read the linked source, authenticate an author, verify the declared
Issue revision, or prove end-user behavior. No packet means an explicit skip.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    from .acceptance_evidence_preflight import outcome_observation_preflight
except ImportError:  # direct script execution
    from acceptance_evidence_preflight import outcome_observation_preflight

BEGIN = "<!-- DEVFLOW_OUTCOME_OBSERVATION_V1_BEGIN -->"
END = "<!-- DEVFLOW_OUTCOME_OBSERVATION_V1_END -->"
_TASK_REF = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+#[1-9][0-9]*\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BODY = 65_536
_MAX_PACKET = 16_384


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def parse_pr_packet(body: object) -> tuple[str, dict[str, Any] | None]:
    if body is None:
        return "SKIPPED_NO_OUTCOME_PACKET", None
    if not isinstance(body, str) or len(body) > _MAX_BODY:
        return "INVALID_PACKET", None
    if BEGIN not in body and END not in body:
        return "SKIPPED_NO_OUTCOME_PACKET", None
    if body.count(BEGIN) != 1 or body.count(END) != 1:
        return "INVALID_PACKET", None
    start = body.index(BEGIN) + len(BEGIN)
    end = body.index(END)
    if end <= start:
        return "INVALID_PACKET", None
    encoded = body[start:end].strip()
    if not encoded or len(encoded) > _MAX_PACKET:
        return "INVALID_PACKET", None
    try:
        packet = json.loads(encoded, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError):
        return "INVALID_PACKET", None
    return ("PACKET", packet) if isinstance(packet, dict) else ("INVALID_PACKET", None)


def evaluate_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Evaluate internal consistency without claiming source or runtime proof."""
    task_ref = packet.get("task_ref")
    claimed_sha = packet.get("issue_body_sha256")
    if not isinstance(task_ref, str) or not _TASK_REF.fullmatch(task_ref):
        return {
            "status": "NEEDS_EVIDENCE", "reason": "TASK_REF_INVALID",
            "source_verification": "NOT_PERFORMED", "acceptance_satisfied": False,
        }
    if not isinstance(claimed_sha, str) or not _SHA.fullmatch(claimed_sha):
        return {
            "status": "NEEDS_EVIDENCE", "reason": "ISSUE_REVISION_CLAIM_INVALID",
            "source_verification": "NOT_PERFORMED", "acceptance_satisfied": False,
        }
    # The SHA is caller-declared here. Only the shared DevflowService compares
    # it with a live exact Issue read; the workflow has no API permissions.
    return outcome_observation_preflight(
        packet, task_ref=task_ref, observed_issue_body_sha256=claimed_sha,
    )


def evaluate_event(event: object) -> tuple[int, str]:
    if not isinstance(event, dict):
        return 2, "OUTCOME_PILOT=INVALID_EVENT"
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict) or "body" not in pull_request:
        return 2, "OUTCOME_PILOT=INVALID_EVENT"
    body = pull_request["body"]
    parsed, packet = parse_pr_packet(body)
    if parsed == "SKIPPED_NO_OUTCOME_PACKET":
        return 0, parsed
    if parsed != "PACKET" or packet is None:
        return 2, "OUTCOME_PILOT=NEEDS_EVIDENCE reason=INVALID_PACKET"

    result = evaluate_packet(packet)
    status = result.get("status")
    reason = result.get("reason")
    observed_result = result.get("observed_result")
    line = f"OUTCOME_PILOT={status} reason={reason} observed_result={observed_result}"
    if status in {"NEEDS_EVIDENCE", "DECLARED_MISMATCH"}:
        return 1, line
    if status in {"UNKNOWN", "NOT_RUN"}:
        return 0, line
    if status == "DECLARED_ALIGNED" and observed_result == "FAILURE":
        return 1, "OUTCOME_PILOT=DECLARED_FAILURE reason=OBSERVED_FAILURE"
    if status == "DECLARED_ALIGNED":
        return 0, line
    return 2, "OUTCOME_PILOT=INVALID_EVALUATOR_RESULT"


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        print("OUTCOME_PILOT=UNKNOWN reason=EVENT_PATH_UNAVAILABLE")
        return 0
    try:
        raw = Path(event_path).read_text(encoding="utf-8")
        if len(raw) > 1_000_000:
            raise ValueError("EVENT_TOO_LARGE")
        event = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print("OUTCOME_PILOT=UNKNOWN reason=EVENT_UNAVAILABLE")
        return 0
    code, message = evaluate_event(event)
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
