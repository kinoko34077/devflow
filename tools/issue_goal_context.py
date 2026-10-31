"""Source-linked, non-authoritative goal context for GitHub Issue authors.

A trusted author interprets the user's request. This helper validates and
renders the author's structured statement; it never infers intent, approves
work, or modifies GitHub. The owning Issue/specification remains authoritative.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

START = "<!-- DEVFLOW_ISSUE_GOAL_CONTEXT_V1_BEGIN -->"
END = "<!-- DEVFLOW_ISSUE_GOAL_CONTEXT_V1_END -->"
START_V2 = "<!-- DEVFLOW_ISSUE_GOAL_CONTEXT_V2_BEGIN -->"
END_V2 = "<!-- DEVFLOW_ISSUE_GOAL_CONTEXT_V2_END -->"
SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
GOAL_KINDS = frozenset({"explicit", "source_derived", "inferred_hypothesis"})
CONSTRAINT_KINDS = frozenset({"explicit", "accepted_spec"})
SPECIFICATION_AUTHORITIES = frozenset({"explicit", "source_derived", "accepted_spec", "inferred_hypothesis"})
SPECIFICATION_STATES = frozenset({"adopted", "proposed", "unknown", "removed"})
MAX_ITEMS = 16
MAX_RESOLUTION_DEPTH = 16
MAX_SPECIFICATION_VALUE_LENGTH = 8192
MARKERS = ((START, END, 1), (START_V2, END_V2, 2))


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
    if any(marker in result for marker in (START, END, START_V2, END_V2)) or any(
        ord(c) < 32 and c != "\n" for c in result
    ):
        raise GoalContextError(f"{name} contains a reserved marker or control character")
    return result


def _list(value: object, name: str, *, allow_empty: bool = True) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS or (not allow_empty and not value):
        raise GoalContextError(f"{name} must contain 1–{MAX_ITEMS} items" if not allow_empty else f"{name} must be a bounded list")
    return value


def _json_value(value: object, name: str) -> Any:
    """Return a bounded JSON value without truthiness-based coercion."""

    def validate(item: object, depth: int = 0) -> None:
        if depth > 12:
            raise GoalContextError(f"{name} is nested too deeply")
        if type(item) is str:
            if any(marker in item for marker in (START, END, START_V2, END_V2)):
                raise GoalContextError(f"{name} contains a reserved marker")
            return
        if item is None or type(item) in {bool, int}:
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise GoalContextError(f"{name} must use finite JSON numbers")
            return
        if isinstance(item, list):
            if len(item) > 256:
                raise GoalContextError(f"{name} contains too many values")
            for child in item:
                validate(child, depth + 1)
            return
        if isinstance(item, Mapping):
            if len(item) > 256 or any(not isinstance(key, str) for key in item):
                raise GoalContextError(f"{name} objects require bounded string keys")
            for key, child in item.items():
                if any(marker in key for marker in (START, END, START_V2, END_V2)):
                    raise GoalContextError(f"{name} contains a reserved marker")
                validate(child, depth + 1)
            return
        raise GoalContextError(f"{name} must be a JSON value")

    validate(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise GoalContextError(f"{name} must be a JSON value") from exc
    if len(encoded) > MAX_SPECIFICATION_VALUE_LENGTH:
        raise GoalContextError(f"{name} exceeds the bounded JSON value size")
    return json.loads(encoded)


def _normalize_specification(value: object, name: str) -> dict[str, Any]:
    item = _fields(
        value,
        name,
        required={"id", "key", "scope", "state", "authority", "evidence_ref"},
        optional={"value", "supersedes", "reason"},
    )
    claim_id = _text(item["id"], f"{name}.id", limit=120)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", claim_id):
        raise GoalContextError(f"{name}.id must use letters, numbers, dot, underscore or hyphen")
    state = _text(item["state"], f"{name}.state", limit=32)
    authority = _text(item["authority"], f"{name}.authority", limit=32)
    if state not in SPECIFICATION_STATES:
        raise GoalContextError(f"{name}.state is unsupported")
    if authority not in SPECIFICATION_AUTHORITIES:
        raise GoalContextError(f"{name}.authority is unsupported")
    if authority == "inferred_hypothesis" and state != "proposed":
        raise GoalContextError("inferred_hypothesis cannot be adopted")

    has_value = "value" in item
    if state in {"adopted", "proposed"} and not has_value:
        raise GoalContextError(f"{name}.value is required for {state}")
    if state in {"unknown", "removed"} and has_value:
        raise GoalContextError(f"{name}.value must be omitted for {state}; use explicit state instead")
    supersedes = item.get("supersedes")
    if state == "removed" and supersedes is None:
        raise GoalContextError(f"{name}.supersedes is required for removed values")
    if state == "proposed" and supersedes is not None:
        raise GoalContextError(f"{name}.supersedes is not allowed for proposals")
    if supersedes is not None:
        supersedes = _text(supersedes, f"{name}.supersedes", limit=500)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*:[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", supersedes):
            raise GoalContextError(f"{name}.supersedes must identify one source Issue claim")
    reason = item.get("reason")
    if state in {"unknown", "proposed"} and reason is None:
        raise GoalContextError(f"{name}.reason is required for {state}")

    normalized = {
        "id": claim_id,
        "key": _text(item["key"], f"{name}.key", limit=200),
        "scope": _text(item["scope"], f"{name}.scope", limit=200),
        "state": state,
        "authority": authority,
        "evidence_ref": _text(item["evidence_ref"], f"{name}.evidence_ref", limit=500),
    }
    if has_value:
        normalized["value"] = _json_value(item["value"], f"{name}.value")
    if supersedes is not None:
        normalized["supersedes"] = supersedes
    if reason is not None:
        normalized["reason"] = _text(reason, f"{name}.reason", limit=500)
    return normalized


def normalize_goal_context(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an author-supplied projection, NOT the truth of its citations."""

    payload = _fields(value, "goal context", required={"schema_version", "request", "request_ref"},
                      optional={"parent_goal_ref", "higher_goals", "success_conditions", "fixed_constraints", "exclusions",
                                "specifications"})
    version = payload["schema_version"]
    if type(version) is not int or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise GoalContextError("unsupported goal context schema_version")
    if version == 1 and "specifications" in payload:
        raise GoalContextError("schema_version 1 does not support specifications")
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
    result: dict[str, Any] = {"schema_version": version, "request": request, "request_ref": request_ref}
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
    if version == 2 and "specifications" in payload:
        specifications = []
        seen_ids: set[str] = set()
        for i, raw in enumerate(_list(payload["specifications"], "specifications")):
            specification = _normalize_specification(raw, f"specifications[{i}]")
            if specification["id"] in seen_ids:
                raise GoalContextError("specifications contain a duplicate id")
            seen_ids.add(specification["id"])
            specifications.append(specification)
        result["specifications"] = specifications
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
    present = [(start, end, version) for start, end, version in MARKERS if start in body or end in body]
    if not present:
        return None
    if len(present) != 1:
        raise GoalContextError("malformed/duplicate goal marker")
    start_marker, end_marker, marker_version = present[0]
    if body.count(start_marker) != 1 or body.count(end_marker) != 1 or body.index(end_marker) < body.index(start_marker) + len(start_marker):
        raise GoalContextError("malformed/duplicate goal marker")
    raw = body.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()
    try:
        decoded = json.loads(raw, object_pairs_hook=_unique_json_pairs)
    except (ValueError, TypeError) as exc:
        raise GoalContextError("invalid goal context JSON") from exc
    normalized = normalize_goal_context(decoded)
    if normalized["schema_version"] != marker_version:
        raise GoalContextError("goal marker version does not match schema_version")
    return normalized


def upsert_goal_context(body: str, context: Mapping[str, Any]) -> str:
    """Return new Issue prose without changing any non-goal content or authority."""

    old = parse_goal_context(body)
    normalized = normalize_goal_context(context)
    if old is not None and old["schema_version"] > normalized["schema_version"]:
        raise GoalContextError("cannot downgrade a newer goal context schema")
    start_marker, end_marker, _ = MARKERS[normalized["schema_version"] - 1]
    block = start_marker + "\n" + json.dumps(normalized, ensure_ascii=False, indent=2) + "\n" + end_marker
    if old is not None:
        old_start, old_end, _ = next(m for m in MARKERS if m[0] in body or m[1] in body)
        before, rest = body.split(old_start, 1)
        _, after = rest.split(old_end, 1)
        return before + block + after
    return body.rstrip("\n") + "\n\n" + block + "\n"


def _parse_issue_reference(value: str) -> tuple[str, int]:
    text = value.strip()
    match = re.fullmatch(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)", text)
    if match:
        return match.group(1), int(match.group(2))
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError as exc:
        raise GoalContextError("Issue reference is malformed") from exc
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme == "https"
        and parsed.netloc.casefold() == "github.com"
        and not parsed.query
        and not parsed.fragment
        and len(parts) == 4
        and parts[2] == "issues"
        and re.fullmatch(r"[1-9][0-9]*", parts[3])
        and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0])
        and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1])
    ):
        return f"{parts[0]}/{parts[1]}", int(parts[3])
    raise GoalContextError("Issue reference is not a supported GitHub Issue identity")


def _issue_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GoalContextError("Issue reader returned a non-object")
    repository = value.get("repository")
    number = value.get("issue_number")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise GoalContextError("Issue reader returned an invalid repository identity")
    owner, name = repository.split("/", 1)
    if not owner or not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise GoalContextError("Issue reader returned an invalid repository identity")
    if type(number) is not int or number < 1:
        raise GoalContextError("Issue reader returned an invalid issue number")
    canonical_url = f"https://github.com/{repository}/issues/{number}"
    url = value.get("url")
    if url is not None:
        try:
            observed_repository, observed_number = _parse_issue_reference(str(url))
        except GoalContextError as exc:
            raise GoalContextError("Issue reader returned an invalid Issue URL") from exc
        if observed_repository.casefold() != repository.casefold() or observed_number != number:
            raise GoalContextError("Issue reader returned an Issue identity mismatch")
    body = value.get("body")
    if body is not None and not isinstance(body, str):
        raise GoalContextError("Issue body must be text")
    return {"repository": repository, "issue_number": number, "url": canonical_url, "body": body or ""}


def _claim_reference(repository: str, issue_number: int, claim_id: str) -> str:
    return f"{repository}#{issue_number}:{claim_id}"


def _claim_reference_identity(value: str) -> tuple[str, int, str] | None:
    match = re.fullmatch(
        r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*):([A-Za-z0-9][A-Za-z0-9_.-]{0,119})",
        value,
    )
    if not match:
        return None
    return match.group(1).casefold(), int(match.group(2)), match.group(3)


def _same_claim_reference(left: str, right: str) -> bool:
    return _claim_reference_identity(left) == _claim_reference_identity(right)


def _context_projection(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return source context without an unresolved parent pointer."""
    return {key: value for key, value in context.items() if key != "parent_goal_ref"}


def _unknown(reason_code: str, issue_ref: str) -> dict[str, str]:
    return {"issue_ref": issue_ref, "reason_code": reason_code}


def resolve_goal_context(
    issue: Mapping[str, Any],
    fetch_issue: Callable[[str, int], Mapping[str, Any]],
    *,
    max_depth: int = MAX_RESOLUTION_DEPTH,
) -> dict[str, Any]:
    """Resolve source-linked Issue ancestry and typed specifications read-only.

    This follows only explicit GitHub parent references. It never checks the
    semantic truth of citations or promotes a proposal. ``fetch_issue`` must
    be a read-only identity-checking reader returning the normalized Issue
    shape used by DevflowService.get_issue.
    """
    if type(max_depth) is not int or not 1 <= max_depth <= MAX_RESOLUTION_DEPTH:
        raise GoalContextError(f"max_depth must be between 1 and {MAX_RESOLUTION_DEPTH}")
    current = _issue_record(issue)
    chain: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unknowns: list[dict[str, str]] = []
    visited: set[tuple[str, int]] = set()
    resolved_parent_refs: set[tuple[str, int]] = set()

    for _ in range(max_depth):
        current_key = (current["repository"].casefold(), current["issue_number"])
        if current_key in visited:
            unknowns.append(_unknown("PARENT_CYCLE", f"{current['repository']}#{current['issue_number']}"))
            break
        visited.add(current_key)
        issue_ref = f"{current['repository']}#{current['issue_number']}"
        try:
            context = parse_goal_context(current["body"])
        except GoalContextError:
            unknowns.append(_unknown("GOAL_CONTEXT_INVALID", issue_ref))
            break
        if context is None:
            unknowns.append(_unknown("GOAL_CONTEXT_MISSING", issue_ref))
            break
        chain.append((current, context))
        parent_ref = context.get("parent_goal_ref")
        if not parent_ref:
            break
        try:
            parent_repository, parent_number = _parse_issue_reference(parent_ref)
        except GoalContextError:
            unknowns.append(_unknown("PARENT_REF_INVALID", issue_ref))
            break
        parent_key = (parent_repository.casefold(), parent_number)
        if parent_key in visited:
            unknowns.append(_unknown("PARENT_CYCLE", issue_ref))
            break
        if len(chain) >= max_depth:
            unknowns.append(_unknown("PARENT_DEPTH_LIMIT", issue_ref))
            break
        try:
            fetched = fetch_issue(parent_repository, parent_number)
        except Exception:
            # Reader exceptions may include private response details or headers.
            unknowns.append(_unknown("PARENT_UNAVAILABLE", issue_ref))
            break
        try:
            parent = _issue_record(fetched)
        except GoalContextError:
            unknowns.append(_unknown("PARENT_IDENTITY_MISMATCH", issue_ref))
            break
        if (
            parent["repository"].casefold() != parent_repository.casefold()
            or parent["issue_number"] != parent_number
        ):
            unknowns.append(_unknown("PARENT_IDENTITY_MISMATCH", issue_ref))
            break
        resolved_parent_refs.add(current_key)
        current = parent
    else:
        issue_ref = f"{current['repository']}#{current['issue_number']}"
        unknowns.append(_unknown("PARENT_DEPTH_LIMIT", issue_ref))

    parent_chain_status = "PARTIAL_UNKNOWN" if any(
        item["reason_code"].startswith("PARENT_")
        or item["reason_code"] in {"GOAL_CONTEXT_INVALID", "GOAL_CONTEXT_MISSING"}
        for item in unknowns
    ) else "COMPLETE"

    if not chain:
        return {
            "parent_chain_status": "UNKNOWN",
            "coverage": {
                "parent_chain": "UNKNOWN",
                "structured_specifications": "NOT_REPRESENTED",
            },
            "source_contexts": [],
            "specifications": [],
            "effective_specifications": [],
            "proposals": [],
            "unknowns": unknowns,
            "semantic_citation_verification": "NOT_PERFORMED",
        }

    source_contexts = []
    for source_issue, context in reversed(chain):
        issue_ref = f"{source_issue['repository']}#{source_issue['issue_number']}"
        context_projection = _context_projection(context)
        source_key = (source_issue["repository"].casefold(), source_issue["issue_number"])
        if source_key in resolved_parent_refs and context.get("parent_goal_ref"):
            context_projection["parent_goal_ref"] = context["parent_goal_ref"]
        source_contexts.append({
            "issue_ref": issue_ref,
            "url": source_issue["url"],
            "schema_version": context["schema_version"],
            "context": context_projection,
        })

    history: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    effective: dict[tuple[str, str], dict[str, Any]] = {}
    active_claim_refs: dict[tuple[str, str], str | None] = {}

    def add_conflict(
        key: str,
        scope: str,
        source_issue: str,
        refs: list[str],
        *,
        invalid_supersedes_ref: str | None = None,
    ) -> None:
        conflicting_refs = sorted(set(refs))
        for item in history:
            if (
                item["claim_ref"] in conflicting_refs
                and item["key"] == key
                and item["scope"] == scope
            ):
                item["resolution_status"] = "CONFLICTED"
        conflict = {
            "key": key,
            "scope": scope,
            "state": "unknown",
            "reason_code": "CONFLICTING_OVERRIDES",
            "source_issue": source_issue,
            "conflicting_claim_refs": conflicting_refs,
        }
        if invalid_supersedes_ref is not None:
            conflict["invalid_supersedes_ref"] = invalid_supersedes_ref
        effective[(key, scope)] = conflict
        active_claim_refs[(key, scope)] = None
        unknowns.append(_unknown("CONFLICTING_OVERRIDES", source_issue))

    for source_issue, context in reversed(chain):
        issue_ref = f"{source_issue['repository']}#{source_issue['issue_number']}"
        specifications = context.get("specifications", [])
        for claim in specifications:
            key, scope = claim["key"], claim["scope"]
            property_key = (key, scope)
            claim_ref = _claim_reference(source_issue["repository"], source_issue["issue_number"], claim["id"])
            record = {
                **claim,
                "claim_ref": claim_ref,
                "source_issue": issue_ref,
                "resolution_status": "SOURCE_RECORDED",
            }
            history.append(record)

            if claim["state"] == "proposed":
                record["resolution_status"] = "PROPOSED"
                proposals.append(record)
                continue

            existing = effective.get(property_key)
            existing_ref = active_claim_refs.get(property_key)
            if claim.get("supersedes") is not None:
                if existing is None or existing_ref is None or not _same_claim_reference(existing_ref, claim["supersedes"]):
                    record["resolution_status"] = "CONFLICTED"
                    conflict_refs = [claim_ref]
                    if existing_ref:
                        conflict_refs.append(existing_ref)
                    add_conflict(
                        key,
                        scope,
                        issue_ref,
                        conflict_refs,
                        invalid_supersedes_ref=claim["supersedes"],
                    )
                    continue
                prior = next((item for item in history if item["claim_ref"] == existing_ref), None)
                if prior is not None:
                    prior["resolution_status"] = "SUPERSEDED"
                record["resolution_status"] = "EFFECTIVE"
                replacement = {
                    "key": key,
                    "scope": scope,
                    "state": claim["state"],
                    "authority": claim["authority"],
                    "evidence_ref": claim["evidence_ref"],
                    "source_issue": issue_ref,
                    "claim_ref": claim_ref,
                }
                if "value" in claim:
                    replacement["value"] = claim["value"]
                if "reason" in claim:
                    replacement["reason"] = claim["reason"]
                if claim["state"] == "unknown":
                    replacement["reason_code"] = "SOURCE_RECORDED_UNKNOWN"
                    unknowns.append(_unknown("SOURCE_RECORDED_UNKNOWN", issue_ref))
                effective[property_key] = replacement
                active_claim_refs[property_key] = claim_ref
                continue

            if existing is not None:
                record["resolution_status"] = "CONFLICTED"
                existing_ref = active_claim_refs.get(property_key)
                add_conflict(key, scope, issue_ref, [ref for ref in (existing_ref, claim_ref) if ref])
                continue

            record["resolution_status"] = "EFFECTIVE" if claim["state"] != "removed" else "REMOVED"
            replacement = {
                "key": key,
                "scope": scope,
                "state": claim["state"],
                "authority": claim["authority"],
                "evidence_ref": claim["evidence_ref"],
                "source_issue": issue_ref,
                "claim_ref": claim_ref,
            }
            if "value" in claim:
                replacement["value"] = claim["value"]
            if "reason" in claim:
                replacement["reason"] = claim["reason"]
            if claim["state"] == "unknown":
                replacement["reason_code"] = "SOURCE_RECORDED_UNKNOWN"
                unknowns.append(_unknown("SOURCE_RECORDED_UNKNOWN", issue_ref))
            effective[property_key] = replacement
            active_claim_refs[property_key] = claim_ref

    for proposal in proposals:
        property_key = (proposal["key"], proposal["scope"])
        if property_key not in effective:
            effective[property_key] = {
                "key": proposal["key"],
                "scope": proposal["scope"],
                "state": "unknown",
                "reason_code": "NO_ADOPTED_SPECIFICATION",
                "source_issue": proposal["source_issue"],
            }
            active_claim_refs[property_key] = None
            unknowns.append(_unknown("NO_ADOPTED_SPECIFICATION", proposal["source_issue"]))

    if parent_chain_status != "COMPLETE":
        # A visible child assertion cannot be called effective when an unseen
        # ancestor might already define or correct the same scoped property.
        # Keep its authored claim and provenance in `specifications`, while
        # removing the value from the effective projection.
        for property_key, current_value in list(effective.items()):
            reason_code = current_value.get("reason_code")
            if current_value["state"] == "unknown" and reason_code not in {"NO_ADOPTED_SPECIFICATION"}:
                continue
            visible_claims = [
                item for item in history
                if (item["key"], item["scope"]) == property_key
            ]
            visible_refs = sorted(item["claim_ref"] for item in visible_claims)
            for item in visible_claims:
                if item["resolution_status"] in {"EFFECTIVE", "REMOVED"}:
                    item["resolution_status"] = "PENDING_PARENT_UNKNOWN"
            effective[property_key] = {
                "key": property_key[0],
                "scope": property_key[1],
                "state": "unknown",
                "reason_code": "PARENT_CHAIN_INCOMPLETE",
                "source_issue": current_value["source_issue"],
                "visible_claim_refs": visible_refs,
            }
            unknowns.append(_unknown("PARENT_CHAIN_INCOMPLETE", current_value["source_issue"]))

    effective_values = sorted(effective.values(), key=lambda item: (item["key"], item["scope"]))
    coverage = {
        "parent_chain": parent_chain_status,
        "structured_specifications": (
            "PARTIAL_UNKNOWN" if parent_chain_status != "COMPLETE"
            else "RECORDED_CLAIMS_ONLY" if any(context.get("specifications") for _, context in chain)
            else "NOT_REPRESENTED"
        ),
    }
    return {
        "parent_chain_status": parent_chain_status,
        "coverage": coverage,
        "source_contexts": source_contexts,
        "specifications": history,
        "effective_specifications": effective_values,
        "proposals": proposals,
        "unknowns": unknowns,
        "semantic_citation_verification": "NOT_PERFORMED",
    }
