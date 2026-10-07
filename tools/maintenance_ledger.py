from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Mapping


ACTIVE_RUN_BEGIN = "<!-- DEVFLOW_MAINTENANCE_ACTIVE_RUN_V1_BEGIN -->"
ACTIVE_RUN_END = "<!-- DEVFLOW_MAINTENANCE_ACTIVE_RUN_V1_END -->"
RUN_COMMENT_SENTINEL = "<!-- devflow-maintenance-run:v1 -->"

_DEPTHS = frozenset({"CONTROL", "STANDARD", "DEEP"})
_RESULTS = frozenset(
    {"CLEAN", "FINDINGS", "RECONCILED", "BLOCKED", "SUPERSEDED", "NEEDS_REAUDIT"}
)
_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

class MaintenanceLedgerError(ValueError):
    pass


@dataclass(frozen=True)
class ActiveRun:
    repository: str
    run_id: str
    slot_id: str
    generation: int
    catalog_digest: str
    fingerprint: str
    depth: str
    coverage_key: str
    selected_at: str
    publisher_attempt_id: str
    score_breakdown: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ResumeAssessment:
    disposition: str
    reason_code: str
    run_id: str
    replay_completed_checks: bool = False


@dataclass(frozen=True)
class RunRecord:
    repository: str
    run_id: str
    slot_id: str
    generation: int
    lens: str
    depth: str
    fingerprint: str
    result: str
    findings_summary: str
    completed_at: str
    next_eligibility_reason: str | None
    evidence_refs: tuple[str, ...]


def replace_active(value: ActiveRun, **changes: object) -> ActiveRun:
    return replace(value, **changes)


def replace_record(value: RunRecord, **changes: object) -> RunRecord:
    return replace(value, **changes)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MaintenanceLedgerError(f"{field} must be a non-empty string")
    return value.strip()


def _sha(value: object, field: str) -> str:
    text = _string(value, field)
    if _SHA_RE.fullmatch(text) is None:
        raise MaintenanceLedgerError(f"{field} must be canonical sha256")
    return text


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MaintenanceLedgerError(f"{field} must be a positive integer")
    return value


def _utc(value: object, field: str) -> str:
    text = _string(value, field)
    if not text.endswith("Z"):
        raise MaintenanceLedgerError(f"{field} must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise MaintenanceLedgerError(f"{field} must be RFC3339 UTC") from exc
    if parsed.utcoffset() is None:
        raise MaintenanceLedgerError(f"{field} must be timezone aware")
    return text


def _closed(value: object, field: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MaintenanceLedgerError(f"{field} must be an object")
    unknown = sorted(set(value) - keys)
    if unknown:
        raise MaintenanceLedgerError(
            f"{field} has unknown field(s): {', '.join(unknown)}"
        )
    missing = sorted(keys - set(value))
    if missing:
        raise MaintenanceLedgerError(
            f"{field} missing field(s): {', '.join(missing)}"
        )
    return dict(value)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _work_status_line(body: str) -> tuple[list[str], int] | None:
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    matches = [index for index, line in enumerate(lines) if line.strip() == "## Work Status"]
    if not matches:
        return None
    if len(matches) != 1:
        raise MaintenanceLedgerError("Ledger Work Status heading is ambiguous")

    index = matches[0] + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or lines[index].lstrip().startswith("## "):
        raise MaintenanceLedgerError("Ledger Work Status has no scalar value")
    return lines, index


def ledger_work_status(body: str) -> str | None:
    located = _work_status_line(body)
    if located is None:
        return None
    lines, index = located
    value = lines[index].strip()
    if len(value) >= 2 and value[0] == value[-1] == "`":
        value = value[1:-1].strip()
    return value or None


def _replace_work_status(body: str, status: str) -> str:
    located = _work_status_line(body)
    if located is None:
        raise MaintenanceLedgerError("Ledger is missing Work Status")
    lines, index = located
    lines[index] = f"`{status}`"
    newline = "\r\n" if "\r\n" in body else "\n"
    rebuilt = newline.join(lines)
    if body.endswith(("\n", "\r")) and not rebuilt.endswith(newline):
        rebuilt += newline
    return rebuilt


def _active_to_payload(active: ActiveRun) -> dict[str, object]:
    return {
        "repository": active.repository,
        "run_id": active.run_id,
        "slot_id": active.slot_id,
        "generation": active.generation,
        "catalog_digest": active.catalog_digest,
        "fingerprint": active.fingerprint,
        "depth": active.depth,
        "coverage_key": active.coverage_key,
        "selected_at": active.selected_at,
        "publisher_attempt_id": active.publisher_attempt_id,
        "score_breakdown": [
            {"name": name, "value": value}
            for name, value in active.score_breakdown
        ],
    }


def _parse_active_payload(value: object) -> ActiveRun:
    keys = {
        "repository", "run_id", "slot_id", "generation", "catalog_digest",
        "fingerprint", "depth", "coverage_key", "selected_at",
        "publisher_attempt_id", "score_breakdown",
    }
    data = _closed(value, "active run", keys)
    repository = _string(data["repository"], "active run.repository")
    slot_id = _string(data["slot_id"], "active run.slot_id")
    generation = _positive_int(data["generation"], "active run.generation")
    expected_run_id = f"audit:{repository}:{slot_id}:{generation}"
    run_id = _string(data["run_id"], "active run.run_id")
    if run_id != expected_run_id:
        raise MaintenanceLedgerError("active run run_id does not match repository/slot/generation")
    depth = _string(data["depth"], "active run.depth")
    if depth not in _DEPTHS:
        raise MaintenanceLedgerError(f"invalid active run.depth: {depth!r}")
    raw_breakdown = data["score_breakdown"]
    if not isinstance(raw_breakdown, list):
        raise MaintenanceLedgerError("active run.score_breakdown must be an array")
    breakdown: list[tuple[str, int]] = []
    names: set[str] = set()
    for index, item in enumerate(raw_breakdown):
        entry = _closed(
            item,
            f"active run.score_breakdown[{index}]",
            {"name", "value"},
        )
        name = _string(entry["name"], f"active run.score_breakdown[{index}].name")
        value_num = entry["value"]
        if not isinstance(value_num, int) or isinstance(value_num, bool):
            raise MaintenanceLedgerError(
                f"active run.score_breakdown[{index}].value must be an integer"
            )
        if name in names:
            raise MaintenanceLedgerError("active run.score_breakdown has duplicate names")
        names.add(name)
        breakdown.append((name, value_num))
    return ActiveRun(
        repository=repository,
        run_id=run_id,
        slot_id=slot_id,
        generation=generation,
        catalog_digest=_sha(data["catalog_digest"], "active run.catalog_digest"),
        fingerprint=_sha(data["fingerprint"], "active run.fingerprint"),
        depth=depth,
        coverage_key=_string(data["coverage_key"], "active run.coverage_key"),
        selected_at=_utc(data["selected_at"], "active run.selected_at"),
        publisher_attempt_id=_string(
            data["publisher_attempt_id"],
            "active run.publisher_attempt_id",
        ),
        score_breakdown=tuple(breakdown),
    )


def render_active_run(active: ActiveRun) -> str:
    parsed = _parse_active_payload(_active_to_payload(active))
    return (
        ACTIVE_RUN_BEGIN
        + "\n"
        + _canonical(_active_to_payload(parsed))
        + "\n"
        + ACTIVE_RUN_END
    )


def _extract_active_without_status(body: str) -> ActiveRun | None:
    starts = body.count(ACTIVE_RUN_BEGIN)
    ends = body.count(ACTIVE_RUN_END)
    if starts == 0 and ends == 0:
        return None
    if starts != 1 or ends != 1:
        raise MaintenanceLedgerError("active run marker is missing or ambiguous")
    start = body.index(ACTIVE_RUN_BEGIN) + len(ACTIVE_RUN_BEGIN)
    end = body.index(ACTIVE_RUN_END)
    if end <= start:
        raise MaintenanceLedgerError("active run marker order is invalid")
    raw = body[start:end].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MaintenanceLedgerError("active run payload is not canonical JSON") from exc
    return _parse_active_payload(payload)


def extract_active_run(body: str, repository: str) -> ActiveRun | None:
    active = _extract_active_without_status(body)
    status = ledger_work_status(body)
    if active is None:
        if status == "READY_FOR_IMPLEMENTATION":
            raise MaintenanceLedgerError(
                "READY_FOR_IMPLEMENTATION Ledger requires an active run"
            )
        return None
    if active.repository != repository:
        raise MaintenanceLedgerError("active run repository mismatch")
    if status != "READY_FOR_IMPLEMENTATION":
        raise MaintenanceLedgerError(
            "active run requires Work Status READY_FOR_IMPLEMENTATION"
        )
    return active


def _remove_active_block(body: str) -> str:
    starts = body.count(ACTIVE_RUN_BEGIN)
    ends = body.count(ACTIVE_RUN_END)
    if starts == 0 and ends == 0:
        return body
    if starts != 1 or ends != 1:
        raise MaintenanceLedgerError("active run marker is missing or ambiguous")
    start = body.index(ACTIVE_RUN_BEGIN)
    end = body.index(ACTIVE_RUN_END) + len(ACTIVE_RUN_END)
    if end <= start:
        raise MaintenanceLedgerError("active run marker order is invalid")
    before = body[:start].rstrip()
    after = body[end:].lstrip()
    if before and after:
        return before + "\n\n" + after
    if before:
        return before + "\n"
    return after


def replace_active_run(
    body: str,
    active: ActiveRun | None,
) -> tuple[str, bool]:
    current = _extract_active_without_status(body)
    status = ledger_work_status(body)
    if active is None and current is None:
        if status == "READY_FOR_IMPLEMENTATION":
            raise MaintenanceLedgerError(
                "READY_FOR_IMPLEMENTATION Ledger requires an active run"
            )
        return body, False
    if active is not None and current == active and status == "READY_FOR_IMPLEMENTATION":
        return body, False

    edited = _remove_active_block(body)
    if active is None:
        edited = _replace_work_status(edited, "AUDITED")
    else:
        block = render_active_run(active)
        edited = _replace_work_status(edited, "READY_FOR_IMPLEMENTATION").rstrip()
        edited += "\n\n" + block + "\n"
    return edited, edited != body


def _record_to_payload(record: RunRecord) -> dict[str, object]:
    return {
        "repository": record.repository,
        "run_id": record.run_id,
        "slot_id": record.slot_id,
        "generation": record.generation,
        "lens": record.lens,
        "depth": record.depth,
        "fingerprint": record.fingerprint,
        "result": record.result,
        "findings_summary": record.findings_summary,
        "completed_at": record.completed_at,
        "next_eligibility_reason": record.next_eligibility_reason,
        "evidence_refs": list(record.evidence_refs),
    }


def _parse_record_payload(value: object) -> RunRecord:
    keys = {
        "repository", "run_id", "slot_id", "generation", "lens", "depth",
        "fingerprint", "result", "findings_summary", "completed_at",
        "next_eligibility_reason", "evidence_refs",
    }
    data = _closed(value, "run record", keys)
    repository = _string(data["repository"], "run record.repository")
    slot_id = _string(data["slot_id"], "run record.slot_id")
    generation = _positive_int(data["generation"], "run record.generation")
    run_id = _string(data["run_id"], "run record.run_id")
    if run_id != f"audit:{repository}:{slot_id}:{generation}":
        raise MaintenanceLedgerError("run record run_id does not match repository/slot/generation")
    depth = _string(data["depth"], "run record.depth")
    if depth not in _DEPTHS:
        raise MaintenanceLedgerError(f"invalid run record.depth: {depth!r}")
    result = _string(data["result"], "run record.result")
    if result not in _RESULTS:
        raise MaintenanceLedgerError(f"invalid run record.result: {result!r}")
    next_reason = data["next_eligibility_reason"]
    if next_reason is not None:
        next_reason = _string(next_reason, "run record.next_eligibility_reason")
    evidence = data["evidence_refs"]
    if not isinstance(evidence, list) or not all(
        isinstance(item, str) and item for item in evidence
    ):
        raise MaintenanceLedgerError("run record.evidence_refs must be an array of strings")
    return RunRecord(
        repository=repository,
        run_id=run_id,
        slot_id=slot_id,
        generation=generation,
        lens=_string(data["lens"], "run record.lens"),
        depth=depth,
        fingerprint=_sha(data["fingerprint"], "run record.fingerprint"),
        result=result,
        findings_summary=(
            data["findings_summary"]
            if isinstance(data["findings_summary"], str)
            else _string(data["findings_summary"], "run record.findings_summary")
        ),
        completed_at=_utc(data["completed_at"], "run record.completed_at"),
        next_eligibility_reason=next_reason,
        evidence_refs=tuple(evidence),
    )


def render_run_comment(record: RunRecord) -> str:
    parsed = _parse_record_payload(_record_to_payload(record))
    return (
        RUN_COMMENT_SENTINEL
        + "\n\n# Maintenance Audit Run\n\n```json\n"
        + _canonical(_record_to_payload(parsed))
        + "\n```"
    )


def parse_run_comment(body: str) -> RunRecord | None:
    count = body.count(RUN_COMMENT_SENTINEL)
    if count == 0:
        return None
    if count != 1:
        raise MaintenanceLedgerError("run comment sentinel is ambiguous")
    pattern = re.compile(
        re.escape(RUN_COMMENT_SENTINEL)
        + r"\s*# Maintenance Audit Run\s*```json\s*(\{.*\})\s*```\s*\Z",
        re.DOTALL,
    )
    match = pattern.fullmatch(body.strip())
    if match is None:
        raise MaintenanceLedgerError("run comment format is malformed")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise MaintenanceLedgerError("run comment payload is not JSON") from exc
    return _parse_record_payload(payload)


def next_generation(
    history: tuple[RunRecord, ...],
    repository: str,
    slot_id: str,
) -> int:
    values = [
        item.generation
        for item in history
        if item.repository == repository and item.slot_id == slot_id
    ]
    return (max(values) + 1) if values else 1



def complete_run(
    active: ActiveRun,
    result: Mapping[str, object],
) -> RunRecord:
    if not isinstance(result, Mapping):
        raise MaintenanceLedgerError("completion result must be an object")
    required = {
        "lens",
        "result",
        "findings_summary",
        "completed_at",
        "next_eligibility_reason",
        "evidence_refs",
    }
    unknown = sorted(set(result) - required)
    missing = sorted(required - set(result))
    if unknown:
        raise MaintenanceLedgerError(
            f"completion result has unknown field(s): {', '.join(unknown)}"
        )
    if missing:
        raise MaintenanceLedgerError(
            f"completion result missing field(s): {', '.join(missing)}"
        )
    refs = result["evidence_refs"]
    if not isinstance(refs, (list, tuple)):
        raise MaintenanceLedgerError(
            "completion result.evidence_refs must be an array"
        )
    payload = {
        "repository": active.repository,
        "run_id": active.run_id,
        "slot_id": active.slot_id,
        "generation": active.generation,
        "lens": result["lens"],
        "depth": active.depth,
        "fingerprint": active.fingerprint,
        "result": result["result"],
        "findings_summary": result["findings_summary"],
        "completed_at": result["completed_at"],
        "next_eligibility_reason": result["next_eligibility_reason"],
        "evidence_refs": list(refs),
    }
    return _parse_record_payload(payload)


def assess_run_continuation(
    active: ActiveRun,
    *,
    mutation_required: bool = False,
    blocker: bool = False,
    handoff_required: bool = False,
    independent_acceptance: bool = False,
    durable_finding: bool = False,
) -> str:
    for field, value in (
        ("mutation_required", mutation_required),
        ("blocker", blocker),
        ("handoff_required", handoff_required),
        ("independent_acceptance", independent_acceptance),
        ("durable_finding", durable_finding),
    ):
        if type(value) is not bool:
            raise MaintenanceLedgerError(f"{field} must be boolean")
    if (
        active.depth == "DEEP"
        or mutation_required
        or blocker
        or handoff_required
        or independent_acceptance
        or durable_finding
    ):
        return "PROMOTE_REQUIRED"
    return "CONTINUE"


def assess_active_run_for_resume(
    active: ActiveRun,
    *,
    current_fingerprint: str | None,
    current_catalog_digest: str | None,
    volatile_evidence_complete: bool,
) -> ResumeAssessment:
    if type(volatile_evidence_complete) is not bool:
        raise MaintenanceLedgerError(
            "volatile_evidence_complete must be boolean"
        )
    if (
        not volatile_evidence_complete
        or current_fingerprint is None
        or current_catalog_digest is None
    ):
        return ResumeAssessment(
            disposition="NEEDS_EVIDENCE",
            reason_code="VOLATILE_EVIDENCE_INCOMPLETE",
            run_id=active.run_id,
            replay_completed_checks=False,
        )

    fingerprint = _sha(
        current_fingerprint,
        "current_fingerprint",
    )
    catalog_digest = _sha(
        current_catalog_digest,
        "current_catalog_digest",
    )
    if catalog_digest != active.catalog_digest:
        return ResumeAssessment(
            disposition="SUPERSEDE",
            reason_code="CATALOG_DRIFT",
            run_id=active.run_id,
            replay_completed_checks=False,
        )
    if fingerprint != active.fingerprint:
        return ResumeAssessment(
            disposition="SUPERSEDE",
            reason_code="FINGERPRINT_DRIFT",
            run_id=active.run_id,
            replay_completed_checks=False,
        )
    return ResumeAssessment(
        disposition="RESUME",
        reason_code="EVIDENCE_STILL_CURRENT",
        run_id=active.run_id,
        replay_completed_checks=False,
    )
