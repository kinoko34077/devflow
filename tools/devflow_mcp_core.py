#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterable

DEFAULT_OWNER = "kinoko34077"
DEVFLOW_REPOSITORY = "kinoko34077/devflow"
HEALTH_TITLE = "[SYSTEM] GitHub Project Sync Health"
API_BASE = "https://api.github.com"
USER_AGENT = "kinotch-devflow-mcp"


class DevflowMCPError(RuntimeError):
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
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.split("\n"):
        match = re.match(r"^## ([^#].*?)\s*$", line)
        if match:
            current = match.group(1).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: _strip_scalar("\n".join(lines)) for name, lines in sections.items()}


def normalize_repository(repository: str) -> str:
    value = (repository or "").strip()
    if not value:
        raise DevflowMCPError("Repository name is required.")
    if value.count("/") == 0:
        value = f"{DEFAULT_OWNER}/{value}"
    if value.count("/") != 1:
        raise DevflowMCPError(f"Invalid repository name: {repository!r}")
    owner, name = value.split("/", 1)
    if not owner or not name or any(part.strip() != part for part in (owner, name)):
        raise DevflowMCPError(f"Invalid repository name: {repository!r}")
    return value


def _default_transport(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 404}:
            raise DevflowMCPError(
                f"GitHub read failed with HTTP {exc.code}. "
                "If the repository is private or access-controlled, configure a read-capable "
                "DEVFLOW_GITHUB_TOKEN or GITHUB_TOKEN."
            ) from None
        raise DevflowMCPError(f"GitHub read failed with HTTP {exc.code}.") from None
    except urllib.error.URLError as exc:
        raise DevflowMCPError(f"GitHub network read failed: {exc.reason}") from None
    except json.JSONDecodeError:
        raise DevflowMCPError("GitHub returned invalid JSON.") from None


class GitHubReader:
    """Read-only GitHub REST client. It intentionally exposes GET operations only."""

    def __init__(
        self,
        token: str = "",
        *,
        api_base: str = API_BASE,
        transport: Callable[[str, dict[str, str]], Any] | None = None,
    ) -> None:
        self._token = token.strip()
        self._api_base = api_base.rstrip("/")
        self._transport = transport or _default_transport

    @classmethod
    def from_env(cls) -> "GitHubReader":
        token = os.environ.get("DEVFLOW_GITHUB_TOKEN", "").strip()
        if not token:
            token = os.environ.get("GITHUB_TOKEN", "").strip()
        return cls(token=token)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _repository_url(self, repository: str, suffix: str) -> str:
        normalized = normalize_repository(repository)
        owner, name = normalized.split("/", 1)
        safe_owner = urllib.parse.quote(owner, safe="")
        safe_name = urllib.parse.quote(name, safe="")
        return f"{self._api_base}/repos/{safe_owner}/{safe_name}/{suffix.lstrip('/')}"

    def list_issues(self, repository: str, state: str = "open", per_page: int = 100) -> list[dict[str, Any]]:
        if state not in {"open", "closed", "all"}:
            raise DevflowMCPError(f"Unsupported issue state: {state!r}")
        issues: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"state": state, "per_page": per_page, "page": page})
            url = self._repository_url(repository, f"issues?{query}")
            batch = self._transport(url, self._headers())
            if not isinstance(batch, list):
                raise DevflowMCPError("GitHub issues response was not a list.")
            actual_issues = [item for item in batch if isinstance(item, dict) and "pull_request" not in item]
            issues.extend(actual_issues)
            if len(batch) < per_page:
                return issues
            page += 1

    def get_issue(self, repository: str, issue_number: int) -> dict[str, Any]:
        if issue_number < 1:
            raise DevflowMCPError("Issue number must be >= 1.")
        url = self._repository_url(repository, f"issues/{issue_number}")
        issue = self._transport(url, self._headers())
        if not isinstance(issue, dict):
            raise DevflowMCPError("GitHub issue response was not an object.")
        return issue


def _exactly_one(items: Iterable[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], description: str) -> dict[str, Any]:
    matches = [item for item in items if predicate(item)]
    if len(matches) != 1:
        raise DevflowMCPError(f"Expected exactly one {description}; found {len(matches)}.")
    return matches[0]


def _issue_url(issue: dict[str, Any]) -> str:
    return str(issue.get("html_url") or issue.get("url") or "")


class DevflowService:
    def __init__(self, reader: GitHubReader | Any, *, devflow_repository: str = DEVFLOW_REPOSITORY) -> None:
        self.reader = reader
        self.devflow_repository = normalize_repository(devflow_repository)

    def list_managed_repositories(self) -> list[str]:
        issues = self.reader.list_issues(self.devflow_repository, state="open")
        repositories: list[str] = []
        for issue in issues:
            title = str(issue.get("title") or "").strip()
            if not title.startswith("[REPO] "):
                continue
            sections = parse_sections(str(issue.get("body") or ""))
            repository = sections.get("Repository", "").strip()
            if repository:
                try:
                    repositories.append(normalize_repository(repository))
                    continue
                except DevflowMCPError:
                    pass
            repositories.append(normalize_repository(title.removeprefix("[REPO] ").strip()))
        return sorted(set(repositories), key=str.casefold)

    def get_repository_control(self, repository: str) -> dict[str, Any]:
        normalized = normalize_repository(repository)
        short_name = normalized.split("/", 1)[1]
        title = f"[REPO] {short_name}"
        issues = self.reader.list_issues(self.devflow_repository, state="open")
        matches = [issue for issue in issues if str(issue.get("title") or "").strip() == title]
        if not matches:
            raise DevflowMCPError(
                f"No open Repository Control Issue titled {title!r}. "
                "Do not infer managed state; onboarding or control reconciliation is required."
            )
        if len(matches) != 1:
            raise DevflowMCPError(f"Expected one open Repository Control Issue titled {title!r}; found {len(matches)}.")
        issue = matches[0]
        sections = parse_sections(str(issue.get("body") or ""))
        recorded_repository = sections.get("Repository", "").strip()
        if recorded_repository and normalize_repository(recorded_repository) != normalized:
            raise DevflowMCPError(
                f"Repository Control title resolved to {recorded_repository!r}, not {normalized!r}."
            )
        return {
            "repository": normalized,
            "issue_number": int(issue.get("number") or 0),
            "url": _issue_url(issue),
            "title": str(issue.get("title") or ""),
            "work_status": sections.get("Work Status", ""),
            "repository_state": sections.get("Repository State", ""),
            "priority": sections.get("Priority", ""),
            "risk": sections.get("Risk", ""),
            "audit_sha": sections.get("Audit SHA", ""),
            "active_work": sections.get("Active Work", ""),
            "next_action": sections.get("Next Action", ""),
            "canonical_entry_points": sections.get("Canonical Entry Points", ""),
            "detailed_current_state": sections.get("Detailed Current State", ""),
            "control_notes": sections.get("Control Notes", ""),
            "sections": sections,
        }

    def bootstrap_repository(self, repository: str) -> dict[str, Any]:
        control = self.get_repository_control(repository)
        return {
            **control,
            "authority": (
                "devflow owns cross-repository operational state; the owning repository owns "
                "detailed technical truth; GitHub Project is display-only."
            ),
            "read_order": [
                "devflow/AGENTS.md",
                f"devflow Repository Control Issue #{control['issue_number']}",
                "repository-local canonical entry points from the Control Issue",
                "active repository-local Issue / Work Order / PR when referenced",
                "task-relevant repository specs / Current State / code / tests",
            ],
            "reporting": (
                "Use Issue-first reporting for durable progress/evidence/handoff. "
                "Keep chat to result, current state, blocker, required user action and Issue references."
            ),
        }

    def get_issue(self, repository: str, issue_number: int) -> dict[str, Any]:
        normalized = normalize_repository(repository)
        issue = self.reader.get_issue(normalized, issue_number)
        body = str(issue.get("body") or "")
        return {
            "repository": normalized,
            "issue_number": int(issue.get("number") or issue_number),
            "title": str(issue.get("title") or ""),
            "state": str(issue.get("state") or ""),
            "url": _issue_url(issue),
            "body": body,
            "sections": parse_sections(body),
        }

    def get_sync_health(self) -> dict[str, Any]:
        issues = self.reader.list_issues(self.devflow_repository, state="all")
        issue = _exactly_one(
            issues,
            lambda item: str(item.get("title") or "").strip() == HEALTH_TITLE,
            "Sync Health Issue",
        )
        sections = parse_sections(str(issue.get("body") or ""))
        return {
            "issue_number": int(issue.get("number") or 0),
            "url": _issue_url(issue),
            "state": str(issue.get("state") or ""),
            "result": sections.get("Result", ""),
            "last_verification": sections.get("Last Verification", ""),
            "mode": sections.get("Mode", ""),
            "coverage": sections.get("Coverage", ""),
            "drift_errors": sections.get("Drift / Errors", ""),
            "run": sections.get("Run", ""),
            "direct_verification_requirement": sections.get("Direct Verification Requirement", ""),
            "sections": sections,
        }


def default_service() -> DevflowService:
    repository = os.environ.get("DEVFLOW_REPOSITORY", DEVFLOW_REPOSITORY).strip() or DEVFLOW_REPOSITORY
    return DevflowService(GitHubReader.from_env(), devflow_repository=repository)
