from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = "repository-bootstrap.v1"
START_MARKER = "<!-- repository-bootstrap:v1:start -->"
END_MARKER = "<!-- repository-bootstrap:v1:end -->"
ALLOWED_OWNER = "kinoko34077"
EXCLUDED_REPOSITORIES = frozenset({"pc-files", "pc-files2"})
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
VISIBILITIES = frozenset({"private", "public"})
PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})
RISKS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})
WORK_STATES = frozenset(
    {
        "NEEDS_AUDIT",
        "AUDITED",
        "WORK_ORDER_READY",
        "READY_FOR_IMPLEMENTATION",
        "IMPLEMENTING",
        "AWAITING_REVIEW",
        "BLOCKED",
        "NEEDS_REAUDIT",
        "PARKED",
        "DONE",
    }
)
REPOSITORY_STATES = frozenset(
    {"ACTIVE", "PARKED", "MAINTENANCE", "DEPRECATED", "CANCELLED"}
)
TEMPLATES = frozenset({"minimal"})
REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
ISSUE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class BootstrapError(ValueError):
    """Raised when a repository-bootstrap request is invalid or ambiguous."""


@dataclass(frozen=True)
class RepositorySpec:
    owner: str
    name: str
    description: str
    visibility: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class InitialIssue:
    key: str
    title: str
    body: str
    role: str | None = None


@dataclass(frozen=True)
class BootstrapRequest:
    schema: str
    repository: RepositorySpec
    kind: str
    priority: str
    risk: str
    template: str
    devflow_managed: bool
    readme: str
    specification: str | None
    license: str | None
    issues: tuple[InitialIssue, ...]
    create_control: bool
    work_status: str
    repository_state: str
    next_action: str


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise BootstrapError(f"{field} must be an object")
    return value


def _string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise BootstrapError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise BootstrapError(f"{field} must not be blank")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise BootstrapError(f"{field} must be a boolean")
    return value


def _enum(value: Any, field: str, allowed: frozenset[str]) -> str:
    text = _string(value, field)
    if text not in allowed:
        raise BootstrapError(f"unsupported {field}: {text}")
    return text


def parse_request_body(body: str) -> dict[str, Any]:
    """Extract exactly one repository-bootstrap.v1 JSON block from an Issue body."""
    if not isinstance(body, str):
        raise BootstrapError("Issue body must be a string")
    if body.count(START_MARKER) != 1 or body.count(END_MARKER) != 1:
        raise BootstrapError("Issue body must contain exactly one bootstrap payload block")

    start = body.index(START_MARKER) + len(START_MARKER)
    end = body.index(END_MARKER)
    if end <= start:
        raise BootstrapError("bootstrap payload markers are out of order")

    payload = body[start:end].strip()
    if payload.startswith("```json"):
        payload = payload[len("```json") :].lstrip("\r\n")
        if not payload.endswith("```"):
            raise BootstrapError("bootstrap JSON fence is not closed")
        payload = payload[:-3].rstrip()
    elif payload.startswith("```"):
        payload = payload[3:].lstrip("\r\n")
        if not payload.endswith("```"):
            raise BootstrapError("bootstrap JSON fence is not closed")
        payload = payload[:-3].rstrip()

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BootstrapError(f"bootstrap payload is not valid JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise BootstrapError("bootstrap payload root must be an object")
    return decoded


def normalize_request(raw: Mapping[str, Any], issue_title: str) -> BootstrapRequest:
    if not isinstance(raw, Mapping):
        raise BootstrapError("bootstrap request must be an object")
    schema = _string(raw.get("schema"), "schema")
    if schema != SCHEMA_VERSION:
        raise BootstrapError(f"unsupported schema: {schema}")

    repository = _mapping(raw.get("repository"), "repository")
    owner = _string(repository.get("owner"), "repository.owner")
    if owner != ALLOWED_OWNER:
        raise BootstrapError(f"unsupported repository.owner: {owner}")
    name = _string(repository.get("name"), "repository.name")
    if (
        name in {".", ".."}
        or name != name.strip()
        or REPOSITORY_NAME_RE.fullmatch(name) is None
    ):
        raise BootstrapError("repository.name is invalid")
    expected_title = f"[REPO CREATE] {name}"
    if issue_title != expected_title:
        raise BootstrapError(f"Issue title must be exactly {expected_title!r}")
    description = repository.get("description", "")
    if not isinstance(description, str):
        raise BootstrapError("repository.description must be a string")
    visibility = _enum(
        repository.get("visibility", "private"), "repository.visibility", VISIBILITIES
    )

    classification = _mapping(raw.get("classification"), "classification")
    kind = _string(classification.get("kind"), "classification.kind")
    priority = _enum(classification.get("priority"), "classification.priority", PRIORITIES)
    risk = _enum(classification.get("risk"), "classification.risk", RISKS)

    bootstrap = _mapping(raw.get("bootstrap", {}), "bootstrap")
    template = _enum(bootstrap.get("template", "minimal"), "bootstrap.template", TEMPLATES)
    managed_explicit = "devflow_managed" in bootstrap
    if managed_explicit:
        devflow_managed = _boolean(
            bootstrap.get("devflow_managed"), "bootstrap.devflow_managed"
        )
    else:
        devflow_managed = name not in EXCLUDED_REPOSITORIES
    if name in EXCLUDED_REPOSITORIES and devflow_managed:
        raise BootstrapError(f"repository {name!r} is excluded from devflow management")

    initial = _mapping(raw.get("initial_content", {}), "initial_content")
    readme = initial.get("readme", f"# {name}\n")
    if not isinstance(readme, str):
        raise BootstrapError("initial_content.readme must be a string")
    specification = _optional_string(
        initial.get("specification"), "initial_content.specification"
    )
    license_value = _optional_string(initial.get("license"), "initial_content.license")

    raw_issues = raw.get("issues", [])
    if not isinstance(raw_issues, list):
        raise BootstrapError("issues must be an array")
    issues: list[InitialIssue] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(raw_issues):
        issue = _mapping(item, f"issues[{index}]")
        key = _string(issue.get("key"), f"issues[{index}].key")
        if ISSUE_KEY_RE.fullmatch(key) is None:
            raise BootstrapError(f"issues[{index}].key is invalid")
        if key in seen_keys:
            raise BootstrapError(f"duplicate Issue key: {key}")
        seen_keys.add(key)
        title = _string(issue.get("title"), f"issues[{index}].title")
        body = _string(issue.get("body"), f"issues[{index}].body", allow_empty=True)
        role = _optional_string(issue.get("role"), f"issues[{index}].role")
        issues.append(InitialIssue(key=key, title=title, body=body, role=role))

    devflow = _mapping(raw.get("devflow", {}), "devflow")
    create_control_default = devflow_managed
    create_control = _boolean(
        devflow.get("create_control", create_control_default), "devflow.create_control"
    )
    if create_control and not devflow_managed:
        raise BootstrapError("devflow.create_control requires bootstrap.devflow_managed=true")
    work_status = _enum(
        devflow.get("work_status", "WORK_ORDER_READY"),
        "devflow.work_status",
        WORK_STATES,
    )
    repository_state = _enum(
        devflow.get("repository_state", "ACTIVE"),
        "devflow.repository_state",
        REPOSITORY_STATES,
    )
    next_action = _string(
        devflow.get("next_action", "[SPECIFY] Define the first implementation slice."),
        "devflow.next_action",
    )

    return BootstrapRequest(
        schema=schema,
        repository=RepositorySpec(
            owner=owner,
            name=name,
            description=description,
            visibility=visibility,
        ),
        kind=kind,
        priority=priority,
        risk=risk,
        template=template,
        devflow_managed=devflow_managed,
        readme=readme,
        specification=specification,
        license=license_value,
        issues=tuple(issues),
        create_control=create_control,
        work_status=work_status,
        repository_state=repository_state,
        next_action=next_action,
    )


def is_trusted_association(value: str) -> bool:
    return value in TRUSTED_ASSOCIATIONS
