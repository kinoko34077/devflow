"""Reference classifier for the Chat Worker Bootstrap Contract v1 (devflow#191).

Pure and deterministic: it performs no I/O.  A worker (Codex, Claude or
ChatGPT) gathers live evidence itself, then this module turns the validated
request plus that evidence into exactly one disposition.  The normative
contract is ``docs/spec/CHAT_WORKER_BOOTSTRAP.md``; this module exists so the
contract's examples are executable and provider-neutral by construction.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

REQUEST_SCHEMA = "chat-worker-bootstrap-request.v1"
EVIDENCE_SCHEMA = "chat-worker-bootstrap-evidence.v1"
RESULT_SCHEMA = "chat-worker-bootstrap-result.v1"

WORKER_SYSTEMS = ("codex", "claude", "chatgpt")

DISPOSITIONS = (
    "CLAIM_AND_WORK",
    "REVIEW_WORK",
    "RECOVERY_WORK",
    "NEEDS_HUMAN",
    "WAIT_EXTERNAL",
    "NO_ELIGIBLE_WORK",
    "NEEDS_EVIDENCE",
)

# Stable typed reason vocabulary.  The set is closed for v1; adding a code is
# a contract change.
REASON_CODES = (
    # selection
    "ELIGIBLE_FRESH_CANDIDATE",
    "ELIGIBLE_REVIEW_DEMAND",
    "ELIGIBLE_RECOVERY_DEMAND",
    # non-work outcomes
    "HUMAN_GATE",
    "EXTERNAL_BLOCKER",
    "NO_CANDIDATES_PUBLISHED",
    "ALL_CANDIDATES_OMITTED",
    "REPOSITORY_NOT_ACTIVE",
    # evidence failures
    "REQUEST_INVALID",
    "SCHEMA_UNSUPPORTED",
    "EVIDENCE_INVALID",
    "EVIDENCE_STALE",
    "PORTFOLIO_ENUMERATION_UNAVAILABLE",
    "BOOTSTRAP_UNREAD",
    "CONTROL_NOT_FOUND",
    "CONTROL_DUPLICATE",
    "CONTROL_UNTRUSTED",
    "FRONTIER_UNAVAILABLE",
    "COORDINATOR_STATE_UNAVAILABLE",
    "PROVIDER_SURFACE_MISSING",
)

# Per-candidate omission reasons (never top-level reason codes).
OMISSION_REASONS = (
    "STALE_DIGEST",
    "DEPENDENCY_NOT_READY",
    "LIVE_CLAIM_CONFLICT",
    "CAPABILITY_MISMATCH",
    "ENVIRONMENT_MISMATCH",
    "REVIEWER_INDEPENDENCE_CONFLICT",
    "PUBLISHED_BY_THIS_ATTEMPT",
    "HUMAN_GATE",
    "EXTERNAL_BLOCKER",
    "ROLE_UNSUPPORTED",
    "REPOSITORY_NOT_ACTIVE",
)

NEXT_STEPS = {
    "CLAIM_AND_WORK": "CLAIM_THEN_ACKNOWLEDGE",
    "REVIEW_WORK": "CLAIM_THEN_ACKNOWLEDGE",
    "RECOVERY_WORK": "CLAIM_THEN_ACKNOWLEDGE",
    "NEEDS_HUMAN": "ASK_HUMAN",
    "WAIT_EXTERNAL": "RECHECK_EXTERNAL",
    "NO_ELIGIBLE_WORK": "REFRESH_LATER",
    "NEEDS_EVIDENCE": "RESOLVE_EVIDENCE",
}

# Candidate role -> (disposition, reason, selection precedence).  Finishing
# in-flight work precedes starting new work: recovery, then review, then
# fresh implementation.
ROLE_TRACKS = {
    "recovery": ("RECOVERY_WORK", "ELIGIBLE_RECOVERY_DEMAND", 0),
    "reviewer": ("REVIEW_WORK", "ELIGIBLE_REVIEW_DEMAND", 1),
    "implementer": ("CLAIM_AND_WORK", "ELIGIBLE_FRESH_CANDIDATE", 2),
}

# Provider-local tool surfaces required before any work disposition.  These
# are availability facts about the chat's tools, never capabilities.
REQUIRED_WORK_SURFACES = ("github:read", "github:write", "coordinator:claim")

CLAIMABILITY = ("CLAIMABLE", "BLOCKED_LIVE", "EXPIRED_UNSWEPT")

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TASK_REF = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*$")
_CONTROL_REF = re.compile(r"^kinoko34077/devflow#[1-9][0-9]*$")
_TAG = re.compile(r"^[a-z0-9][a-z0-9_.:/-]{0,63}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
# Metadata must never carry secret material; reject obvious shapes outright.
_SECRET_SHAPE = re.compile(
    r"(ghp_|gho_|ghs_|github_pat_|sk-|xox[abp]-|bearer|token|secret|password|cookie|session_key)",
    re.IGNORECASE,
)


class ContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise ContractError(code, detail)


def _timestamp(value: object, field: str, code: str) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), code, f"{field} must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError(code, f"{field} must be RFC3339 UTC") from exc


def _tags(value: object, field: str, code: str) -> list[str]:
    _require(isinstance(value, list), code, f"{field} must be an array")
    tags: list[str] = []
    for tag in value:
        _require(isinstance(tag, str) and _TAG.fullmatch(tag) is not None, code, f"{field} has a malformed tag")
        _require(_SECRET_SHAPE.search(tag) is None, code, f"{field} must not carry secret material")
        tags.append(tag)
    _require(len(set(tags)) == len(tags), code, f"{field} has duplicate tags")
    return sorted(tags)


REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "target_repository",
        "work_intent",
        "worker_system",
        "worker_session_id",
        "execution_attempt_id",
        "capabilities",
        "environment",
        "tool_surfaces",
        "observed_at",
    }
)


def normalize_request(request: object) -> dict[str, Any]:
    """Validate and normalize a v1 request.  Raises ``ContractError``."""

    _require(isinstance(request, dict), "REQUEST_INVALID", "request must be an object")
    _require(
        request.get("schema_version") == REQUEST_SCHEMA,
        "SCHEMA_UNSUPPORTED",
        "unsupported request schema_version",
    )
    unknown = set(request) - REQUEST_FIELDS
    _require(not unknown, "REQUEST_INVALID", f"unknown request fields: {sorted(unknown)}")
    target = request.get("target_repository")
    _require(
        target is None or (isinstance(target, str) and _REPOSITORY.fullmatch(target) is not None),
        "REQUEST_INVALID",
        "target_repository must be owner/name or null",
    )
    intent = request.get("work_intent")
    _require(
        intent is None or (isinstance(intent, str) and len(intent) <= 500),
        "REQUEST_INVALID",
        "work_intent must be a string of at most 500 characters or null",
    )
    _require(
        request.get("worker_system") in WORKER_SYSTEMS,
        "REQUEST_INVALID",
        "worker_system must be codex, claude or chatgpt",
    )
    for field in ("worker_session_id", "execution_attempt_id"):
        value = request.get(field)
        _require(
            isinstance(value, str) and _IDENTITY.fullmatch(value) is not None,
            "REQUEST_INVALID",
            f"{field} is malformed",
        )
        _require(_SECRET_SHAPE.search(value) is None, "REQUEST_INVALID", f"{field} must not carry secret material")
    return {
        "schema_version": REQUEST_SCHEMA,
        "target_repository": target,
        # Intent is recorded for audit only; it never selects or ranks work.
        "work_intent": intent,
        "worker_system": request["worker_system"],
        "worker_session_id": request["worker_session_id"],
        "execution_attempt_id": request["execution_attempt_id"],
        "capabilities": _tags(request.get("capabilities"), "capabilities", "REQUEST_INVALID"),
        "environment": _tags(request.get("environment"), "environment", "REQUEST_INVALID"),
        "tool_surfaces": _tags(request.get("tool_surfaces"), "tool_surfaces", "REQUEST_INVALID"),
        "observed_at": request.get("observed_at"),
    }


def coordinator_worker_id(request: dict[str, Any]) -> str:
    """Runtime ``worker_id`` used for execution-coordinator claims."""

    return f"{request['worker_system']}:{request['worker_session_id']}"


def _candidate(value: object) -> dict[str, Any]:
    code = "EVIDENCE_INVALID"
    _require(isinstance(value, dict), code, "candidate must be an object")
    _require(isinstance(value.get("task_ref"), str) and _TASK_REF.fullmatch(value["task_ref"]) is not None, code, "candidate task_ref is malformed")
    _require(isinstance(value.get("role"), str), code, "candidate role must be a string")
    _require(isinstance(value.get("action"), str) and value["action"], code, "candidate action must be a string")
    _require(isinstance(value.get("fingerprint"), str) and _FINGERPRINT.fullmatch(value["fingerprint"]) is not None, code, "candidate fingerprint is malformed")
    for flag in ("digest_fresh", "dependency_ready", "human_gate", "external_blocker", "reviewer_independence_conflict", "published_by_this_attempt"):
        _require(type(value.get(flag)) is bool, code, f"candidate {flag} must be boolean")
    _require(value.get("claimability") in CLAIMABILITY, code, "candidate claimability is unknown")
    rank = value.get("rank_key")
    _require(
        isinstance(rank, list)
        and all(
            (isinstance(item, int) and not isinstance(item, bool) and 0 <= item < 10**20)
            or isinstance(item, str)
            for item in rank
        ),
        code,
        "candidate rank_key must be a list of non-negative integers/strings",
    )
    return {
        **value,
        "required_capabilities": _tags(value.get("required_capabilities"), "required_capabilities", code),
        "required_environment": _tags(value.get("required_environment"), "required_environment", code),
    }


def _result(request: dict[str, Any] | None, disposition: str, reason_code: str, *, detail: str | None = None,
            source_refs: list[str] | None = None, selected: dict[str, Any] | None = None,
            omissions: list[dict[str, str]] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "disposition": disposition,
        "worker_session_id": request["worker_session_id"] if request else None,
        "execution_attempt_id": request["execution_attempt_id"] if request else None,
        "target_repository": request["target_repository"] if request else None,
        "task_ref": None,
        "role": None,
        "action": None,
        "source_refs": sorted(set(source_refs or [])),
        "reason_code": reason_code,
        "reason_detail": detail,
        "claim_required": False,
        "claim_candidate_fingerprint": None,
        "coordinator_worker_id": None,
        "omissions": sorted(omissions or [], key=lambda item: (item["task_ref"], item["role"], item["reason"])),
        "next_authoritative_step": NEXT_STEPS[disposition],
    }
    if selected is not None:
        result.update(
            task_ref=selected["task_ref"],
            role=selected["role"],
            action=selected["action"],
            claim_required=True,
            claim_candidate_fingerprint=selected["fingerprint"],
            coordinator_worker_id=coordinator_worker_id(request),
        )
        result["source_refs"] = sorted(set(result["source_refs"]) | {selected["task_ref"]})
    return result


def classify(request: object, evidence: object) -> dict[str, Any]:
    """Return exactly one v1 result for a request and its gathered evidence."""

    try:
        normalized = normalize_request(request)
    except ContractError as error:
        return _result(None, "NEEDS_EVIDENCE", error.code, detail=error.detail)
    try:
        return _classify(normalized, evidence)
    except ContractError as error:
        return _result(normalized, "NEEDS_EVIDENCE", error.code, detail=error.detail)


def _candidate_repository(task_ref: str) -> str:
    return task_ref.rsplit("#", 1)[0]


def _normalized_rank_key(item: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(part).zfill(20) if isinstance(part, int) and not isinstance(part, bool) else part
        for part in item["rank_key"]
    )


def _portfolio_spread_key(request: dict[str, Any], item: dict[str, Any]) -> tuple[str, str, str]:
    material = (
        coordinator_worker_id(request)
        + "\0"
        + item["task_ref"]
        + "\0"
        + request["execution_attempt_id"]
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest(), item["task_ref"], item["role"]


def _classify(request: dict[str, Any], evidence: object) -> dict[str, Any]:
    # 1. Evidence envelope.
    _require(isinstance(evidence, dict), "EVIDENCE_INVALID", "evidence must be an object")
    _require(evidence.get("schema_version") == EVIDENCE_SCHEMA, "SCHEMA_UNSUPPORTED", "unsupported evidence schema_version")
    observed = _timestamp(evidence.get("observed_at"), "evidence observed_at", "EVIDENCE_INVALID")
    fresh_until = _timestamp(evidence.get("fresh_until"), "evidence fresh_until", "EVIDENCE_INVALID")
    request_time = _timestamp(request["observed_at"], "request observed_at", "REQUEST_INVALID")
    _require(fresh_until > observed, "EVIDENCE_INVALID", "fresh_until must be after observed_at")
    _require(observed <= request_time <= fresh_until, "EVIDENCE_STALE", "evidence is not fresh for this request")

    portfolio = request["target_repository"] is None

    # 2. Live bootstrap canon.
    if evidence.get("agents_md_read") is not True:
        return _result(request, "NEEDS_EVIDENCE", "BOOTSTRAP_UNREAD", detail="live devflow/AGENTS.md was not read")

    # 3. Validate Control observations. Repository scope resolves one Control
    # immediately; portfolio scope resolves one exact Control per candidate
    # after the complete frontier has been read.
    controls = evidence.get("controls")
    _require(isinstance(controls, list), "EVIDENCE_INVALID", "controls must be an array")
    for control in controls:
        _require(isinstance(control, dict) and isinstance(control.get("ref"), str) and _CONTROL_REF.fullmatch(control["ref"]) is not None,
                 "EVIDENCE_INVALID", "control ref must be kinoko34077/devflow#N")
        _require(isinstance(control.get("managed_repository"), str), "EVIDENCE_INVALID", "control managed_repository missing")

    refs: list[str] = []
    repo_control: dict[str, Any] | None = None
    if not portfolio:
        matching = [
            control for control in controls
            if control["managed_repository"].casefold() == request["target_repository"].casefold()
            and control.get("state") == "open"
        ]
        refs = [control["ref"] for control in matching]
        if not matching:
            return _result(request, "NEEDS_EVIDENCE", "CONTROL_NOT_FOUND", detail="no open Repository Control for target")
        if len(matching) > 1:
            return _result(request, "NEEDS_EVIDENCE", "CONTROL_DUPLICATE", source_refs=refs,
                           detail="more than one open Repository Control claims the target")
        repo_control = matching[0]
        if repo_control.get("trusted") is not True:
            return _result(request, "NEEDS_EVIDENCE", "CONTROL_UNTRUSTED", source_refs=refs)
        if repo_control.get("repository_state") != "ACTIVE":
            return _result(request, "NO_ELIGIBLE_WORK", "REPOSITORY_NOT_ACTIVE", source_refs=refs)
        if repo_control.get("human_gate") is True:
            return _result(request, "NEEDS_HUMAN", "HUMAN_GATE", source_refs=refs)
        if repo_control.get("external_blocker") is True:
            return _result(request, "WAIT_EXTERNAL", "EXTERNAL_BLOCKER", source_refs=refs)

    # 4. Accepted frontier and runtime state must both be available. For
    # portfolio scope, gatherers set complete=false if any ordinary candidate
    # lacks accepted fresh ranking/requirements metadata; no fallback is used.
    frontier = evidence.get("frontier")
    if not isinstance(frontier, dict) or frontier.get("complete") is not True:
        return _result(request, "NEEDS_EVIDENCE", "FRONTIER_UNAVAILABLE", source_refs=refs)
    if evidence.get("coordinator_state_read") is not True:
        return _result(request, "NEEDS_EVIDENCE", "COORDINATOR_STATE_UNAVAILABLE", source_refs=refs)
    raw_candidates = frontier.get("candidates")
    _require(isinstance(raw_candidates, list), "EVIDENCE_INVALID", "frontier candidates must be an array")
    candidates = [_candidate(item) for item in raw_candidates]
    keys = [(item["task_ref"], item["role"]) for item in candidates]
    _require(len(set(keys)) == len(keys), "EVIDENCE_INVALID", "frontier has duplicate (task, role) candidates")
    if not candidates:
        return _result(request, "NO_ELIGIBLE_WORK", "NO_CANDIDATES_PUBLISHED", source_refs=refs)

    # 5. Hard filters. Portfolio scope applies live Control vetoes per
    # candidate repository so one gated repository does not suppress unrelated
    # eligible work, while missing/duplicate/untrusted Control identity fails
    # the whole cycle closed.
    capabilities = set(request["capabilities"])
    environment = set(request["environment"])
    eligible: list[dict[str, Any]] = []
    omissions: list[dict[str, str]] = []
    portfolio_refs: set[str] = set()
    for item in candidates:
        reason = None
        selected_item = dict(item)
        if portfolio:
            repository = _candidate_repository(item["task_ref"])
            matching = [
                control for control in controls
                if control["managed_repository"].casefold() == repository.casefold()
                and control.get("state") == "open"
            ]
            matching_refs = [control["ref"] for control in matching]
            if not matching:
                return _result(request, "NEEDS_EVIDENCE", "CONTROL_NOT_FOUND",
                               detail=f"no open Repository Control for portfolio candidate {repository}")
            if len(matching) > 1:
                return _result(request, "NEEDS_EVIDENCE", "CONTROL_DUPLICATE", source_refs=matching_refs,
                               detail=f"more than one open Repository Control claims portfolio candidate {repository}")
            control = matching[0]
            if control.get("trusted") is not True:
                return _result(request, "NEEDS_EVIDENCE", "CONTROL_UNTRUSTED", source_refs=matching_refs)
            selected_item["_source_ref"] = control["ref"]
            portfolio_refs.add(control["ref"])
            if control.get("repository_state") != "ACTIVE":
                reason = "REPOSITORY_NOT_ACTIVE"
            elif control.get("human_gate") is True:
                reason = "HUMAN_GATE"
            elif control.get("external_blocker") is True:
                reason = "EXTERNAL_BLOCKER"

        if reason is None:
            if item["role"] not in ROLE_TRACKS:
                reason = "ROLE_UNSUPPORTED"
            elif not item["digest_fresh"]:
                reason = "STALE_DIGEST"
            elif item["human_gate"]:
                reason = "HUMAN_GATE"
            elif item["external_blocker"]:
                reason = "EXTERNAL_BLOCKER"
            elif not item["dependency_ready"]:
                reason = "DEPENDENCY_NOT_READY"
            elif item["claimability"] != "CLAIMABLE":
                reason = "LIVE_CLAIM_CONFLICT"
            elif item["published_by_this_attempt"]:
                reason = "PUBLISHED_BY_THIS_ATTEMPT"
            elif item["role"] == "reviewer" and item["reviewer_independence_conflict"]:
                reason = "REVIEWER_INDEPENDENCE_CONFLICT"
            elif not set(item["required_capabilities"]) <= capabilities:
                reason = "CAPABILITY_MISMATCH"
            elif not set(item["required_environment"]) <= environment:
                reason = "ENVIRONMENT_MISMATCH"
        if reason is None:
            eligible.append(selected_item)
        else:
            omissions.append({"task_ref": item["task_ref"], "role": item["role"], "reason": reason})

    cycle_refs = sorted(portfolio_refs) if portfolio else refs
    if not eligible:
        omitted = {item["reason"] for item in omissions}
        if "HUMAN_GATE" in omitted:
            return _result(request, "NEEDS_HUMAN", "HUMAN_GATE", source_refs=cycle_refs, omissions=omissions)
        if "EXTERNAL_BLOCKER" in omitted:
            return _result(request, "WAIT_EXTERNAL", "EXTERNAL_BLOCKER", source_refs=cycle_refs, omissions=omissions)
        return _result(request, "NO_ELIGIBLE_WORK", "ALL_CANDIDATES_OMITTED", source_refs=cycle_refs, omissions=omissions)

    # 6. Provider-local mutation surface. Checked only once work exists and
    # never used as capability evidence.
    missing = [surface for surface in REQUIRED_WORK_SURFACES if surface not in request["tool_surfaces"]]
    if missing:
        return _result(request, "NEEDS_EVIDENCE", "PROVIDER_SURFACE_MISSING", source_refs=cycle_refs,
                       detail="missing tool surfaces: " + ",".join(missing), omissions=omissions)

    # 7. Selection. Repository scope keeps the accepted v1 lexical behavior.
    # Portfolio scope first fixes the best track + rank class, then spreads
    # workers deterministically inside that class. At most one is returned.
    if portfolio:
        best_track = min(ROLE_TRACKS[item["role"]][2] for item in eligible)
        track_items = [item for item in eligible if ROLE_TRACKS[item["role"]][2] == best_track]
        best_rank = min(_normalized_rank_key(item) for item in track_items)
        rank_class = [item for item in track_items if _normalized_rank_key(item) == best_rank]
        selected = min(rank_class, key=lambda item: _portfolio_spread_key(request, item))
        selected_refs = [selected["_source_ref"]]
    else:
        selected = min(
            eligible,
            key=lambda item: (ROLE_TRACKS[item["role"]][2], _normalized_rank_key(item), item["task_ref"], item["role"]),
        )
        selected_refs = refs
    disposition, reason_code, _ = ROLE_TRACKS[selected["role"]]
    return _result(request, disposition, reason_code, source_refs=selected_refs, selected=selected, omissions=omissions)


RESULT_FIELDS = (
    "schema_version",
    "disposition",
    "worker_session_id",
    "execution_attempt_id",
    "target_repository",
    "task_ref",
    "role",
    "action",
    "source_refs",
    "reason_code",
    "reason_detail",
    "claim_required",
    "claim_candidate_fingerprint",
    "coordinator_worker_id",
    "omissions",
    "next_authoritative_step",
)


def validate_result(result: object) -> None:
    """Check a result against the v1 envelope invariants."""

    _require(isinstance(result, dict), "EVIDENCE_INVALID", "result must be an object")
    _require(tuple(sorted(result)) == tuple(sorted(RESULT_FIELDS)), "EVIDENCE_INVALID", "result fields differ from v1 envelope")
    _require(result["schema_version"] == RESULT_SCHEMA, "SCHEMA_UNSUPPORTED", "result schema_version")
    _require(result["disposition"] in DISPOSITIONS, "EVIDENCE_INVALID", "unknown disposition")
    _require(result["reason_code"] in REASON_CODES, "EVIDENCE_INVALID", "unknown reason_code")
    _require(result["next_authoritative_step"] == NEXT_STEPS[result["disposition"]], "EVIDENCE_INVALID", "next step does not match disposition")
    work = result["disposition"] in ("CLAIM_AND_WORK", "REVIEW_WORK", "RECOVERY_WORK")
    _require(result["claim_required"] is work, "EVIDENCE_INVALID", "claim_required must hold exactly for work dispositions")
    for field in ("task_ref", "role", "action", "claim_candidate_fingerprint", "coordinator_worker_id"):
        _require((result[field] is not None) is work, "EVIDENCE_INVALID", f"{field} must be set exactly for work dispositions")
    for omission in result["omissions"]:
        _require(omission.get("reason") in OMISSION_REASONS, "EVIDENCE_INVALID", "unknown omission reason")
