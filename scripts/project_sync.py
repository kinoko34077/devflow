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

PROJECT_OWNER = "kinoko34077"
PROJECT_NUMBER = 1
PROJECT_TITLE = "KiNoTch. Development Control"
HEALTH_TITLE = "[SYSTEM] GitHub Project Sync Health"
EXCLUDED_REPOSITORIES = {"pc-files", "pc-files2"}

FIELD_MAP = {
    "Work Status": "Status",
    "Repository State": "Repository State",
    "Priority": "Priority",
    "Risk": "Risk",
    "Type": "Work Type",
    "Repository": "Managed Repository",
    "Next Action": "Next Action",
    "Audit SHA": "Audit SHA",
}
SELECT_OPTIONS = {
    "Status": {
        "NEEDS_AUDIT", "AUDITED", "WORK_ORDER_READY", "READY_FOR_IMPLEMENTATION",
        "IMPLEMENTING", "AWAITING_REVIEW", "BLOCKED", "NEEDS_REAUDIT", "PARKED", "DONE",
    },
    "Repository State": {"ACTIVE", "PARKED", "MAINTENANCE", "DEPRECATED", "CANCELLED"},
    "Priority": {"P0", "P1", "P2", "P3"},
    "Risk": {"LOW", "MEDIUM", "HIGH", "CRITICAL"},
    "Work Type": {"FEATURE", "BUG", "SPEC", "AUDIT", "REFACTOR", "MAINTENANCE", "RESEARCH", "INFRA", "DOCS"},
}
TEXT_FIELDS = {"Managed Repository", "Next Action", "Audit SHA"}
EXPECTED_FIELDS = set(SELECT_OPTIONS) | TEXT_FIELDS


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


def parse_sections(body: str) -> dict[str, str]:
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        m = re.match(r"^## ([^#].*?)\s*$", line)
        if m:
            current = m.group(1).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: _strip_scalar("\n".join(value)) for name, value in sections.items()}


def desired_project_fields(issue: dict[str, Any]) -> dict[str, str]:
    sections = parse_sections(str(issue.get("body") or ""))
    desired: dict[str, str] = {}
    for section, field in FIELD_MAP.items():
        value = sections.get(section, "").strip()
        if value:
            desired[field] = value
    if str(issue.get("state", "")).lower() == "closed":
        desired["Status"] = "DONE"
    return desired


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


def is_health_issue(issue: dict[str, Any]) -> bool:
    return str(issue.get("title") or "").strip() == HEALTH_TITLE


def _redact(text: str, secrets: Iterable[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[REDACTED]")
    return out


def render_health_report(
    *, result: str, mode: str, project: dict[str, Any], coverage: dict[str, int],
    messages: list[str], run_url: str, direct_requirement: str = "NONE",
    direct_reason: str = "", secrets: Iterable[str] = (), timestamp: str | None = None,
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

    @classmethod
    def from_env(cls, env: dict[str, str] | os._Environ[str] = os.environ) -> "RuntimeConfig":
        return cls(
            repository=env.get("GITHUB_REPOSITORY", "kinoko34077/devflow-test"),
            project_token=env.get("PROJECTS_TOKEN", ""),
            github_token=env.get("GITHUB_TOKEN", ""),
            owner=env.get("PROJECT_OWNER", PROJECT_OWNER),
            project_number=int(env.get("PROJECT_NUMBER", str(PROJECT_NUMBER))),
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
        response = self._transport(self.endpoint, headers, {"query": query, "variables": variables or {}})
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
                kind = "text" if node.get("dataType") == "TEXT" else str(node.get("dataType", "")).lower()
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
            items.append({
                "id": node["id"],
                "content_id": content.get("id"),
                "number": content.get("number"),
                "repository": (content.get("repository") or {}).get("nameWithOwner"),
                "fields": values,
            })
        return items

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
        return self._transport(method, url, headers, payload)

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


def select_canonical_issues(issues: list[dict[str, Any]], tracked_items: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for issue in issues:
        if is_health_issue(issue):
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


def sync_one_issue(issue: dict[str, Any], snapshot: ProjectSnapshot, gql: Any, mode: str) -> dict[str, Any]:
    desired = desired_project_fields(issue)
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


def process_issues(issues: list[dict[str, Any]], snapshot: ProjectSnapshot, gql: Any, mode: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    mutations = 0
    matched_items = 0
    for issue in issues:
        try:
            result = sync_one_issue(issue, snapshot, gql, mode)
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


def _health_body_for_missing_token(mode: str, run_url: str) -> str:
    return render_health_report(
        result="NOT_CONFIGURED", mode=mode,
        project={"owner": PROJECT_OWNER, "number": PROJECT_NUMBER, "title": PROJECT_TITLE},
        coverage={"canonical_issues": 0, "project_items": 0, "drift_fields": 0, "errors": 1},
        messages=["PROJECTS_TOKEN is not configured; Project access and mutation were not attempted."],
        run_url=run_url, direct_requirement="NONE",
    )


def _summary_health(mode: str, snapshot: ProjectSnapshot, summary: dict[str, Any], run_url: str, health_item_status: str = "MATCH") -> tuple[str, str]:
    messages = list(summary.get("errors") or [])
    if summary.get("membership_drift"):
        messages.append(f"Project membership drift: {summary['membership_drift']}")
    if summary.get("drift_fields"):
        messages.append(f"Project field drift: {summary['drift_fields']}")
    if health_item_status == "DRIFT":
        messages.append("Sync Health Issue is present in the display Project and should be removed by reconcile.")
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
        messages=messages, run_url=run_url,
    )
    return result, body


def run_sync(
    mode: str, cfg: RuntimeConfig, *, rest: Any | None = None, gql: Any | None = None,
    issue_number: int | None = None, event_issue: dict[str, Any] | None = None, run_url: str = "Unavailable",
) -> int:
    if mode == "event-sync" and event_issue and is_health_issue(event_issue):
        return 0

    if rest is None and cfg.github_token:
        rest = GitHubREST(cfg.github_token, cfg.repository)

    if not cfg.project_token:
        if rest is not None:
            upsert_health_issue(rest, _health_body_for_missing_token(mode, run_url))
        return 2

    gql = gql or GitHubGraphQL(cfg.project_token)
    try:
        snapshot = discover_project(gql, cfg.owner, cfg.project_number)
        _validate_project_options(snapshot)

        health_issue = rest.find_issue_by_title(HEALTH_TITLE) if rest is not None else None
        health_item_status = ensure_health_not_project_item(health_issue, snapshot, gql, mode=mode)

        if mode == "event-sync":
            issue = event_issue
            if issue is None:
                raise ConfigError("event-sync requires an issue event payload")
            issues = [issue]
            summary = process_issues(issues, snapshot, gql, mode="event-sync")
            snapshot2 = discover_project(gql, cfg.owner, cfg.project_number)
            verify_summary = process_issues(issues, snapshot2, gql, mode="verify")
            verify_summary["mutations"] = summary.get("mutations", 0)
            summary = verify_summary
        else:
            if rest is None:
                raise ConfigError("repository token is required for verify/reconcile issue reads")
            if issue_number is not None:
                issue = rest.get_issue(issue_number)
                issues = [] if is_health_issue(issue) else [issue]
            else:
                all_issues = rest.list_issues(state="all")
                issues = select_canonical_issues(all_issues, snapshot.items_by_content_id)
            summary = process_issues(issues, snapshot, gql, mode=mode)
            if mode == "reconcile" and not summary.get("errors"):
                snapshot2 = discover_project(gql, cfg.owner, cfg.project_number)
                _validate_project_options(snapshot2)
                health_issue2 = rest.find_issue_by_title(HEALTH_TITLE)
                health_item_status = ensure_health_not_project_item(health_issue2, snapshot2, gql, mode="reconcile")
                snapshot3 = discover_project(gql, cfg.owner, cfg.project_number)
                issues2 = [rest.get_issue(issue_number)] if issue_number is not None else select_canonical_issues(rest.list_issues(state="all"), snapshot3.items_by_content_id)
                summary = process_issues(issues2, snapshot3, gql, mode="verify")
                health_item_status = ensure_health_not_project_item(rest.find_issue_by_title(HEALTH_TITLE), snapshot3, gql, mode="verify")
                snapshot = snapshot3

        result, body = _summary_health(mode, snapshot, summary, run_url, health_item_status)
        if rest is not None:
            upsert_health_issue(rest, body)
        return 0 if result == "PASS" else 1
    except SyncError as exc:
        body = render_health_report(
            result="FAIL", mode=mode,
            project={"owner": cfg.owner, "number": cfg.project_number, "title": PROJECT_TITLE},
            coverage={"canonical_issues": 0, "project_items": 0, "drift_fields": 0, "errors": 1},
            messages=[str(exc)], run_url=run_url, direct_requirement="CODEX_REQUIRED" if isinstance(exc, ConfigError) else "NONE",
            direct_reason="Project structure/configuration needs direct verification." if isinstance(exc, ConfigError) else "",
            secrets=[cfg.project_token, cfg.github_token],
        )
        if rest is not None:
            try:
                upsert_health_issue(rest, body)
            except Exception:
                pass
        print(_redact(str(exc), [cfg.project_token, cfg.github_token]), file=sys.stderr)
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
