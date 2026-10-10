"""Pure, fail-closed G1 contract for ChatGPT-to-GitHub dispatch admission.

This module neither authenticates GitHub identity nor makes GitHub calls.
Adapters MUST supply the verified principal and a reviewed, trusted catalog;
ADMITTED is not permission to execute without G2 runtime checks.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

REQUEST_SCHEMA = "dispatch-request.v1"
CATALOG_SCHEMA = "dispatch-catalog.v1"
_ADMITTED = "ADMITTED"
_DENIED = "DENIED"
_HUMAN = "NEEDS_HUMAN"

_ACTOR = re.compile(r"[A-Za-z0-9_.-]{1,39}", re.ASCII)
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", re.ASCII)
_NAME = re.compile(r"[a-z][a-z0-9_.-]{1,63}", re.ASCII)
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,80}", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{40}", re.ASCII)
_REF = re.compile(r"(?:main|master|[a-zA-Z0-9][a-zA-Z0-9._/-]{0,95})", re.ASCII)
_API_EXECUTOR = re.compile(r"github\.[a-z][a-z0-9_.-]{2,95}", re.ASCII)
_WORKFLOW_EXECUTOR = re.compile(r"\.github/workflows/[a-zA-Z0-9_-]+\.ya?ml", re.ASCII)
_KEYS_REQUEST = frozenset({"schema", "request_id", "repository", "action", "ref", "head_sha", "inputs"})
_KEYS_CATALOG = frozenset({"schema", "operator", "actions"})
_KEYS_ENTRY = frozenset({"repository", "backend", "executor", "ref", "effects", "human_gate", "inputs"})
_KEYS_ACTION_ENTRY = _KEYS_ENTRY | frozenset({"reviewed_workflow_sha"})
_INPUT_TYPE_KEYS = {
    "choice": frozenset({"type", "required", "choices"}),
    "boolean": frozenset({"type", "required"}),
    "integer": frozenset({"type", "required", "minimum", "maximum"}),
}


@dataclass(frozen=True)
class Admission:
    status: str
    reason: str
    # These fields describe an admission, not a queued or completed execution.
    request_id: str | None = None
    repository: str | None = None
    action: str | None = None
    backend: str | None = None
    executor: str | None = None
    ref: str | None = None
    head_sha: str | None = None
    # Trusted catalog pin: Git blob SHA of the reviewed workflow, not the request SHA.
    reviewed_workflow_sha: str | None = None


def _matching(value: Any, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _valid_ref(value: Any) -> bool:
    """Reject Git-forbidden branch ref shapes before any offline admission."""
    if not _matching(value, _REF):
        return False
    if ".." in value or "//" in value or value.endswith(("/", ".")):
        return False
    return all(
        component and not component.startswith(".")
        and not component.endswith((".", ".lock"))
        for component in value.split("/")
    )


def _exact_object(value: Any, keys: frozenset[str]) -> bool:
    return type(value) is dict and frozenset(value) == keys


def parse_json_object(text: str, *, max_bytes: int = 8192) -> dict[str, Any]:
    """Decode bounded JSON without accepting duplicate keys or NaN/Infinity."""
    if type(text) is not str:
        raise ValueError("INVALID_JSON_SIZE")
    try:
        encoded_size = len(text.encode("utf-8"))
    except UnicodeError as exc:
        raise ValueError("INVALID_JSON") from exc
    if encoded_size > max_bytes:
        raise ValueError("INVALID_JSON_SIZE")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("DUPLICATE_JSON_KEY")
            obj[key] = value
        return obj

    def reject_constant(_constant: str) -> None:
        raise ValueError("INVALID_JSON_CONSTANT")

    try:
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("INVALID_JSON") from exc
    if type(value) is not dict:
        raise ValueError("INVALID_JSON_OBJECT")
    return value


def _valid_spec(spec: Any) -> bool:
    if type(spec) is not dict or type(spec.get("type")) is not str:
        return False
    kind = spec["type"]
    if kind not in _INPUT_TYPE_KEYS:
        return False
    if frozenset(spec) != _INPUT_TYPE_KEYS[kind] or type(spec["required"]) is not bool:
        return False
    if kind == "choice":
        choices = spec["choices"]
        return (
            type(choices) is list
            and 1 <= len(choices) <= 32
            and all(_matching(v, _NAME) for v in choices)
            and len(set(choices)) == len(choices)
        )
    if kind == "integer":
        return (
            type(spec["minimum"]) is int
            and type(spec["maximum"]) is int
            and -1000000 <= spec["minimum"] <= spec["maximum"] <= 1000000
        )
    return True


def _valid_catalog(catalog: Any) -> bool:
    if not _exact_object(catalog, _KEYS_CATALOG):
        return False
    if catalog["schema"] != CATALOG_SCHEMA or not _matching(catalog["operator"], _ACTOR):
        return False
    actions = catalog["actions"]
    if type(actions) is not dict or not (1 <= len(actions) <= 128):
        return False
    for name, entry in actions.items():
        if not _matching(name, _NAME) or type(entry) is not dict:
            return False
        backend = entry.get("backend")
        if type(backend) is not str or backend not in ("github_api", "github_actions"):
            return False
        required_keys = _KEYS_ACTION_ENTRY if backend == "github_actions" else _KEYS_ENTRY
        if not _exact_object(entry, required_keys):
            return False
        if not _matching(entry["repository"], _REPO) or not _valid_ref(entry["ref"]):
            return False
        executor_re = _API_EXECUTOR if backend == "github_api" else _WORKFLOW_EXECUTOR
        if not _matching(entry["executor"], executor_re):
            return False
        if backend == "github_actions" and not _matching(entry["reviewed_workflow_sha"], _SHA):
            return False
        if entry["effects"] not in ("read", "write") or type(entry["human_gate"]) is not bool:
            return False
        if entry["effects"] == "write" and not entry["human_gate"]:
            return False
        schemas = entry["inputs"]
        if type(schemas) is not dict or len(schemas) > 16:
            return False
        if any(not _matching(k, _NAME) or not _valid_spec(v) for k, v in schemas.items()):
            return False
    return True


def _valid_inputs(inputs: Any, specs: dict[str, Any]) -> bool:
    if type(inputs) is not dict or len(inputs) > 16 or any(type(k) is not str for k in inputs):
        return False
    if not set(inputs).issubset(specs):
        return False
    for key, spec in specs.items():
        if key not in inputs:
            if spec["required"]:
                return False
            continue
        value = inputs[key]
        kind = spec["type"]
        if kind == "choice" and (type(value) is not str or value not in spec["choices"]):
            return False
        if kind == "boolean" and type(value) is not bool:
            return False
        if kind == "integer" and (
            type(value) is not int
            or not spec["minimum"] <= value <= spec["maximum"]
        ):
            return False
    return True


def admit_dispatch(request: Any, catalog: Any, *, verified_actor: str) -> Admission:
    """Determine offline admission only; never performs a GitHub action.

    The catalog must be loaded from a trusted, reviewed commit rather than
    supplied in a chat message, Issue, PR, or untrusted branch. G2 must prove
    actual permissions, immutable head, approval, deduplication and outcome.
    """
    if not _valid_catalog(catalog):
        return Admission(_DENIED, "INVALID_TRUSTED_CATALOG")
    if type(verified_actor) is not str or verified_actor != catalog["operator"]:
        return Admission(_DENIED, "UNTRUSTED_ACTOR")
    if not _exact_object(request, _KEYS_REQUEST) or request["schema"] != REQUEST_SCHEMA:
        return Admission(_DENIED, "INVALID_REQUEST_SCHEMA")
    if not _matching(request["request_id"], _REQUEST_ID):
        return Admission(_DENIED, "INVALID_REQUEST_ID")
    if not _matching(request["repository"], _REPO):
        return Admission(_DENIED, "INVALID_REPOSITORY")
    if not _matching(request["action"], _NAME):
        return Admission(_DENIED, "INVALID_ACTION")
    entry = catalog["actions"].get(request["action"])
    if entry is None:
        return Admission(_DENIED, "UNKNOWN_ACTION")
    if request["repository"] != entry["repository"]:
        return Admission(_DENIED, "REPOSITORY_NOT_ALLOWED")
    if request["ref"] != entry["ref"] or not _matching(request["head_sha"], _SHA):
        return Admission(_DENIED, "REF_OR_HEAD_INVALID")
    if not _valid_inputs(request["inputs"], entry["inputs"]):
        return Admission(_DENIED, "INVALID_INPUTS")

    shared = dict(
        request_id=request["request_id"],
        repository=entry["repository"],
        action=request["action"],
        backend=entry["backend"],
        executor=entry["executor"],
        ref=entry["ref"],
        head_sha=request["head_sha"],
        reviewed_workflow_sha=entry.get("reviewed_workflow_sha"),
    )
    if entry["human_gate"] or entry["effects"] != "read":
        # A claim embedded in the request never constitutes human approval.
        return Admission(_HUMAN, "HUMAN_GATE_REQUIRED", **shared)
    return Admission(_ADMITTED, "POLICY_ADMITTED_NOT_EXECUTED", **shared)
