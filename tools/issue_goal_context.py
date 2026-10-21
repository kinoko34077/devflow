"""Source-linked, non-authoritative goal context for GitHub Issue authors.

A trusted author interprets the user's request. This helper validates and
renders the author's structured statement; it never infers intent, approves
work, or modifies GitHub. The owning Issue/specification remains authoritative.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

START = "<!-- DEVFLOW_ISSUE_GOAL_CONTEXT_V1_BEGIN -->"
END = "<!-- DEVFLOW_ISSUE_GOAL_CONTEXT_V1_END -->"
SCHEMA_VERSION = 1
GOAL_KINDS = frozenset({"explicit", "source_derived", "inferred_hypothesis"})
CONSTRAINT_KINDS = frozenset({"explicit", "accepted_spec"})
MAX_ITEMS = 16


class GoalContextError(ValueError):
    """Malformed goal projection; never repair the owning Issue silently."""


def _fields(value: object, name: str, *, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GoalContextError(f"{name} must be an object")
    result = dict(value)
    unknown = set(result) - required - (optional or set())
    missing = required - set(result)
    if unknown or missing:
        raise GoalContextError(f"{name} has invalid fields (missing={sorted(missing)}, unknown={sorted(unknown)})")
    return result


def _text(value: object, name: str, *, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise GoalContextError(f"{name} must be nonempty text (max {limit})")
    result = value.strip()
    if any(c in result for c in (START, END)) or any(ord(c) < 32 and c != "\n" for c in result):
        raise GoalContextError(f"{name} contains a reserved marker or control character")
    return result


def _list(value: object, name: str, *, allow_empty: bool = True) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS or (not allow_empty and not value):
        raise GoalContextError(f"{name} must contain 1–{MAX_ITEMS} items" if not allow_empty else f"{name} must be a bounded list")
    return value


def normalize_goal_context(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an author-supplied projection, NOT the truth of its citations."""

    payload = _fields(value, "goal context", required={"schema_version", "request", "request_ref"},
                      optional={"parent_goal_ref", "higher_goals", "success_conditions", "fixed_constraints", "exclusions"})
    if type(payload["schema_version"]) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise GoalContextError("unsupported goal context schema_version")
    request = _text(payload["request"], "request", limit=700)
    request_ref = _text(payload["request_ref"], "request_ref", limit=500)
    parent = payload.get("parent_goal_ref")
    parent_ref = None if parent is None else _text(parent, "parent_goal_ref", limit=500)
    goals = []
    for i, raw in enumerate(_list(payload.get("higher_goals", []), "higher_goals")):
        item = _fields(raw, f"higher_goals[{i}]", required={"statement", "kind"}, optional={"evidence_ref", "reason"})
        kind = _text(item["kind"], f"higher_goals[{i}].kind", limit=32)
        if kind not in GOAL_KINDS:
            raise GoalContextError("unsupported higher_goals.kind")
        ref = item.get("evidence_ref")
        if kind != "inferred_hypothesis" and not ref:
            raise GoalContextError("explicit/source_derived goals require evidence_ref")
        reason = item.get("reason")
        if kind == "inferred_hypothesis" and not reason:
            raise GoalContextError("inferred_hypothesis requires a reason, not acceptance")
        normalized = {"statement": _text(item["statement"], f"higher_goals[{i}].statement"), "kind": kind}
        if ref is not None:
            normalized["evidence_ref"] = _text(ref, f"higher_goals[{i}].evidence_ref", limit=500)
        if reason is not None:
            normalized["reason"] = _text(reason, f"higher_goals[{i}].reason", limit=500)
        goals.append(normalized)
    if not goals and not parent_ref:
        raise GoalContextError("at least one higher goal or parent_goal_ref is required")
    if parent_ref and goals:
        raise GoalContextError("parent inheritance must reference the parent, not duplicate its goals")
    constraints = []
    for i, raw in enumerate(_list(payload.get("fixed_constraints", []), "fixed_constraints")):
        item = _fields(raw, f"fixed_constraints[{i}]", required={"statement", "kind", "evidence_ref"})
        kind = _text(item["kind"], f"fixed_constraints[{i}].kind", limit=32)
        if kind not in CONSTRAINT_KINDS:
            raise GoalContextError("only explicit or accepted-spec constraints may be fixed")
        constraints.append({"statement": _text(item["statement"], f"fixed_constraints[{i}].statement"),
                            "kind": kind, "evidence_ref": _text(item["evidence_ref"], f"fixed_constraints[{i}].evidence_ref", limit=500)})
    success = [_text(s, f"success_conditions[{i}]") for i, s in enumerate(_list(payload.get("success_conditions", []), "success_conditions"))]
    exclusions = [_text(s, f"exclusions[{i}]") for i, s in enumerate(_list(payload.get("exclusions", []), "exclusions"))]
    # An inheriting child uses the parent's source-linked success conditions.
    if goals and not success:
        raise GoalContextError("independent goals require at least one observable success condition")
    result: dict[str, Any] = {"schema_version": 1, "request": request, "request_ref": request_ref}
    if parent_ref:
        result["parent_goal_ref"] = parent_ref
    if goals:
        result["higher_goals"] = goals
    if success:
        result["success_conditions"] = success
    if constraints:
        result["fixed_constraints"] = constraints
    if exclusions:
        result["exclusions"] = exclusions
    return result


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise GoalContextError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_goal_context(body: str) -> dict[str, Any] | None:
    """Read one existing marker; malformed/duplicate markers fail closed."""

    if not isinstance(body, str):
        raise GoalContextError("issue body must be text")
    begins, ends = body.count(START), body.count(END)
    if begins == ends == 0:
        return None
    if begins != 1 or ends != 1 or body.index(END) < body.index(START) + len(START):
        raise GoalContextError("malformed/duplicate goal marker")
    raw = body.split(START, 1)[1].split(END, 1)[0].strip()
    try:
        decoded = json.loads(raw, object_pairs_hook=_unique_json_pairs)
    except (ValueError, TypeError) as exc:
        raise GoalContextError("invalid goal context JSON") from exc
    return normalize_goal_context(decoded)


def upsert_goal_context(body: str, context: Mapping[str, Any]) -> str:
    """Return new Issue prose without changing any non-goal content or authority."""

    old = parse_goal_context(body)
    normalized = normalize_goal_context(context)
    block = START + "\n" + json.dumps(normalized, ensure_ascii=False, indent=2) + "\n" + END
    if old is not None:
        before, rest = body.split(START, 1)
        _, after = rest.split(END, 1)
        return before + block + after
    return body.rstrip("\n") + "\n\n" + block + "\n"
