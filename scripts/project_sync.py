#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from tools import devflow_mcp_core, github_issue_trust, workflow_contract
except ImportError:  # direct script execution
    _TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
    if str(_TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(_TOOLS_DIR))
    import devflow_mcp_core
    import github_issue_trust
    import workflow_contract

WORKFLOW_CONTRACT = workflow_contract.WORKFLOW_CONTRACT

PROJECT_OWNER = "kinoko34077"
PROJECT_NUMBER = 1
PROJECT_TITLE = "KiNoTch. Development Control"
DEFAULT_REPOSITORY = "kinoko34077/devflow"
HEALTH_TITLE = "[SYSTEM] GitHub Project Sync Health"
HEALTH_FAILURE_STATE_MARKER = "<!-- devflow-project-sync-health-state:v1 -->"
EXCLUDED_REPOSITORIES = set(WORKFLOW_CONTRACT.excluded_repositories)

FIELD_MAP = {
    "Work Status": "Status",
    "Repository State": "Repository State",
    "Priority": "Priority",
    "Risk": "Risk",
    "Type": "Work Type",
    "Repository": "Managed Repository",
    "Next Action": "Next Action",
    "Audit SHA": "Audit SHA",
    "Audit Ref": "Audit Ref",
    "Last Audit At": "Last Audit",
    "Audit Depth": "Audit Depth",
    "Audit Scope": "Audit Scope",
    "Audit Evidence": "Audit Evidence",
    "Last Deep Audit At": "Last Deep Audit",
}
# WAIT is the accepted Repository Control-only source-state exception from devflow#162.
# It is not a general Work Status. Map it only at the Project display boundary:
# the source Control remains WAIT while the existing Project Status option is PARKED.
PROJECT_STATUS_ALIASES = {
    WORKFLOW_CONTRACT.control_wait_state: WORKFLOW_CONTRACT.control_wait_project_status
}

SELECT_OPTIONS = {
    "Status": set(WORKFLOW_CONTRACT.work_states),
    "Repository State": set(WORKFLOW_CONTRACT.repository_states),
    "Priority": set(WORKFLOW_CONTRACT.priorities),
    "Risk": set(WORKFLOW_CONTRACT.risks),
    "Work Type": set(WORKFLOW_CONTRACT.types),
    "Audit Depth": set(WORKFLOW_CONTRACT.audit_depths),
    "Audit Freshness": set(WORKFLOW_CONTRACT.audit_freshness_values),
}
TEXT_FIELDS = {"Managed Repository", "Next Action", "Audit SHA", "Audit Ref", "Audit Scope", "Audit Evidence"}
DATE_FIELDS = {"Last Audit", "Last Deep Audit"}
EXPECTED_FIELDS = set(SELECT_OPTIONS) | TEXT_FIELDS | DATE_FIELDS

AUDIT_PROJECT_FIELD_SPECS = {
    "Audit Ref": {"kind": "text", "options": []},
    "Last Audit": {"kind": "date", "options": []},
    "Audit Depth": {"kind": "single", "options": [
        {"name": "CONTROL", "color": "GRAY", "description": "Control/state consistency audit"},
        {"name": "STANDARD", "color": "BLUE", "description": "Repository-local standard audit"},
        {"name": "DEEP", "color": "PURPLE", "description": "Broad repository-local deep audit"},
    ]},
    "Audit Scope": {"kind": "text", "options": []},
    "Audit Evidence": {"kind": "text", "options": []},
    "Last Deep Audit": {"kind": "date", "options": []},
    "Audit Freshness": {"kind": "single", "options": [
        {"name": "CURRENT", "color": "GREEN", "description": "Audit SHA matches Audit Ref HEAD"},
        {"name": "DRIFTED", "color": "YELLOW", "description": "Audit Ref HEAD advanced past Audit SHA"},
        {"name": "UNKNOWN", "color": "GRAY", "description": "Audit Ref or exact head cannot be established"},
    ]},
}

CONTROL_PREFIX = "[REPO] "
AUDIT_FRESHNESS_LABELS = {
    "CURRENT": "devflow:audit-freshness:current",
    "DRIFTED": "devflow:audit-freshness:drifted",
    "UNKNOWN": "devflow:audit-freshness:unknown",
}
AUDIT_FRESHNESS_LABEL_SPECS = {
    "devflow:audit-freshness:current": {
        "color": "2DA44E",
        "description": "Machine-owned non-canonical Audit Freshness projection: CURRENT",
    },
    "devflow:audit-freshness:drifted": {
        "color": "BF8700",
        "description": "Machine-owned non-canonical Audit Freshness projection: DRIFTED",
    },
    "devflow:audit-freshness:unknown": {
        "color": "6E7781",
        "description": "Machine-owned non-canonical Audit Freshness projection: UNKNOWN",
    },
}



class SyncError(RuntimeError):
    pass


class ConfigError(SyncError):
    pass


class APIError(SyncError):
    pass


def _strip_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        if len(lines) >= 3:
            value = "\n".join(lines[1:-1]).strip()
    if len(value) >= 2 and value[0] == value[-1] == "`":
        value = value[1:-1].strip()
    return value


def parse_sections(body: str, *, reject_duplicates: set[str] | None = None) -> dict[str, str]:
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        m = re.match(r"^## ([^#].*?)\s*$", line)
        if m:
            current = m.group(1).strip()
            if reject_duplicates and current in reject_duplicates and current in sections:
                raise ConfigError(f"duplicate canonical section in Project sync input: {current}")
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: _strip_scalar("\n".join(value)) for name, value in sections.items()}


def _project_date(value: str, section: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ConfigError(f"invalid {section}: expected ISO date/time") from exc


def desired_project_fields(issue: dict[str, Any]) -> dict[str, str]:
    sections = parse_sections(
        str(issue.get("body") or ""),
        reject_duplicates=set(FIELD_MAP),
    )
    if _is_repository_control(issue):
        try:
            WORKFLOW_CONTRACT.validate_repository_control_sections(sections)
        except workflow_contract.WorkflowContractError as exc:
            raise ConfigError(str(exc)) from exc
    desired: dict[str, str] = {}
    for section, field in FIELD_MAP.items():
        value = sections.get(section, "").strip()
        if section == "Work Status":
            value = PROJECT_STATUS_ALIASES.get(value, value)
        if section in {"Last Audit At", "Last Deep Audit At"} and value:
            value = _project_date(value, section)
        if value:
            desired[field] = value
    if str(issue.get("state", "")).lower() == "closed":
        desired["Status"] = "DONE"
    return desired


def derive_audit_freshness(
    issue: dict[str, Any],
    head_resolver: Callable[[str, str], str] | None,
) -> str | None:
    sections = parse_sections(str(issue.get("body") or ""))
    repository = sections.get("Repository", "").strip().strip("`")
    audit_sha = sections.get("Audit SHA", "").strip().strip("`")
    audit_ref = sections.get("Audit Ref", "").strip().strip("`")
    if not audit_sha:
        return None
    if (
        not repository
        or "/" not in repository
        or not re.fullmatch(r"[0-9a-fA-F]{40}", audit_sha)
        or not audit_ref
        or head_resolver is None
    ):
        return "UNKNOWN"
    try:
        current = head_resolver(repository, audit_ref)
    except Exception:
        return "UNKNOWN"
    if not isinstance(current, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", current):
        return "UNKNOWN"
    return "CURRENT" if current.lower() == audit_sha.lower() else "DRIFTED"



@dataclasses.dataclass(frozen=True)
class AuditFreshnessLabelPlan:
    status: str
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


def _issue_label_names(issue: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for value in issue.get("labels") or []:
        if isinstance(value, str):
            name = value.strip()
        elif isinstance(value, dict):
            name = str(value.get("name") or "").strip()
        else:
            name = ""
        if name:
            names.append(name)
    return tuple(names)


def _is_repository_control(issue: dict[str, Any]) -> bool:
    title = str(issue.get("title") or "").strip()
    return title.startswith(CONTROL_PREFIX) and bool(title[len(CONTROL_PREFIX):].strip())


def plan_audit_freshness_label_projection(
    issue: dict[str, Any],
    freshness: str | None,
) -> AuditFreshnessLabelPlan:
    if not _is_repository_control(issue) or freshness is None:
        return AuditFreshnessLabelPlan("NOT_APPLICABLE")
    desired = AUDIT_FRESHNESS_LABELS.get(freshness)
    if desired is None:
        raise ConfigError(f"invalid Audit Freshness projection: {freshness!r}")
    machine_labels = tuple(
        name for name in _issue_label_names(issue)
        if name in AUDIT_FRESHNESS_LABEL_SPECS
    )
    if len(machine_labels) == 1 and machine_labels[0] == desired:
        return AuditFreshnessLabelPlan("MATCH")
    remove = tuple(sorted({name for name in machine_labels if name != desired}))
    add = () if desired in machine_labels else (desired,)
    return AuditFreshnessLabelPlan("DRIFT", add=add, remove=remove)


def sync_audit_freshness_label_projection(
    issue: dict[str, Any],
    freshness: str | None,
    rest: Any | None,
    mode: str,
) -> dict[str, Any]:
    plan = plan_audit_freshness_label_projection(issue, freshness)
    if plan.status != "DRIFT" or mode not in {"reconcile", "event-sync"}:
        return {"status": plan.status, "mutations": 0}

    if rest is None:
        raise ConfigError("repository token is required for Audit Freshness label projection")

    issue_number = int(issue.get("number") or 0)
    if issue_number <= 0:
        raise ConfigError("Repository Control has no valid issue number")

    mutations = 0
    for label in plan.remove:
        rest.remove_issue_label(issue_number, label)
        mutations += 1
    if plan.add:
        rest.add_issue_labels(issue_number, list(plan.add))
        mutations += 1

    # Keep the in-memory event issue coherent for the immediate post-write verify.
    unrelated = [
        name for name in _issue_label_names(issue)
        if name not in AUDIT_FRESHNESS_LABEL_SPECS
    ]
    desired = AUDIT_FRESHNESS_LABELS.get(freshness or "")
    issue["labels"] = [{"name": name} for name in unrelated + ([desired] if desired else [])]
    return {"status": "REPAIRED", "mutations": mutations}


def ensure_audit_freshness_labels(rest: Any) -> int:
    existing = {
        str(item.get("name") or "").strip()
        for item in rest.list_labels()
        if isinstance(item, dict)
    }
    mutations = 0
    for name, spec in AUDIT_FRESHNESS_LABEL_SPECS.items():
        if name in existing:
            continue
        rest.create_label(name, str(spec["color"]), str(spec["description"]))
        mutations += 1
    return mutations

def validate_select_values(fields: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for field, allowed in SELECT_OPTIONS.items():
        if field in fields and fields[field] not in allowed:
            errors.append(f"invalid {field}: {fields[field]!r}")
    return errors


def require_unique_named(nodes: Iterable[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [node for node in nodes if str(node.get("name", "")).strip() == name]
    if len(matches) != 1:
        raise ConfigError(f"expected exactly one field named {name!r}, found {len(matches)}")
    return matches[0]


def require_option(field: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [opt for opt in field.get("options", []) if str(opt.get("name", "")).strip() == name]
    if len(matches) != 1:
        raise ConfigError(f"expected exactly one option {name!r} in {field.get('name')!r}, found {len(matches)}")
    return matches[0]


def collect_connection(fetch_page: Callable[[str | None], dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str | None] = set()
    while True:
        if cursor in seen:
            raise ConfigError("pagination cursor loop detected")
        seen.add(cursor)
        connection = fetch_page(cursor)
        nodes.extend(connection.get("nodes") or [])
        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return nodes
        cursor = page.get("endCursor")
        if not cursor:
            raise ConfigError("pagination reports next page without cursor")


def compare_fields(desired: dict[str, str], current: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in sorted(set(desired) | set(current)):
        if field not in desired:
            result[field] = "NOT_APPLICABLE"
        elif current.get(field) == desired[field]:
            result[field] = "MATCH"
        else:
            result[field] = "DRIFT"
    return result


def plan_field_mutations(desired: dict[str, str], current: dict[str, str]) -> dict[str, str]:
    return {field: value for field, value in desired.items() if current.get(field) != value}


def compare_membership(present: bool, mode: str) -> str:
    return "MATCH" if present else "DRIFT"


def should_add_missing_item(present: bool, mode: str) -> bool:
    return (not present) and mode in {"reconcile", "event-sync"}


TRUSTED_AUTHOR_ASSOCIATIONS = github_issue_trust.TRUSTED_AUTHOR_ASSOCIATIONS


def is_trusted_author(issue: dict[str, Any]) -> bool:
    """Return direct trusted-author status for a devflow Issue."""
    return github_issue_trust.is_trusted_issue_author(issue)


def _repository_from_control(issue: dict[str, Any]) -> str | None:
    if not _is_repository_control(issue):
        return None
    try:
        sections = parse_sections(
            str(issue.get("body") or ""),
            reject_duplicates={"Repository"},
        )
        repository = sections.get("Repository", "").strip()
        if not repository:
            return None
        return devflow_mcp_core.normalize_repository(repository)
    except (ConfigError, devflow_mcp_core.DevflowMCPError):
        return None


def is_trusted_sync_issue(
    issue: dict[str, Any],
    *,
    control_trust_service: Any | None = None,
) -> bool:
    """Return whether an Issue may drive Project synchronization."""
    if is_trusted_author(issue):
        return True
    repository = _repository_from_control(issue)
    if repository is None or control_trust_service is None:
        return False
    try:
        canonical = control_trust_service.get_repository_control(repository)
        candidate_number = int(issue.get("number") or 0)
        canonical_number = int(canonical.get("issue_number") or 0)
        return candidate_number > 0 and candidate_number == canonical_number
    except (
        devflow_mcp_core.DevflowMCPError,
        ConfigError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return False


def is_health_issue(issue: dict[str, Any]) -> bool:
    return str(issue.get("title") or "").strip() == HEALTH_TITLE


def select_target_issue(
    rest: Any,
    issue_number: int,
    control_trust_service: Any | None = None,
) -> list[dict[str, Any]]:
    issue = rest.get_issue(issue_number)
    return (
        []
        if is_health_issue(issue)
        or not is_trusted_sync_issue(
            issue,
            control_trust_service=control_trust_service,
        )
        else [issue]
    )


def _redact(text: str, secrets: Iterable[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[REDACTED]")
    return out


def parse_health_failure_state(body: str) -> dict[str, dict[str, str]]:
    text = body or ""
    marker_index = text.find(HEALTH_FAILURE_STATE_MARKER)
    if marker_index < 0:
        return {}
    if text.find(HEALTH_FAILURE_STATE_MARKER, marker_index + len(HEALTH_FAILURE_STATE_MARKER)) >= 0:
        raise ConfigError("duplicate Project Sync Health failure-state marker")
    tail = text[marker_index + len(HEALTH_FAILURE_STATE_MARKER):]
    match = re.search(r"(?s)\n?\s*```json\s*\n(.*?)\n```", tail)
    if not match:
        raise ConfigError("malformed Project Sync Health failure-state payload")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ConfigError("invalid Project Sync Health failure-state JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ConfigError("unsupported Project Sync Health failure-state schema")
    failures = payload.get("failures")
    if not isinstance(failures, dict):
        raise ConfigError("Project Sync Health failure-state failures must be an object")
    normalized: dict[str, dict[str, str]] = {}
    for key, value in failures.items():
        key_text = str(key)
        if key_text != "global" and not key_text.isdigit():
            raise ConfigError(f"invalid Project Sync Health failure key: {key_text!r}")
        if not isinstance(value, dict):
            raise ConfigError(f"invalid Project Sync Health failure record: {key_text!r}")
        mode = str(value.get("mode") or "")
        run_url = str(value.get("run_url") or "")
        message = str(value.get("message") or "")
        if mode not in {"event-sync", "verify", "reconcile"}:
            raise ConfigError(f"invalid Project Sync Health failure mode: {mode!r}")
        normalized[key_text] = {
            "mode": mode,
            "run_url": run_url,
            "message": message,
        }
    return normalized


def update_health_failure_state(
    state: dict[str, dict[str, str]],
    *,
    mode: str,
    issue_number: int | None,
    failed: bool,
    run_url: str,
    message: str,
) -> dict[str, dict[str, str]]:
    updated = {key: dict(value) for key, value in state.items()}
    if issue_number is None:
        if not failed:
            return {}
        key = "global"
    else:
        key = str(issue_number)
        if not failed:
            updated.pop(key, None)
            return updated
    normalized_message = " ".join(str(message or "").split()).replace("```", "'''")[:500]
    updated[key] = {
        "mode": mode,
        "run_url": str(run_url or "Unavailable"),
        "message": normalized_message,
    }
    return updated


def _health_failure_lines(failures: dict[str, dict[str, str]]) -> list[str]:
    lines = ["## Unresolved Scoped Failures"]
    if not failures:
        lines.append("None")
    else:
        def sort_key(key: str) -> tuple[int, int]:
            return (0, 0) if key == "global" else (1, int(key))
        for key in sorted(failures, key=sort_key):
            record = failures[key]
            target = "global/full-scope verification" if key == "global" else f"Issue #{key}"
            run_url = record.get("run_url") or "Unavailable"
            mode = record.get("mode") or "unknown"
            message = record.get("message") or "failure remains unresolved"
            lines.append(f"- {target} — {mode} — {message} — {run_url}")
    payload = json.dumps(
        {"schema_version": 1, "failures": failures},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    lines.extend(["", HEALTH_FAILURE_STATE_MARKER, "```json", payload, "```"])
    return lines


def render_health_report(
    *, result: str, mode: str, project: dict[str, Any], coverage: dict[str, int],
    messages: list[str], run_url: str, direct_requirement: str = "NONE",
    direct_reason: str = "", secrets: Iterable[str] = (), timestamp: str | None = None,
    unresolved_failures: dict[str, dict[str, str]] | None = None,
) -> str:
    timestamp = timestamp or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    clean = [_redact(m, secrets) for m in messages] or ["None"]
    reason = _redact(direct_reason, secrets)
    lines = [
        "## Result", result, "", "## Last Verification", timestamp, "", "## Mode", mode, "",
        "## Project",
        f"- Owner: {project.get('owner', PROJECT_OWNER)}",
        f"- Number: {project.get('number', PROJECT_NUMBER)}",
        f"- Title: {project.get('title', PROJECT_TITLE)}", "",
        "## Coverage",
        f"- Canonical issues checked: {coverage.get('canonical_issues', 0)}",
        f"- Project items matched: {coverage.get('project_items', 0)}",
        f"- Drift fields: {coverage.get('drift_fields', 0)}",
        f"- Errors: {coverage.get('errors', 0)}", "",
        "## Drift / Errors",
    ]
    lines.extend(f"- {m}" for m in clean)
    lines.extend(["", "## Run", run_url or "Unavailable", "", "## Direct Verification Requirement", direct_requirement])
    if reason:
        lines.append(reason)
    lines.extend([""] + _health_failure_lines(unresolved_failures or {}))
    return "\n".join(lines).rstrip() + "\n"


def result_for_missing_project_token() -> str:
    return "NOT_CONFIGURED"


@dataclasses.dataclass(frozen=True)
class RuntimeConfig:
    repository: str
    project_token: str
    github_token: str
    owner: str = PROJECT_OWNER
    project_number: int = PROJECT_NUMBER
    maintenance_audit_token: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | os._Environ[str] = os.environ) -> "RuntimeConfig":
        return cls(
            repository=env.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY),
            project_token=env.get("PROJECTS_TOKEN", ""),
            github_token=env.get("GITHUB_TOKEN", ""),
            owner=env.get("PROJECT_OWNER", PROJECT_OWNER),
            project_number=int(env.get("PROJECT_NUMBER", str(PROJECT_NUMBER))),
            maintenance_audit_token=env.get("MAINTENANCE_AUDIT_TOKEN", ""),
        )


@dataclasses.dataclass(frozen=True)
class ProjectField:
    id: str
    name: str
    kind: str
    options: dict[str, str]


@dataclasses.dataclass(frozen=True)
class ProjectItem:
    id: str
    content_id: str
    number: int | None
    repository: str | None
    fields: dict[str, str]


@dataclasses.dataclass(frozen=True)
class ProjectSnapshot:
    id: str
    title: str
    public: bool
    fields: dict[str, ProjectField]
    items_by_content_id: dict[str, ProjectItem]


def _default_graphql_transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise APIError(f"GitHub GraphQL HTTP {exc.code}: {body[:500]}") from None
    except urllib.error.URLError as exc:
        raise APIError(f"GitHub GraphQL network error: {exc.reason}") from None


def _default_rest_transport(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise APIError(f"GitHub REST HTTP {exc.code}: {body[:500]}") from None
    except urllib.error.URLError as exc:
        raise APIError(f"GitHub REST network error: {exc.reason}") from None


class GitHubGraphQL:
    endpoint = "https://api.github.com/graphql"

    def __init__(self, token: str, transport: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None = None):
        self._token = token
        self._transport = transport or _default_graphql_transport

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "devflow-project-sync",
        }
        try:
            response = self._transport(self.endpoint, headers, {"query": query, "variables": variables or {}})
        except APIError:
            raise
        except Exception as exc:
            raise APIError(f"GitHub GraphQL transport failed: {type(exc).__name__}") from None
        if not isinstance(response, dict):
            raise APIError("GitHub GraphQL response was not an object")
        if response.get("errors"):
            messages = "; ".join(str(e.get("message", "GraphQL error")) for e in response["errors"])
            raise APIError(f"GitHub GraphQL error: {messages}")
        if "data" not in response:
            raise APIError("GitHub GraphQL response missing data")
        return response["data"]

    def get_project_identity(self, owner: str, number: int) -> dict[str, Any]:
        query = """
query($owner:String!, $number:Int!) {
  user(login:$owner) {
    projectV2(number:$number) { id title public }
  }
}
"""
        data = self.query(query, {"owner": owner, "number": number})
        project = (data.get("user") or {}).get("projectV2")
        if not project:
            raise ConfigError(f"Project {owner}#{number} not found or inaccessible")
        return project

    def get_project_fields(self, project_id: str) -> list[dict[str, Any]]:
        query = """
query($id:ID!, $after:String) {
  node(id:$id) {
    ... on ProjectV2 {
      fields(first:100, after:$after) {
        nodes {
          __typename
          ... on ProjectV2Field { id name dataType }
          ... on ProjectV2SingleSelectField { id name dataType options { id name } }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
        def fetch(cursor: str | None) -> dict[str, Any]:
            data = self.query(query, {"id": project_id, "after": cursor})
            connection = (data.get("node") or {}).get("fields")
            if connection is None:
                raise ConfigError("Project fields connection unavailable")
            return connection
        raw = collect_connection(fetch)
        fields: list[dict[str, Any]] = []
        for node in raw:
            if node.get("__typename") == "ProjectV2SingleSelectField":
                fields.append({"id": node["id"], "name": node["name"], "kind": "single", "options": node.get("options") or []})
            elif node.get("__typename") == "ProjectV2Field":
                data_type = str(node.get("dataType", "")).upper()
                kind = "text" if data_type == "TEXT" else "date" if data_type == "DATE" else data_type.lower()
                fields.append({"id": node["id"], "name": node["name"], "kind": kind, "options": []})
        return fields

    def get_project_items(self, project_id: str) -> list[dict[str, Any]]:
        query = """
query($id:ID!, $after:String) {
  node(id:$id) {
    ... on ProjectV2 {
      items(first:100, after:$after) {
        nodes {
          id
          content {
            __typename
            ... on Issue { id number title state repository { nameWithOwner } }
          }
          fieldValues(first:100) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldTextValue {
                text
                field { ... on ProjectV2Field { id name } }
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                optionId
                field { ... on ProjectV2SingleSelectField { id name } }
              }
              ... on ProjectV2ItemFieldDateValue {
                date
                field { ... on ProjectV2Field { id name } }
              }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
        def fetch(cursor: str | None) -> dict[str, Any]:
            data = self.query(query, {"id": project_id, "after": cursor})
            connection = (data.get("node") or {}).get("items")
            if connection is None:
                raise ConfigError("Project items connection unavailable")
            return connection
        raw = collect_connection(fetch)
        items: list[dict[str, Any]] = []
        for node in raw:
            content = node.get("content") or {}
            if content.get("__typename") != "Issue":
                continue
            values: dict[str, str] = {}
            for field_value in (node.get("fieldValues") or {}).get("nodes") or []:
                field = field_value.get("field") or {}
                name = field.get("name")
                if not name:
                    continue
                if field_value.get("__typename") == "ProjectV2ItemFieldTextValue":
                    values[name] = field_value.get("text") or ""
                elif field_value.get("__typename") == "ProjectV2ItemFieldSingleSelectValue":
                    values[name] = field_value.get("name") or ""
                elif field_value.get("__typename") == "ProjectV2ItemFieldDateValue":
                    values[name] = field_value.get("date") or ""
            items.append({
                "id": node["id"],
                "content_id": content.get("id"),
                "number": content.get("number"),
                "repository": (content.get("repository") or {}).get("nameWithOwner"),
                "fields": values,
            })
        return items

    def create_project_field(
        self, project_id: str, name: str, kind: str, options: list[dict[str, str]]
    ) -> None:
        data_type = {"text": "TEXT", "date": "DATE", "single": "SINGLE_SELECT"}.get(kind)
        if data_type is None:
            raise ConfigError(f"unsupported Project field kind: {kind}")
        query = """
mutation($project:ID!, $name:String!, $dataType:ProjectV2CustomFieldType!, $options:[ProjectV2SingleSelectFieldOptionInput!]) {
  createProjectV2Field(input:{
    projectId:$project, name:$name, dataType:$dataType, singleSelectOptions:$options
  }) { projectV2Field { ... on ProjectV2FieldCommon { id name } } }
}
"""
        self.query(query, {
            "project": project_id,
            "name": name,
            "dataType": data_type,
            "options": options if kind == "single" else None,
        })

    def add_item(self, project_id: str, content_id: str) -> str:
        query = """
mutation($project:ID!, $content:ID!) {
  addProjectV2ItemById(input:{projectId:$project, contentId:$content}) { item { id } }
}
"""
        data = self.query(query, {"project": project_id, "content": content_id})
        item = (data.get("addProjectV2ItemById") or {}).get("item") or {}
        if not item.get("id"):
            raise APIError("addProjectV2ItemById returned no item id")
        return item["id"]

    def update_single_select(self, project_id: str, item_id: str, field_id: str, option_id: str) -> None:
        query = """
mutation($project:ID!, $item:ID!, $field:ID!, $option:String!) {
  updateProjectV2ItemFieldValue(input:{
    projectId:$project, itemId:$item, fieldId:$field,
    value:{singleSelectOptionId:$option}
  }) { projectV2Item { id } }
}
"""
        self.query(query, {"project": project_id, "item": item_id, "field": field_id, "option": option_id})

    def update_text(self, project_id: str, item_id: str, field_id: str, text: str) -> None:
        query = """
mutation($project:ID!, $item:ID!, $field:ID!, $text:String!) {
  updateProjectV2ItemFieldValue(input:{
    projectId:$project, itemId:$item, fieldId:$field,
    value:{text:$text}
  }) { projectV2Item { id } }
}
"""
        self.query(query, {"project": project_id, "item": item_id, "field": field_id, "text": text})

    def update_date(self, project_id: str, item_id: str, field_id: str, date: str) -> None:
        query = """
mutation($project:ID!, $item:ID!, $field:ID!, $date:Date!) {
  updateProjectV2ItemFieldValue(input:{
    projectId:$project, itemId:$item, fieldId:$field, value:{date:$date}
  }) { projectV2Item { id } }
}
"""
        self.query(query, {"project": project_id, "item": item_id, "field": field_id, "date": date})

    def delete_item(self, project_id: str, item_id: str) -> None:
        query = """
mutation($project:ID!, $item:ID!) {
  deleteProjectV2Item(input:{projectId:$project, itemId:$item}) { deletedItemId }
}
"""
        self.query(query, {"project": project_id, "item": item_id})


class GitHubREST:
    def __init__(self, token: str, repository: str, transport: Callable[[str, str, dict[str, str], dict[str, Any] | None], Any] | None = None):
        self._token = token
        self.repository = repository
        self._transport = transport or _default_rest_transport
        self.base = f"https://api.github.com/repos/{repository}"

    def _request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "devflow-project-sync",
        }
        try:
            return self._transport(method, url, headers, payload)
        except APIError:
            raise
        except Exception as exc:
            raise APIError(f"GitHub REST transport failed: {type(exc).__name__}") from None

    def list_issues(self, state: str = "all", per_page: int = 100) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"state": state, "per_page": per_page, "page": page, "sort": "created", "direction": "asc"})
            batch = self._request("GET", f"{self.base}/issues?{query}")
            if not batch:
                break
            out.extend(issue for issue in batch if "pull_request" not in issue)
            if len(batch) < per_page:
                break
            page += 1
        return out

    def get_issue(self, number: int) -> dict[str, Any]:
        return self._request("GET", f"{self.base}/issues/{number}")

    def list_labels(self, per_page: int = 100) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"per_page": per_page, "page": page})
            batch = self._request("GET", f"{self.base}/labels?{query}")
            if not isinstance(batch, list):
                raise APIError("repository labels response was not a list")
            out.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < per_page:
                break
            page += 1
        return out

    def create_label(self, name: str, color: str, description: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.base}/labels",
            {"name": name, "color": color, "description": description},
        )

    def add_issue_labels(self, issue_number: int, labels: list[str]) -> Any:
        return self._request(
            "POST",
            f"{self.base}/issues/{issue_number}/labels",
            {"labels": labels},
        )

    def remove_issue_label(self, issue_number: int, label: str) -> Any:
        encoded = urllib.parse.quote(label, safe="")
        return self._request(
            "DELETE",
            f"{self.base}/issues/{issue_number}/labels/{encoded}",
        )

    def get_commit_sha(self, ref: str) -> str:
        encoded = urllib.parse.quote(ref, safe="")
        value = self._request("GET", f"{self.base}/commits/{encoded}")
        sha = value.get("sha") if isinstance(value, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise APIError("repository ref did not resolve to an exact commit SHA")
        return sha

    def find_issue_by_title(self, title: str) -> dict[str, Any] | None:
        for issue in self.list_issues(state="all"):
            if str(issue.get("title") or "").strip() == title:
                return issue
        return None

    def create_issue(self, title: str, body: str) -> dict[str, Any]:
        return self._request("POST", f"{self.base}/issues", {"title": title, "body": body})

    def update_issue(self, number: int, body: str | None = None, state: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        return self._request("PATCH", f"{self.base}/issues/{number}", payload)


def ensure_audit_project_fields(gql: Any, owner: str, number: int) -> int:
    identity = gql.get_project_identity(owner, number)
    if identity.get("title") != PROJECT_TITLE:
        raise ConfigError(f"Project title mismatch: {identity.get('title')!r}")
    if bool(identity.get("public")):
        raise ConfigError("Project must be Private")
    raw_fields = gql.get_project_fields(identity["id"])
    mutations = 0
    for name, spec in AUDIT_PROJECT_FIELD_SPECS.items():
        matches = [field for field in raw_fields if str(field.get("name", "")).strip() == name]
        if len(matches) > 1:
            raise ConfigError(f"expected at most one field named {name!r}, found {len(matches)}")
        if not matches:
            gql.create_project_field(
                identity["id"], name, str(spec["kind"]), list(spec.get("options") or [])
            )
            mutations += 1
            continue
        field = matches[0]
        expected_kind = str(spec["kind"])
        if field.get("kind") != expected_kind:
            raise ConfigError(
                f"Project field kind mismatch for {name}: expected {expected_kind}, got {field.get('kind')}"
            )
        if expected_kind == "single":
            expected_options = {str(option["name"]) for option in spec.get("options") or []}
            actual_options = {str(option.get("name", "")).strip() for option in field.get("options") or []}
            if actual_options != expected_options:
                raise ConfigError(
                    f"Project option mismatch for {name}: missing={sorted(expected_options - actual_options)}, extra={sorted(actual_options - expected_options)}"
                )
    return mutations

def discover_project(gql: Any, owner: str, number: int) -> ProjectSnapshot:
    identity = gql.get_project_identity(owner, number)
    if identity.get("title") != PROJECT_TITLE:
        raise ConfigError(f"Project title mismatch: {identity.get('title')!r}")
    if bool(identity.get("public")):
        raise ConfigError("Project must be Private")
    raw_fields = gql.get_project_fields(identity["id"])
    fields: dict[str, ProjectField] = {}
    for name in EXPECTED_FIELDS:
        node = require_unique_named(raw_fields, name)
        kind = node.get("kind", "")
        if name in SELECT_OPTIONS and kind != "single":
            raise ConfigError(f"Project field kind mismatch for {name}: expected single, got {kind}")
        if name in TEXT_FIELDS and kind != "text":
            raise ConfigError(f"Project field kind mismatch for {name}: expected text, got {kind}")
        if name in DATE_FIELDS and kind != "date":
            raise ConfigError(f"Project field kind mismatch for {name}: expected date, got {kind}")
        raw_options = node.get("options") or []
        option_names = [str(option.get("name", "")).strip() for option in raw_options]
        if len(option_names) != len(set(option_names)):
            raise ConfigError(f"duplicate Project option names in {name}")
        options = {str(option["name"]).strip(): option["id"] for option in raw_options}
        fields[name] = ProjectField(node["id"], name, kind, options)
    raw_items = gql.get_project_items(identity["id"])
    items: dict[str, ProjectItem] = {}
    for node in raw_items:
        content_id = node.get("content_id")
        if not content_id:
            continue
        if content_id in items:
            raise ConfigError(f"duplicate Project item for content {content_id}")
        items[content_id] = ProjectItem(
            node["id"], content_id, node.get("number"), node.get("repository"), dict(node.get("fields") or {})
        )
    return ProjectSnapshot(identity["id"], identity["title"], bool(identity.get("public")), fields, items)


def select_canonical_issues(
    issues: list[dict[str, Any]],
    tracked_items: dict[str, Any],
    control_trust_service: Any | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for issue in issues:
        if is_health_issue(issue):
            continue
        if not is_trusted_sync_issue(
            issue,
            control_trust_service=control_trust_service,
        ):
            continue
        node_id = issue.get("node_id") or issue.get("id")
        state = str(issue.get("state") or "").lower()
        if state == "open" or (node_id and node_id in tracked_items):
            desired = desired_project_fields(issue)
            managed = desired.get("Managed Repository", "")
            if any(managed == name or managed.endswith("/" + name) for name in EXCLUDED_REPOSITORIES):
                continue
            selected.append(issue)
    selected.sort(key=lambda issue: int(issue.get("number") or 0))
    return selected


def sync_one_issue(
    issue: dict[str, Any], snapshot: ProjectSnapshot, gql: Any, mode: str,
    extra_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    desired = desired_project_fields(issue)
    if extra_fields:
        desired.update(extra_fields)
    errors = validate_select_values(desired)
    if errors:
        raise ConfigError("; ".join(errors))
    content_id = issue.get("node_id") or issue.get("id")
    if not content_id:
        raise ConfigError(f"Issue #{issue.get('number')} has no node_id")
    item = snapshot.items_by_content_id.get(content_id)
    membership = compare_membership(item is not None, mode)
    mutations = 0
    if item is None and should_add_missing_item(False, mode):
        item_id = gql.add_item(snapshot.id, content_id)
        item = ProjectItem(item_id, content_id, issue.get("number"), None, {})
        mutations += 1
    current = item.fields if item else {}
    statuses = compare_fields(desired, current)
    if mode in {"reconcile", "event-sync"} and item:
        for field_name, value in plan_field_mutations(desired, current).items():
            field = snapshot.fields.get(field_name)
            if not field:
                raise ConfigError(f"Project field missing: {field_name}")
            if field_name in SELECT_OPTIONS:
                option_id = field.options.get(value)
                if not option_id:
                    raise ConfigError(f"Project option missing: {field_name}={value}")
                gql.update_single_select(snapshot.id, item.id, field.id, option_id)
            elif field_name in TEXT_FIELDS:
                gql.update_text(snapshot.id, item.id, field.id, value)
            elif field_name in DATE_FIELDS:
                gql.update_date(snapshot.id, item.id, field.id, value)
            else:
                raise ConfigError(f"Unsupported Project field: {field_name}")
            mutations += 1
    return {"issue_number": issue.get("number"), "membership": membership, "fields": statuses, "mutations": mutations}


def upsert_health_issue(rest: Any, body: str) -> dict[str, Any]:
    issue = rest.find_issue_by_title(HEALTH_TITLE)
    if issue is None:
        issue = rest.create_issue(HEALTH_TITLE, body)
        number = int(issue["number"])
        rest.update_issue(number, state="closed")
        return rest.update_issue(number, body=body)
    return rest.update_issue(int(issue["number"]), body=body)


def _validate_project_options(snapshot: ProjectSnapshot) -> None:
    for field_name, expected in SELECT_OPTIONS.items():
        field = snapshot.fields.get(field_name)
        if field is None:
            raise ConfigError(f"Project field missing: {field_name}")
        actual = set(field.options)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ConfigError(f"Project option mismatch for {field_name}: missing={missing}, extra={extra}")


def process_issues(
    issues: list[dict[str, Any]], snapshot: ProjectSnapshot, gql: Any, mode: str,
    freshness_resolver: Callable[[str, str], str] | None = None,
    rest: Any | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    mutations = 0
    matched_items = 0
    for issue in issues:
        try:
            extra_fields: dict[str, str] = {}
            freshness = derive_audit_freshness(issue, freshness_resolver)
            if freshness is not None:
                extra_fields["Audit Freshness"] = freshness
            result = sync_one_issue(issue, snapshot, gql, mode, extra_fields=extra_fields)
            projection = sync_audit_freshness_label_projection(
                issue, freshness, rest, mode
            )
            result["freshness_projection"] = projection["status"]
            result["mutations"] = int(result.get("mutations", 0)) + int(projection["mutations"])
            results.append(result)
            mutations += int(result.get("mutations", 0))
            if result.get("membership") == "MATCH":
                matched_items += 1
        except SyncError as exc:
            errors.append(f"#{issue.get('number')}: {exc}")
    drift_fields = 0
    membership_drift = 0
    for result in results:
        if result.get("membership") == "DRIFT":
            membership_drift += 1
        drift_fields += sum(1 for state in result.get("fields", {}).values() if state == "DRIFT")
        if result.get("freshness_projection") == "DRIFT":
            drift_fields += 1
    return {
        "results": results,
        "errors": errors,
        "mutations": mutations,
        "drift_fields": drift_fields,
        "membership_drift": membership_drift,
        "project_items": matched_items,
        "canonical_issues": len(issues),
    }

def ensure_health_not_project_item(health_issue: dict[str, Any] | None, snapshot: ProjectSnapshot, gql: Any, mode: str) -> str:
    if not health_issue:
        return "NOT_APPLICABLE"
    node_id = health_issue.get("node_id") or health_issue.get("id")
    if not node_id:
        return "NOT_APPLICABLE"
    item = snapshot.items_by_content_id.get(node_id)
    if not item:
        return "MATCH"
    if mode == "reconcile":
        gql.delete_item(snapshot.id, item.id)
        return "REPAIRED"
    return "DRIFT"


def reread_event_issue(
    rest: Any,
    event_issue: dict[str, Any],
    control_trust_service: Any | None = None,
) -> dict[str, Any]:
    issue_number = int(event_issue.get("number") or 0)
    if issue_number <= 0:
        raise ConfigError("event-sync post-write readback requires a valid issue number")
    live = rest.get_issue(issue_number)
    if not isinstance(live, dict):
        raise ConfigError("event-sync post-write readback returned no Issue")
    if is_health_issue(live) or not is_trusted_sync_issue(
        live,
        control_trust_service=control_trust_service,
    ):
        raise ConfigError("event-sync post-write readback is not a trusted canonical Issue")
    return live


def load_event_issue(path: str) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read GitHub event payload: {exc}") from None
    issue = payload.get("issue")
    return issue if isinstance(issue, dict) else None


def _run_url(env: dict[str, str] | os._Environ[str] = os.environ) -> str:
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    repo = env.get("GITHUB_REPOSITORY", "")
    run_id = env.get("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "Unavailable"


def _health_body_for_missing_token(
    mode: str,
    run_url: str,
    unresolved_failures: dict[str, dict[str, str]] | None = None,
) -> str:
    return render_health_report(
        result="NOT_CONFIGURED", mode=mode,
        project={"owner": PROJECT_OWNER, "number": PROJECT_NUMBER, "title": PROJECT_TITLE},
        coverage={"canonical_issues": 0, "project_items": 0, "drift_fields": 0, "errors": 1},
        messages=["PROJECTS_TOKEN is not configured; Project access and mutation were not attempted."],
        run_url=run_url, direct_requirement="NONE",
        unresolved_failures=unresolved_failures,
    )


def _summary_messages(summary: dict[str, Any], health_item_status: str = "MATCH") -> list[str]:
    messages = list(summary.get("errors") or [])
    if summary.get("membership_drift"):
        messages.append(f"Project membership drift: {summary['membership_drift']}")
    if summary.get("drift_fields"):
        messages.append(f"Synchronized value drift: {summary['drift_fields']}")
    if health_item_status == "DRIFT":
        messages.append("Sync Health Issue is present in the display Project and should be removed by reconcile.")
    return messages


def _summary_health(
    mode: str,
    snapshot: ProjectSnapshot,
    summary: dict[str, Any],
    run_url: str,
    health_item_status: str = "MATCH",
    unresolved_failures: dict[str, dict[str, str]] | None = None,
) -> tuple[str, str]:
    messages = _summary_messages(summary, health_item_status)
    failures = unresolved_failures or {}
    if failures:
        scoped = ", ".join(
            "global" if key == "global" else f"#{key}"
            for key in sorted(failures, key=lambda key: (0, 0) if key == "global" else (1, int(key)))
        )
        messages.append(f"Unresolved Project sync failure memory remains: {scoped}")
    blocking = bool(messages)
    result = "FAIL" if blocking else "PASS"
    body = render_health_report(
        result=result, mode=mode,
        project={"owner": PROJECT_OWNER, "number": PROJECT_NUMBER, "title": snapshot.title},
        coverage={
            "canonical_issues": int(summary.get("canonical_issues", 0)),
            "project_items": int(summary.get("project_items", 0)),
            "drift_fields": int(summary.get("drift_fields", 0)) + int(summary.get("membership_drift", 0)),
            "errors": len(summary.get("errors") or []),
        },
        messages=messages,
        run_url=run_url,
        unresolved_failures=failures,
    )
    return result, body


def run_sync(
    mode: str, cfg: RuntimeConfig, *, rest: Any | None = None, gql: Any | None = None,
    issue_number: int | None = None, event_issue: dict[str, Any] | None = None,
    run_url: str = "Unavailable",
    control_trust_service: Any | None = None,
) -> int:
    if control_trust_service is None and cfg.maintenance_audit_token:
        control_trust_service = devflow_mcp_core.DevflowService(
            devflow_mcp_core.GitHubReader(token=cfg.maintenance_audit_token)
        )

    if mode == "event-sync" and event_issue and (
        is_health_issue(event_issue)
        or not is_trusted_sync_issue(
            event_issue,
            control_trust_service=control_trust_service,
        )
    ):
        # Only direct trusted-author Issues or canonical verified Repository Controls may drive Project writes.
        return 0

    if rest is None and cfg.github_token:
        rest = GitHubREST(cfg.github_token, cfg.repository)

    failure_state: dict[str, dict[str, str]] = {}
    previous_health_issue: dict[str, Any] | None = None
    try:
        if rest is not None:
            previous_health_issue = rest.find_issue_by_title(HEALTH_TITLE)
            if previous_health_issue is not None:
                failure_state = parse_health_failure_state(
                    str(previous_health_issue.get("body") or "")
                )

        if not cfg.project_token:
            if rest is not None:
                upsert_health_issue(
                    rest,
                    _health_body_for_missing_token(
                        mode,
                        run_url,
                        unresolved_failures=failure_state,
                    ),
                )
            return 2

        gql = gql or GitHubGraphQL(cfg.project_token)
        if mode in {"reconcile", "event-sync"} and rest is not None:
            ensure_audit_freshness_labels(rest)
        if mode == "reconcile":
            ensure_audit_project_fields(gql, cfg.owner, cfg.project_number)
        snapshot = discover_project(gql, cfg.owner, cfg.project_number)
        _validate_project_options(snapshot)

        health_issue = previous_health_issue
        health_item_status = ensure_health_not_project_item(health_issue, snapshot, gql, mode=mode)

        freshness_clients: dict[str, GitHubREST] = {}
        freshness_cache: dict[tuple[str, str], str] = {}

        def resolve_freshness_head(repository: str, ref: str) -> str:
            key = (repository, ref)
            if key in freshness_cache:
                return freshness_cache[key]
            if not cfg.maintenance_audit_token:
                raise APIError("maintenance audit read token unavailable")
            client = freshness_clients.get(repository)
            if client is None:
                client = GitHubREST(cfg.maintenance_audit_token, repository)
                freshness_clients[repository] = client
            freshness_cache[key] = client.get_commit_sha(ref)
            return freshness_cache[key]

        freshness_resolver = resolve_freshness_head if cfg.maintenance_audit_token else None

        if mode == "event-sync":
            issue = event_issue
            if issue is None:
                raise ConfigError("event-sync requires an issue event payload")
            issues = [issue]
            summary = process_issues(
                issues, snapshot, gql, mode="event-sync",
                freshness_resolver=freshness_resolver, rest=rest,
            )
            if rest is None:
                raise ConfigError("event-sync post-write readback requires repository access")
            live_issue = reread_event_issue(
                rest,
                issue,
                control_trust_service=control_trust_service,
            )
            issues = [live_issue]
            snapshot2 = discover_project(gql, cfg.owner, cfg.project_number)
            verify_summary = process_issues(
                issues, snapshot2, gql, mode="verify",
                freshness_resolver=freshness_resolver, rest=rest,
            )
            verify_summary["mutations"] = summary.get("mutations", 0)
            summary = verify_summary
        else:
            if rest is None:
                raise ConfigError("repository token is required for verify/reconcile issue reads")
            if issue_number is not None:
                issues = select_target_issue(
                    rest,
                    issue_number,
                    control_trust_service=control_trust_service,
                )
            else:
                all_issues = rest.list_issues(state="all")
                issues = select_canonical_issues(
                    all_issues,
                    snapshot.items_by_content_id,
                    control_trust_service=control_trust_service,
                )
            summary = process_issues(
                issues, snapshot, gql, mode=mode,
                freshness_resolver=freshness_resolver, rest=rest,
            )
            if mode == "reconcile" and not summary.get("errors"):
                snapshot2 = discover_project(gql, cfg.owner, cfg.project_number)
                _validate_project_options(snapshot2)
                health_issue2 = rest.find_issue_by_title(HEALTH_TITLE)
                health_item_status = ensure_health_not_project_item(health_issue2, snapshot2, gql, mode="reconcile")
                snapshot3 = discover_project(gql, cfg.owner, cfg.project_number)
                issues2 = (
                    select_target_issue(
                        rest,
                        issue_number,
                        control_trust_service=control_trust_service,
                    )
                    if issue_number is not None
                    else select_canonical_issues(
                        rest.list_issues(state="all"),
                        snapshot3.items_by_content_id,
                        control_trust_service=control_trust_service,
                    )
                )
                summary = process_issues(
                    issues2, snapshot3, gql, mode="verify",
                    freshness_resolver=freshness_resolver, rest=rest,
                )
                health_item_status = ensure_health_not_project_item(rest.find_issue_by_title(HEALTH_TITLE), snapshot3, gql, mode="verify")
                snapshot = snapshot3

        current_messages = _summary_messages(summary, health_item_status)
        scoped_issue_number: int | None
        if mode == "event-sync":
            scoped_issue_number = int((event_issue or {}).get("number") or 0) or None
        else:
            scoped_issue_number = issue_number
        safe_current_message = _redact(
            "; ".join(current_messages),
            [cfg.project_token, cfg.github_token, cfg.maintenance_audit_token],
        )
        failure_state = update_health_failure_state(
            failure_state,
            mode=mode,
            issue_number=scoped_issue_number,
            failed=bool(current_messages),
            run_url=run_url,
            message=safe_current_message,
        )
        result, body = _summary_health(
            mode,
            snapshot,
            summary,
            run_url,
            health_item_status,
            unresolved_failures=failure_state,
        )
        if rest is not None:
            upsert_health_issue(rest, body)
        return 0 if result == "PASS" else 1
    except SyncError as exc:
        scoped_issue_number = (
            (int((event_issue or {}).get("number") or 0) or None)
            if mode == "event-sync"
            else issue_number
        )
        safe_message = _redact(
            str(exc),
            [cfg.project_token, cfg.github_token, cfg.maintenance_audit_token],
        )
        failure_state = update_health_failure_state(
            failure_state,
            mode=mode,
            issue_number=scoped_issue_number,
            failed=True,
            run_url=run_url,
            message=safe_message,
        )
        body = render_health_report(
            result="FAIL", mode=mode,
            project={"owner": cfg.owner, "number": cfg.project_number, "title": PROJECT_TITLE},
            coverage={"canonical_issues": 0, "project_items": 0, "drift_fields": 0, "errors": 1},
            messages=[safe_message], run_url=run_url, direct_requirement="CODEX_REQUIRED" if isinstance(exc, ConfigError) else "NONE",
            direct_reason="Project structure/configuration needs direct verification." if isinstance(exc, ConfigError) else "",
            secrets=[cfg.project_token, cfg.github_token, cfg.maintenance_audit_token],
            unresolved_failures=failure_state,
        )
        if rest is not None:
            try:
                upsert_health_issue(rest, body)
            except Exception:
                pass
        print(_redact(str(exc), [cfg.project_token, cfg.github_token, cfg.maintenance_audit_token]), file=sys.stderr)
        return 1

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["event-sync", "verify", "reconcile"])
    parser.add_argument("--issue-number", type=int)
    args = parser.parse_args(argv)
    cfg = RuntimeConfig.from_env()
    event_issue = load_event_issue(os.environ.get("GITHUB_EVENT_PATH", "")) if args.mode == "event-sync" else None
    return run_sync(
        args.mode, cfg, issue_number=args.issue_number, event_issue=event_issue, run_url=_run_url()
    )


if __name__ == "__main__":
    raise SystemExit(main())
