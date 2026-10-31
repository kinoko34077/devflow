"""Source-bound comparison for explicitly declared plan effects.

The comparator checks exact structured values against the existing effective
Goal Context projection. It does not inspect implementation semantics, infer
missing effects, authorize work, or turn unknown input into a task-wide block.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any


PLAN_MARKER_START = "<!-- DEVFLOW_GOAL_PLAN_V1_BEGIN -->"
PLAN_MARKER_END = "<!-- DEVFLOW_GOAL_PLAN_V1_END -->"
TASK_REF = re.compile(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]{0,9})\Z")
ALLOWED_AUTHORITIES = frozenset({"explicit", "source_derived", "accepted_spec"})
MAX_STEPS = 64
MAX_EFFECTS = 128
MAX_TEXT = 1000


class PlanAssessmentError(ValueError):
    """Invalid plan packet; public results redact the invalid field contents."""


def _is_text(value: object, *, limit: int = MAX_TEXT) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _normalize_json_value(value: object, *, depth: int = 0) -> Any:
    if depth > 12:
        raise PlanAssessmentError("PLAN_INVALID")
    if value is None or type(value) in {bool, int, str}:
        normalized = value
    elif type(value) is float and math.isfinite(value):
        normalized = value
    elif isinstance(value, list) and len(value) <= 256:
        normalized = [_normalize_json_value(item, depth=depth + 1) for item in value]
    elif isinstance(value, Mapping) and len(value) <= 256 and all(isinstance(key, str) for key in value):
        normalized = {key: _normalize_json_value(item, depth=depth + 1) for key, item in value.items()}
    else:
        raise PlanAssessmentError("PLAN_INVALID")
    try:
        if len(_canonical(normalized)) > 8_192:
            raise PlanAssessmentError("PLAN_INVALID")
    except (TypeError, ValueError):
        raise PlanAssessmentError("PLAN_INVALID") from None
    return normalized


def _normalize_plan(plan: object) -> dict[str, Any]:
    if not isinstance(plan, Mapping) or set(plan) != {"schema_version", "task_ref", "steps"}:
        raise PlanAssessmentError("PLAN_INVALID")
    if type(plan.get("schema_version")) is not int or plan["schema_version"] != 1:
        raise PlanAssessmentError("PLAN_INVALID")
    task_ref = plan.get("task_ref")
    if not isinstance(task_ref, str) or not TASK_REF.fullmatch(task_ref):
        raise PlanAssessmentError("PLAN_INVALID")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise PlanAssessmentError("PLAN_INVALID")

    step_ids: set[str] = set()
    normalized_steps: list[dict[str, Any]] = []
    effect_count = 0
    for step in steps:
        if not isinstance(step, Mapping) or set(step) - {"id", "intent", "declared_effects"}:
            raise PlanAssessmentError("PLAN_INVALID")
        if not {"id", "intent"} <= set(step):
            raise PlanAssessmentError("PLAN_INVALID")
        step_id, intent = step.get("id"), step.get("intent")
        if not _is_text(step_id, limit=120) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", step_id):
            raise PlanAssessmentError("PLAN_INVALID")
        if step_id in step_ids or not _is_text(intent):
            raise PlanAssessmentError("PLAN_INVALID")
        step_ids.add(step_id)
        raw_effects = step.get("declared_effects", [])
        if not isinstance(raw_effects, list):
            raise PlanAssessmentError("PLAN_INVALID")
        effects = []
        for effect in raw_effects:
            effect_count += 1
            if effect_count > MAX_EFFECTS or not isinstance(effect, Mapping):
                raise PlanAssessmentError("PLAN_INVALID")
            state = effect.get("state")
            if not isinstance(state, str) or state not in {"set", "removed"}:
                raise PlanAssessmentError("PLAN_INVALID")
            required = {"key", "scope", "state"} | ({"value"} if state == "set" else set())
            if set(effect) != required:
                raise PlanAssessmentError("PLAN_INVALID")
            if not _is_text(effect.get("key"), limit=200) or not _is_text(effect.get("scope"), limit=200):
                raise PlanAssessmentError("PLAN_INVALID")
            value = _normalize_json_value(effect["value"]) if state == "set" else None
            effects.append({"key": effect["key"].strip(), "scope": effect["scope"].strip(),
                            "state": state, **({"value": value} if state == "set" else {})})
        normalized_steps.append({"id": step_id, "intent": intent.strip(), "declared_effects": effects})
    normalized = {"schema_version": 1, "task_ref": task_ref, "steps": normalized_steps}
    if len(_canonical(normalized)) > 100_000:
        raise PlanAssessmentError("PLAN_INVALID")
    return normalized


def normalize_plan_packet(plan: object) -> dict[str, Any]:
    """Return the bounded canonical packet before any source read occurs."""
    return _normalize_plan(plan)


def _needs_evidence(reason_code: str, *, task_ref: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "NEEDS_EVIDENCE",
        "reason_code": reason_code,
        "mechanical_conflicts": [],
        "unchecked_effects": [],
        "checked_effect_count": 0,
        "blocks_execution": False,
        "can_authorize_execution": False,
        "asserts_plan_completeness": False,
        "coverage_scope": "DECLARED_EFFECTS_ONLY",
        "semantic_critique": "NOT_PERFORMED",
        "citation_semantics": "NOT_VERIFIED",
        "source_authority": "ASSERTED_IN_SOURCE_NOT_AUTHENTICATED",
        "source_revisions": [],
    }
    if task_ref is not None:
        result["task_ref"] = task_ref
    return result


def assess_plan(effective_context: object, plan: object) -> dict[str, Any]:
    """Compare declared plan effects with complete, adopted exact-scope claims.

    A deterministic conflict requires a source-resolved complete parent chain,
    a unique effective claim for the exact key/scope, an adopted state, and an
    accepted authority. Everything else is returned as unknown/uncovered.
    """
    try:
        candidate = _normalize_plan(plan)
    except PlanAssessmentError:
        return _needs_evidence("PLAN_INVALID")
    task_ref = candidate["task_ref"]
    if not isinstance(effective_context, Mapping):
        return _needs_evidence("GOAL_CONTEXT_INVALID", task_ref=task_ref)
    sources = effective_context.get("source_contexts")
    if not isinstance(sources, list) or not sources or not isinstance(sources[-1], Mapping):
        return _needs_evidence("SOURCE_CONTEXT_MISSING", task_ref=task_ref)
    observed_task_ref = sources[-1].get("issue_ref")
    if not isinstance(observed_task_ref, str) or observed_task_ref.casefold() != task_ref.casefold():
        return _needs_evidence("TASK_REFERENCE_MISMATCH", task_ref=task_ref)

    specifications = effective_context.get("effective_specifications")
    if not isinstance(specifications, list):
        return _needs_evidence("EFFECTIVE_SPECIFICATIONS_MISSING", task_ref=task_ref)
    keyed: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in specifications:
        if not isinstance(item, Mapping) or not _is_text(item.get("key"), limit=200) or not _is_text(item.get("scope"), limit=200):
            return _needs_evidence("EFFECTIVE_SPECIFICATIONS_INVALID", task_ref=task_ref)
        key = (item["key"], item["scope"])
        if key in keyed:
            return _needs_evidence("DUPLICATE_EFFECTIVE_SPECIFICATION", task_ref=task_ref)
        keyed[key] = item

    conflicts: list[dict[str, Any]] = []
    unchecked: list[dict[str, str]] = []
    checked_count = 0
    complete_chain = effective_context.get("parent_chain_status") == "COMPLETE"
    for step in candidate["steps"]:
        for effect in step["declared_effects"]:
            key = (effect["key"], effect["scope"])
            expected = keyed.get(key)
            expected_state = expected.get("state") if expected is not None else None
            expected_authority = expected.get("authority") if expected is not None else None
            if not complete_chain:
                unchecked.append({"step_id": step["id"], "key": key[0], "scope": key[1],
                                  "reason_code": "PARENT_CHAIN_INCOMPLETE"})
                continue
            if (expected is None or not isinstance(expected_state, str)
                    or expected_state not in {"adopted", "removed"}
                    or not isinstance(expected_authority, str)
                    or expected_authority not in ALLOWED_AUTHORITIES
                    or not _is_text(expected.get("claim_ref"))
                    or not _is_text(expected.get("source_issue"))
                    or not _is_text(expected.get("evidence_ref"))
                    or (expected_state == "adopted" and "value" not in expected)):
                unchecked.append({"step_id": step["id"], "key": key[0], "scope": key[1],
                                  "reason_code": "NO_MATCHING_ADOPTED_SPECIFICATION"})
                continue
            expected_plan_state = "set" if expected_state == "adopted" else "removed"
            mismatch = effect["state"] != expected_plan_state
            if not mismatch and effect["state"] == "set":
                try:
                    mismatch = _canonical(effect["value"]) != _canonical(expected.get("value"))
                except (TypeError, ValueError):
                    unchecked.append({"step_id": step["id"], "key": key[0], "scope": key[1],
                                      "reason_code": "EFFECTIVE_VALUE_INVALID"})
                    continue
            if mismatch:
                conflicts.append({
                    "step_id": step["id"],
                    "key": key[0],
                    "scope": key[1],
                    "claim_ref": expected["claim_ref"],
                    "source_issue": expected["source_issue"],
                    "evidence_ref": expected["evidence_ref"],
                    "expected_state": expected_state,
                    "declared_state": effect["state"],
                })
            else:
                checked_count += 1

    status = "CONFLICTS_DETECTED" if conflicts else "NEEDS_EVIDENCE" if unchecked or checked_count == 0 else "NO_DECLARED_CONFLICT"
    revisions = [
        {key: source[key] for key in ("issue_ref", "url", "body_sha256", "source_updated_at") if key in source}
        for source in sources if isinstance(source, Mapping)
    ]
    return {
        "status": status,
        "reason_code": "SOURCE_BOUND_DECLARED_EFFECTS_ONLY",
        "task_ref": task_ref,
        "mechanical_conflicts": conflicts,
        "unchecked_effects": unchecked,
        "checked_effect_count": checked_count,
        "blocks_execution": False,
        "can_authorize_execution": False,
        "asserts_plan_completeness": False,
        "coverage_scope": "DECLARED_EFFECTS_ONLY",
        "semantic_critique": "NOT_PERFORMED",
        "citation_semantics": "NOT_VERIFIED",
        "source_authority": "ASSERTED_IN_SOURCE_NOT_AUTHENTICATED",
        "observed_at": effective_context.get("observed_at"),
        "source_revisions": revisions,
    }


def parse_declared_plan(body: object) -> tuple[str, dict[str, Any] | None]:
    """Read the optional exact plan packet from a GitHub PR description."""
    if not isinstance(body, str):
        return "PLAN_BODY_MISSING", None
    starts, ends = body.count(PLAN_MARKER_START), body.count(PLAN_MARKER_END)
    if starts == 0 and ends == 0:
        return "NO_DECLARED_PLAN", None
    if starts != 1 or ends != 1:
        return "PLAN_MARKERS_INVALID", None
    start = body.index(PLAN_MARKER_START) + len(PLAN_MARKER_START)
    end = body.index(PLAN_MARKER_END)
    if end <= start:
        return "PLAN_MARKERS_INVALID", None
    raw = body[start:end].strip()
    if len(raw) > 100_000:
        return "PLAN_INVALID", None

    try:
        normalized = parse_plan_json(raw)
    except (json.JSONDecodeError, PlanAssessmentError, TypeError, ValueError):
        return "PLAN_INVALID", None
    return "PLAN_DECLARED", normalized


def parse_plan_json(raw: object) -> dict[str, Any]:
    """Parse one bounded plan JSON object with duplicate-key rejection."""
    if not isinstance(raw, str) or len(raw) > 100_000:
        raise PlanAssessmentError("PLAN_INVALID")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PlanAssessmentError("PLAN_INVALID")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise PlanAssessmentError("PLAN_INVALID")

    try:
        packet = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, PlanAssessmentError):
            raise
        raise PlanAssessmentError("PLAN_INVALID") from None
    return _normalize_plan(packet)


def _parse_task_ref(task_ref: str) -> tuple[str, int] | None:
    match = TASK_REF.fullmatch(task_ref) if isinstance(task_ref, str) else None
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}", int(match.group(3))


def fetch_public_issue(repository: str, issue_number: int) -> dict[str, Any]:
    """Read one public GitHub Issue anonymously; never uses a token or redirects off-host."""
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise PlanAssessmentError("SOURCE_UNAVAILABLE")
    if type(issue_number) is not int or issue_number < 1:
        raise PlanAssessmentError("SOURCE_UNAVAILABLE")
    url = f"https://api.github.com/repos/{repository}/issues/{issue_number}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "devflow-source-bound-plan-check/1",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != "api.github.com" or response.status != 200:
                raise PlanAssessmentError("SOURCE_UNAVAILABLE")
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise PlanAssessmentError("SOURCE_UNAVAILABLE")
            payload = json.loads(raw)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TypeError, ValueError):
        raise PlanAssessmentError("SOURCE_UNAVAILABLE") from None
    if (not isinstance(payload, Mapping) or "pull_request" in payload
            or type(payload.get("number")) is not int or payload.get("number") != issue_number):
        raise PlanAssessmentError("SOURCE_IDENTITY_MISMATCH")

    def matches_url(value: object, *, host: str, path: str) -> bool:
        if not isinstance(value, str):
            return False
        try:
            parsed = urllib.parse.urlsplit(value)
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname == host
            and port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path.casefold() == path.casefold()
        )

    expected_repo = f"/repos/{repository}"
    expected_issue_api = f"/repos/{repository}/issues/{issue_number}"
    expected_issue_html = f"/{repository}/issues/{issue_number}"
    if (not matches_url(payload.get("repository_url"), host="api.github.com", path=expected_repo)
            or not matches_url(payload.get("url"), host="api.github.com", path=expected_issue_api)
            or not matches_url(payload.get("html_url"), host="github.com", path=expected_issue_html)):
        raise PlanAssessmentError("SOURCE_IDENTITY_MISMATCH")
    body, updated_at = payload.get("body"), payload.get("updated_at")
    if body is not None and not isinstance(body, str):
        raise PlanAssessmentError("SOURCE_IDENTITY_MISMATCH")
    if updated_at is not None and not isinstance(updated_at, str):
        raise PlanAssessmentError("SOURCE_IDENTITY_MISMATCH")
    return {
        "repository": repository,
        "issue_number": issue_number,
        "title": str(payload.get("title") or ""),
        "state": str(payload.get("state") or ""),
        "url": f"https://github.com/{repository}/issues/{issue_number}",
        "body": body or "",
        "updated_at": updated_at or "",
    }


def assess_issue_plan(task_ref: str, plan: object, fetch_issue=fetch_public_issue) -> dict[str, Any]:
    """Resolve live public source ancestry and apply the shared pure comparator."""
    parsed = _parse_task_ref(task_ref)
    if parsed is None:
        return _needs_evidence("TASK_REFERENCE_INVALID")
    from . import issue_goal_context

    try:
        repository, issue_number = parsed
        issue = fetch_issue(repository, issue_number)
        effective_context = issue_goal_context.resolve_goal_context(issue, fetch_issue)
        from datetime import datetime, timezone
        effective_context["observed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return _needs_evidence("SOURCE_UNAVAILABLE", task_ref=task_ref)
    return assess_plan(effective_context, plan)


def write_action_summary(result: Mapping[str, Any], destination: str | None) -> None:
    """Write sanitized source revision evidence without echoing Issue/plan prose."""
    if not destination:
        return
    observed_at = result.get("observed_at")
    if not isinstance(observed_at, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT[0-9:.+-]+Z", observed_at):
        observed_at = "UNKNOWN"
    lines = [
        "## Declared goal plan assessment",
        "",
        f"- Status: `{result.get('status', 'NEEDS_EVIDENCE')}`",
        f"- Observed at: `{observed_at}`",
        "- Scope: declared effects only; plan completeness, source-author authority, citation truth, and plan semantics not assessed.",
        "- Authority: none; this report does not authorize work or enforce branch protection.",
        "- Source body revisions:",
    ]
    revisions = result.get("source_revisions")
    if isinstance(revisions, list) and revisions:
        for source in revisions:
            if not isinstance(source, Mapping):
                continue
            issue_ref = source.get("issue_ref")
            digest = source.get("body_sha256")
            if isinstance(issue_ref, str) and TASK_REF.fullmatch(issue_ref) and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                lines.append(f"  - `{issue_ref}` body SHA-256 `{digest}`")
    else:
        lines.append("  - `NONE / SOURCE_UNAVAILABLE_OR_UNRESOLVED`")
    with open(destination, "a", encoding="utf-8") as summary_file:
        summary_file.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    """GitHub Actions adapter: assess an optional PR-body declaration anonymously."""
    del argv
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("GOAL_PLAN_CHECK=NEEDS_EVIDENCE EVENT_MISSING")
        return 0
    try:
        with open(event_path, encoding="utf-8") as event_file:
            event = json.load(event_file)
        body = event.get("pull_request", {}).get("body") if isinstance(event, Mapping) else None
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        print("GOAL_PLAN_CHECK=NEEDS_EVIDENCE EVENT_INVALID")
        return 0
    packet_status, plan = parse_declared_plan(body)
    if packet_status == "NO_DECLARED_PLAN":
        print("GOAL_PLAN_CHECK=SKIPPED_NO_DECLARED_PLAN")
        return 0
    if plan is None:
        print(f"GOAL_PLAN_CHECK=NEEDS_EVIDENCE {packet_status}")
        return 0
    result = assess_issue_plan(plan["task_ref"], plan)
    write_action_summary(result, os.environ.get("GITHUB_STEP_SUMMARY"))
    print(f"GOAL_PLAN_CHECK={result['status']} CHECKED={result['checked_effect_count']} "
          f"CONFLICTS={len(result['mechanical_conflicts'])} UNCHECKED={len(result['unchecked_effects'])}")
    if result["status"] == "CONFLICTS_DETECTED":
        print("::error::Declared plan conflicts with an adopted, source-linked Goal Context condition.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
