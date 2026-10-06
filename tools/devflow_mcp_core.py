#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

try:
    from .repository_bootstrap import (
        BootstrapError,
        normalize_request,
        parse_control_provenance,
        parse_provenance_document,
        parse_request_body,
    )
    from . import (
        github_issue_trust,
        human_portfolio,
        maintenance_sync_check,
        reconciliation_publication,
        repository_projection,
        workflow_contract,
    )
except ImportError:  # direct script execution
    import sys

    _repository_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _repository_root not in sys.path:
        sys.path.insert(0, _repository_root)

    from repository_bootstrap import (
        BootstrapError,
        normalize_request,
        parse_control_provenance,
        parse_provenance_document,
        parse_request_body,
    )
    import github_issue_trust
    import human_portfolio
    import maintenance_sync_check
    import reconciliation_publication
    import repository_projection
    import workflow_contract

WORKFLOW_CONTRACT = workflow_contract.WORKFLOW_CONTRACT

DEFAULT_OWNER = "kinoko34077"
DEVFLOW_REPOSITORY = "kinoko34077/devflow"
HEALTH_TITLE = "[SYSTEM] GitHub Project Sync Health"
API_BASE = "https://api.github.com"
USER_AGENT = "kinotch-devflow-mcp"
HUMAN_PORTFOLIO_READ_SCHEMA_VERSION = "human-portfolio-read.v1"


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


def parse_sections(body: str, *, reject_duplicates: bool = False) -> dict[str, str]:
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.split("\n"):
        match = re.match(r"^## ([^#].*?)\s*$", line)
        if match:
            current = match.group(1).strip()
            if reject_duplicates and current in sections:
                raise DevflowMCPError(f"Duplicate section in canonical Issue body: {current!r}.")
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
    with urllib.request.urlopen(request, timeout=30) as response:
        final_url = response.geturl()
        if final_url != url:
            # A redirect means the observed object may not be the requested
            # one (transfer, rename, misrouting). Fail closed; never relabel.
            raise DevflowMCPError(
                "GitHub read was redirected; refusing to use a response whose "
                f"identity differs from the request ({_redact_url(url)} -> {_redact_url(final_url)})."
            )
        payload = response.read().decode("utf-8")
        return json.loads(payload) if payload else None


def _redact_url(value: str) -> str:
    parts = urllib.parse.urlsplit(str(value))
    return urllib.parse.urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))


def _translate_read_error(exc: Exception) -> DevflowMCPError:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in {401, 403, 404}:
            return DevflowMCPError(
                f"GitHub read failed with HTTP {exc.code}. "
                "If the repository is private or access-controlled, configure a read-capable "
                "DEVFLOW_GITHUB_TOKEN or GITHUB_TOKEN."
            )
        return DevflowMCPError(f"GitHub read failed with HTTP {exc.code}.")
    if isinstance(exc, urllib.error.URLError):
        return DevflowMCPError(f"GitHub network read failed: {exc.reason}")
    if isinstance(exc, json.JSONDecodeError):
        return DevflowMCPError("GitHub returned invalid JSON.")
    return DevflowMCPError(f"GitHub read failed: {type(exc).__name__}.")


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

    def _read(self, url: str, *, allow_404: bool = False) -> Any:
        try:
            return self._transport(url, self._headers())
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            raise _translate_read_error(exc) from None
        except DevflowMCPError:
            raise
        except Exception as exc:
            raise _translate_read_error(exc) from None

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
            batch = self._read(url)
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
        issue = self._read(url)
        if not isinstance(issue, dict):
            raise DevflowMCPError("GitHub issue response was not an object.")
        verify_observed_issue_identity(issue, repository, issue_number)
        return issue

    def list_issue_comments(
        self, repository: str, issue_number: int, per_page: int = 100
    ) -> list[dict[str, Any]]:
        if issue_number < 1:
            raise DevflowMCPError("Issue number must be >= 1.")
        comments: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"per_page": per_page, "page": page})
            url = self._repository_url(repository, f"issues/{issue_number}/comments?{query}")
            batch = self._read(url)
            if not isinstance(batch, list):
                raise DevflowMCPError("GitHub Issue comments response was not a list.")
            comments.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < per_page:
                return comments
            page += 1

    def get_file(self, repository: str, path: str) -> dict[str, Any] | None:
        if not isinstance(path, str) or not path.strip():
            raise DevflowMCPError("Repository file path is required.")
        encoded_path = urllib.parse.quote(path, safe="/")
        url = self._repository_url(repository, f"contents/{encoded_path}")
        result = self._read(url, allow_404=True)
        if result is None:
            return None
        if not isinstance(result, dict) or result.get("type") not in (None, "file"):
            raise DevflowMCPError(f"GitHub contents response for {path!r} was not a file.")
        encoded = result.get("content")
        if not isinstance(encoded, str):
            raise DevflowMCPError(f"GitHub contents response for {path!r} has no content.")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=False).decode("utf-8")
        except (UnicodeError, ValueError) as exc:
            raise DevflowMCPError(f"GitHub contents response for {path!r} is not UTF-8 text.") from exc
        return {"content": content, "sha": result.get("sha")}


def _exactly_one(items: Iterable[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], description: str) -> dict[str, Any]:
    matches = [item for item in items if predicate(item)]
    if len(matches) != 1:
        raise DevflowMCPError(f"Expected exactly one {description}; found {len(matches)}.")
    return matches[0]


def _issue_url(issue: dict[str, Any]) -> str:
    return str(issue.get("html_url") or issue.get("url") or "")


TRUSTED_GITHUB_API_HOSTS = frozenset({"api.github.com"})
TRUSTED_GITHUB_WEB_HOSTS = frozenset({"github.com", "www.github.com"})


def _parse_issue_identity_url(value: Any, *, field: str) -> tuple[str, int | None] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.lower() != "https"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or parsed.path.endswith("/")
        or "//" in parsed.path
    ):
        return None

    host = (parsed.hostname or "").lower()
    segments = [urllib.parse.unquote(part) for part in parsed.path.split("/")[1:]]
    try:
        if field == "repository_url":
            if host not in TRUSTED_GITHUB_API_HOSTS or len(segments) != 3 or segments[0] != "repos":
                return None
            return normalize_repository(f"{segments[1]}/{segments[2]}"), None

        if field == "url":
            if (
                host not in TRUSTED_GITHUB_API_HOSTS
                or len(segments) != 5
                or segments[0] != "repos"
                or segments[3] != "issues"
                or not segments[4].isdigit()
            ):
                return None
            return normalize_repository(f"{segments[1]}/{segments[2]}"), int(segments[4])

        if field == "html_url":
            if (
                host not in TRUSTED_GITHUB_WEB_HOSTS
                or len(segments) != 4
                or segments[2] != "issues"
                or not segments[3].isdigit()
            ):
                return None
            return normalize_repository(f"{segments[0]}/{segments[1]}"), int(segments[3])
    except DevflowMCPError:
        return None

    return None


def _identity_mismatch(requested: str, detail: str) -> DevflowMCPError:
    return DevflowMCPError(
        f"Observed Issue identity {detail} does not match requested {requested!r}; "
        "the response may be malformed, transferred, or misrouted."
    )


def verify_observed_issue_identity(issue: dict[str, Any], repository: str, issue_number: int) -> None:
    """Fail closed unless every present observed identity field matches the request."""
    requested = normalize_repository(repository)
    observed_number = issue.get("number")
    if isinstance(observed_number, bool) or not isinstance(observed_number, int) or observed_number != issue_number:
        raise DevflowMCPError(
            f"Observed Issue number {observed_number!r} does not match requested #{issue_number} in {requested}."
        )
    if "pull_request" in issue:
        raise DevflowMCPError(f"{requested}#{issue_number} is a pull request, not an Issue.")

    repositories: set[str] = set()
    issue_numbers: set[int] = set()
    for field in ("repository_url", "url", "html_url"):
        if field not in issue:
            if field == "repository_url":
                raise _identity_mismatch(requested, "repository <missing>")
            continue
        parsed = _parse_issue_identity_url(issue.get(field), field=field)
        if parsed is None:
            raise _identity_mismatch(requested, f"field {field!r} is invalid")
        observed_repository, observed_issue_number = parsed
        repositories.add(observed_repository.casefold())
        if observed_issue_number is not None:
            issue_numbers.add(observed_issue_number)

    if repositories != {requested.casefold()}:
        raise _identity_mismatch(requested, f"repositories {sorted(repositories)!r}")

    if any(number != issue_number for number in issue_numbers):
        raise _identity_mismatch(requested, f"Issue numbers {sorted(issue_numbers)!r}")

    if "repository" in issue:
        repository_object = issue.get("repository")
        if not isinstance(repository_object, dict):
            raise _identity_mismatch(requested, "repository object is invalid")
        repository_values: set[str] = set()
        for key in ("full_name", "nameWithOwner"):
            if key not in repository_object:
                continue
            value = repository_object.get(key)
            if not isinstance(value, str) or not value.strip():
                raise _identity_mismatch(requested, f"repository.{key} is invalid")
            try:
                repository_values.add(normalize_repository(value).casefold())
            except DevflowMCPError:
                raise _identity_mismatch(requested, f"repository.{key} is invalid") from None
        if not repository_values or repository_values != {requested.casefold()}:
            raise _identity_mismatch(requested, f"repository object {sorted(repository_values)!r}")


TRUSTED_AUTHOR_ASSOCIATIONS = github_issue_trust.TRUSTED_AUTHOR_ASSOCIATIONS


def is_trusted_control_author(issue: dict[str, Any]) -> bool:
    """Only directly trusted authors may author canonical Control Issues."""
    return github_issue_trust.is_trusted_issue_author(issue)


def _parse_request_reference(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([^\s/]+/[^\s#]+)#([1-9][0-9]*)", value.strip())
    if not match:
        return None
    try:
        return normalize_repository(match.group(1)), int(match.group(2))
    except DevflowMCPError:
        return None


def _comment_fields(body: Any) -> dict[str, str]:
    if not isinstance(body, str):
        return {}
    fields: dict[str, str] = {}
    for line in body.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            fields[key] = value.strip().strip("`").strip()
    return fields


def _is_accepted_bootstrap_request_lifecycle(issue: dict[str, Any]) -> bool:
    state = str(issue.get("state") or "")
    if state == "open":
        return True
    return state == "closed" and str(issue.get("state_reason") or "") == "completed"


def _is_bootstrap_executor_comment(comment: Any) -> bool:
    if not isinstance(comment, dict):
        return False
    user = comment.get("user")
    app = comment.get("performed_via_github_app")
    return (
        isinstance(user, dict)
        and user.get("login") == "github-actions[bot]"
        and isinstance(app, dict)
        and app.get("slug") == "github-actions"
    )


class DevflowService:
    def __init__(
        self,
        reader: GitHubReader | Any,
        *,
        devflow_repository: str = DEVFLOW_REPOSITORY,
        observed_at_factory: Callable[[], str] | None = None,
    ) -> None:
        self.reader = reader
        self.devflow_repository = normalize_repository(devflow_repository)
        self._observed_at_factory = observed_at_factory or (
            lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        if self.devflow_repository.casefold() != DEVFLOW_REPOSITORY.casefold():
            raise DevflowMCPError(
                f"Repository Control trust requires the canonical devflow repository {DEVFLOW_REPOSITORY!r}."
            )

    def _is_bootstrap_derived_control_trusted(
        self, issue: dict[str, Any], target_repository: str
    ) -> bool:
        """Verify a bot-authored Control through the complete bootstrap chain."""
        try:
            if str(issue.get("state") or "open") != "open":
                return False
            issue_number = issue.get("number")
            if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1:
                return False
            expected_control_url = f"https://github.com/{self.devflow_repository}/issues/{issue_number}"
            if issue.get("html_url") != expected_control_url:
                return False

            control_provenance = parse_control_provenance(str(issue.get("body") or ""))
            if normalize_repository(control_provenance["repository"]) != target_repository:
                return False
            request_identity = _parse_request_reference(control_provenance["request_ref"])
            if not request_identity:
                return False
            request_repository, request_number = request_identity
            if request_repository.casefold() != self.devflow_repository.casefold():
                return False
            parsed_url = _parse_issue_identity_url(control_provenance["request_url"], field="html_url")
            if parsed_url != (self.devflow_repository, request_number):
                return False
            expected_request_url = f"https://github.com/{self.devflow_repository}/issues/{request_number}"
            if control_provenance["request_url"] != expected_request_url:
                return False

            request_issue = self.reader.get_issue(self.devflow_repository, request_number)
            verify_observed_issue_identity(request_issue, self.devflow_repository, request_number)
            if not _is_accepted_bootstrap_request_lifecycle(request_issue):
                return False
            request_title = str(request_issue.get("title") or "")
            if request_title != f"[REPO CREATE] {target_repository.split('/', 1)[1]}":
                return False
            if not is_trusted_control_author(request_issue):
                return False
            request = normalize_request(
                parse_request_body(str(request_issue.get("body") or "")),
                request_title,
            )
            if not request.devflow_managed or not request.create_control:
                return False
            if request.repository.full_name.casefold() != target_repository.casefold():
                return False

            target_file = self.reader.get_file(target_repository, ".github/repository-bootstrap.json")
            if not isinstance(target_file, dict):
                return False
            target_provenance = parse_provenance_document(target_file.get("content"))
            expected_provenance = {
                "schema": "repository-bootstrap-provenance.v1",
                "request_ref": f"{self.devflow_repository}#{request_number}",
                "request_url": expected_request_url,
                "repository": target_repository,
            }
            if target_provenance != expected_provenance:
                return False

            comments = self.reader.list_issue_comments(self.devflow_repository, request_number)
            states: list[tuple[str, bool]] = []
            done_comments: list[dict[str, str]] = []
            for comment in comments:
                fields = _comment_fields(comment.get("body")) if isinstance(comment, dict) else {}
                state = fields.get("Repository-Bootstrap-State")
                if state:
                    states.append((state, _is_bootstrap_executor_comment(comment)))
                if state == "DONE" and _is_bootstrap_executor_comment(comment):
                    done_comments.append(fields)
            if not states or states[-1] != ("DONE", True):
                return False
            expected_repository_url = f"https://github.com/{target_repository}"
            return any(
                fields.get("Repository") == expected_repository_url
                and fields.get("Repository-Control") == expected_control_url
                for fields in done_comments
            )
        except (BootstrapError, DevflowMCPError, KeyError, TypeError, ValueError):
            return False

    def _is_accepted_control(self, issue: dict[str, Any], target_repository: str) -> bool:
        if is_trusted_control_author(issue):
            return True
        return self._is_bootstrap_derived_control_trusted(issue, target_repository)

    def is_repository_control_trusted(
        self,
        issue: dict[str, Any],
        target_repository: str,
    ) -> bool:
        """Return the canonical direct-or-derived Repository Control trust result."""
        normalized = normalize_repository(target_repository)
        return self._is_accepted_control(issue, normalized)

    def list_managed_repositories(self) -> list[str]:
        issues = self.reader.list_issues(self.devflow_repository, state="open")
        repositories: list[str] = []
        for issue in issues:
            title = str(issue.get("title") or "").strip()
            if not title.startswith("[REPO] "):
                continue
            try:
                target = normalize_repository(title.removeprefix("[REPO] ").strip())
            except DevflowMCPError:
                continue
            if not self._is_accepted_control(issue, target):
                continue
            sections = parse_sections(str(issue.get("body") or ""))
            try:
                WORKFLOW_CONTRACT.validate_repository_control_sections(sections)
            except workflow_contract.WorkflowContractError as exc:
                raise DevflowMCPError(str(exc)) from exc
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
        titled = [issue for issue in issues if str(issue.get("title") or "").strip() == title]
        matches = [issue for issue in titled if self._is_accepted_control(issue, normalized)]
        if not matches:
            raise DevflowMCPError(
                f"No open Repository Control Issue titled {title!r}. "
                "Do not infer managed state; onboarding or control reconciliation is required."
            )
        if len(matches) != 1:
            raise DevflowMCPError(f"Expected one open Repository Control Issue titled {title!r}; found {len(matches)}.")
        issue = matches[0]
        sections = parse_sections(str(issue.get("body") or ""), reject_duplicates=True)
        try:
            WORKFLOW_CONTRACT.validate_repository_control_sections(sections)
        except workflow_contract.WorkflowContractError as exc:
            raise DevflowMCPError(str(exc)) from exc
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

    @staticmethod
    def _issue_record_dict(
        record: repository_projection.IssueRecord,
    ) -> dict[str, Any]:
        return {
            "issue_number": record.number,
            "title": record.title,
            "state": record.state,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "url": record.html_url,
            "source_kind": record.source_kind,
            "record_role": record.record_role,
            "type": record.type,
            "work_status": record.work_status,
            "attention_disposition": record.attention_disposition,
            "metadata_error": record.metadata_error,
        }

    @classmethod
    def _repository_projection_dict(
        cls,
        projection: repository_projection.RepositoryProjection,
        *,
        include_records: bool,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "repository": projection.repository,
            "observed_at": projection.observed_at,
            "source_status": projection.source_status,
            "source_freshness": projection.source_freshness,
            "source_error": projection.source_error,
            "open_issue_count": projection.open_issue_count,
            "machine_task_count": projection.machine_task_count,
            "legacy_hint_count": projection.legacy_hint_count,
            "unclassified_count": projection.unclassified_count,
            "invalid_metadata_count": projection.invalid_metadata_count,
            "untrusted_metadata_count": projection.untrusted_metadata_count,
            "machine_type_counts": dict(projection.machine_type_counts),
            "legacy_hint_type_counts": dict(projection.legacy_hint_type_counts),
            "task_records": [
                cls._issue_record_dict(record)
                for record in projection.task_records
            ],
            "ready_tasks": [
                cls._issue_record_dict(record)
                for record in projection.ready_tasks
            ],
            "implementing_tasks": [
                cls._issue_record_dict(record)
                for record in projection.implementing_tasks
            ],
            "newest_open_issue": (
                cls._issue_record_dict(projection.newest_open_issue)
                if projection.newest_open_issue is not None
                else None
            ),
            "recently_active_issue": (
                cls._issue_record_dict(projection.recently_active_issue)
                if projection.recently_active_issue is not None
                else None
            ),
        }
        if include_records:
            result["records"] = [
                cls._issue_record_dict(record)
                for record in projection.records
            ]
        return result

    def _read_repository_projection(
        self,
        repository: str,
        *,
        observed_at: str,
    ) -> repository_projection.RepositoryProjection:
        try:
            issues = self.reader.list_issues(repository, state="open")
        except DevflowMCPError as exc:
            return repository_projection.build_repository_projection(
                repository,
                [],
                observed_at=observed_at,
                source_status="UNAVAILABLE",
                source_error=str(exc),
            )
        return repository_projection.build_repository_projection(
            repository,
            issues,
            observed_at=observed_at,
        )

    def get_repository_projection(self, repository: str) -> dict[str, Any]:
        normalized = normalize_repository(repository)
        self.get_repository_control(normalized)
        observed_at = self._observed_at_factory()
        projection = self._read_repository_projection(
            normalized,
            observed_at=observed_at,
        )
        return self._repository_projection_dict(
            projection,
            include_records=True,
        )

    @staticmethod
    def _human_portfolio_entry_dict(
        entry: human_portfolio.HumanPortfolioEntry,
    ) -> dict[str, Any]:
        return {
            "repository": entry.repository,
            "task_ref": entry.task_ref,
            "entry_ref": entry.entry_ref,
            "disposition": entry.disposition,
            "role": entry.role,
            "source_kind": entry.source_kind,
            "observed_at": entry.observed_at,
            "work_status": entry.work_status,
            "publication_id": entry.publication_id,
            "evidence_freshness": entry.evidence_freshness,
            "evidence_trust": entry.evidence_trust,
        }

    def get_human_portfolio(self, repository: str) -> dict[str, Any]:
        """Return one live read-only Human Portfolio queue for a managed repository."""

        normalized = normalize_repository(repository)
        control = self.get_repository_control(normalized)
        observed_at = self._observed_at_factory()
        projection = self._read_repository_projection(
            normalized,
            observed_at=observed_at,
        )

        control_issue = self.reader.get_issue(
            self.devflow_repository,
            control["issue_number"],
        )
        if (
            str(control_issue.get("title") or "").strip()
            != f"[REPO] {normalized.split('/', 1)[1]}"
            or not self._is_accepted_control(control_issue, normalized)
        ):
            raise DevflowMCPError(
                "Repository Control identity/trust changed during Human Portfolio read."
            )

        control_body = str(control_issue.get("body") or "")
        latest_sections = parse_sections(control_body, reject_duplicates=True)
        try:
            WORKFLOW_CONTRACT.validate_repository_control_sections(latest_sections)
        except workflow_contract.WorkflowContractError as exc:
            raise DevflowMCPError(str(exc)) from exc
        latest_repository = latest_sections.get("Repository", "").strip()
        if latest_repository and normalize_repository(latest_repository) != normalized:
            raise DevflowMCPError(
                "Repository Control repository changed during Human Portfolio read."
            )

        publication_status = "AVAILABLE"
        publication_error: str | None = None
        publications: list[dict[str, Any]] = []
        try:
            publications = reconciliation_publication.parse_publication_projection(
                control_body,
                normalized,
            )
        except ValueError as exc:
            publication_status = "INVALID"
            publication_error = str(exc)

        task_digests: dict[str, str] = {}
        task_errors: list[dict[str, str]] = []
        if publication_status == "AVAILABLE":
            for publication in publications:
                task_ref = str(publication["task_ref"])
                _, raw_number = task_ref.rsplit("#", 1)
                task_number = int(raw_number)
                try:
                    task_issue = self.reader.get_issue(normalized, task_number)
                except DevflowMCPError as exc:
                    task_errors.append(
                        {"task_ref": task_ref, "error": str(exc)}
                    )
                    continue
                if str(task_issue.get("state") or "").casefold() != "open":
                    task_errors.append(
                        {
                            "task_ref": task_ref,
                            "error": "owning task is not open",
                        }
                    )
                    continue
                if "pull_request" in task_issue:
                    task_errors.append(
                        {
                            "task_ref": task_ref,
                            "error": "owning task is a pull request, not an Issue",
                        }
                    )
                    continue
                if not github_issue_trust.is_trusted_issue_author(task_issue):
                    task_errors.append(
                        {
                            "task_ref": task_ref,
                            "error": "owning task author is untrusted",
                        }
                    )
                    continue
                task_body = str(task_issue.get("body") or "")
                if not task_body.strip():
                    task_errors.append(
                        {
                            "task_ref": task_ref,
                            "error": "owning task body is empty",
                        }
                    )
                    continue
                task_digests[task_ref] = (
                    maintenance_sync_check.canonical_body_sha256(task_body)
                )

        source_trust = (
            "VERIFIED" if publication_status == "AVAILABLE" else "UNKNOWN"
        )
        portfolio = human_portfolio.build_repository_human_portfolio(
            projection,
            reconciliation_publications=(
                publications if publication_status == "AVAILABLE" else ()
            ),
            reconciliation_task_body_sha256=task_digests,
            reconciliation_source_trust=source_trust,
        )
        return {
            "schema_version": HUMAN_PORTFOLIO_READ_SCHEMA_VERSION,
            "repository": normalized,
            "observed_at": observed_at,
            "complete": (
                portfolio.complete
                and publication_status == "AVAILABLE"
                and not task_errors
            ),
            "repository_source": {
                "status": portfolio.source_status,
                "freshness": portfolio.source_freshness,
                "error": portfolio.source_error,
            },
            "reconciliation_source": {
                "status": publication_status,
                "trust": source_trust,
                "control_issue_number": control["issue_number"],
                "control_url": control["url"],
                "error": publication_error,
                "task_errors": task_errors,
            },
            "entries": [
                self._human_portfolio_entry_dict(entry)
                for entry in portfolio.entries
            ],
        }

    def get_portfolio_projection(self) -> dict[str, Any]:
        observed_at = self._observed_at_factory()
        repositories = self.list_managed_repositories()
        projections = [
            self._read_repository_projection(
                repository,
                observed_at=observed_at,
            )
            for repository in repositories
        ]
        compact = [
            self._repository_projection_dict(
                projection,
                include_records=False,
            )
            for projection in projections
        ]
        return {
            "observed_at": observed_at,
            "repository_count": len(projections),
            "source_unavailable_count": sum(
                1
                for projection in projections
                if projection.source_status == "UNAVAILABLE"
            ),
            "open_issue_count": sum(
                projection.open_issue_count
                for projection in projections
            ),
            "machine_task_count": sum(
                projection.machine_task_count
                for projection in projections
            ),
            "legacy_hint_count": sum(
                projection.legacy_hint_count
                for projection in projections
            ),
            "unclassified_count": sum(
                projection.unclassified_count
                for projection in projections
            ),
            "invalid_metadata_count": sum(
                projection.invalid_metadata_count
                for projection in projections
            ),
            "untrusted_metadata_count": sum(
                projection.untrusted_metadata_count
                for projection in projections
            ),
            "repositories": compact,
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
        verify_observed_issue_identity(issue, normalized, issue_number)
        body = str(issue.get("body") or "")
        return {
            "repository": normalized,
            "issue_number": int(issue["number"]),
            "title": str(issue.get("title") or ""),
            "state": str(issue.get("state") or ""),
            "url": _issue_url(issue),
            "body": body,
            "sections": parse_sections(body),
        }

    def get_sync_health(self) -> dict[str, Any]:
        issues = self.reader.list_issues(self.devflow_repository, state="all")
        titled = [item for item in issues if str(item.get("title") or "").strip() == HEALTH_TITLE]
        trusted = [item for item in titled if is_trusted_control_author(item)]
        ignored = sorted(int(item.get("number") or 0) for item in titled if not is_trusted_control_author(item))
        if not trusted:
            raise DevflowMCPError(
                f"No trusted Sync Health Issue titled {HEALTH_TITLE!r}"
                + (f"; ignored untrusted candidates {ignored}." if ignored else ".")
            )
        if len(trusted) > 1:
            # Prefer the single open trusted Issue over closed history.
            trusted = [item for item in trusted if str(item.get("state") or "") == "open"]
        issue = _exactly_one(trusted, lambda item: True, "trusted Sync Health Issue")
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
            "ignored_untrusted_candidates": ignored,
            "run": sections.get("Run", ""),
            "direct_verification_requirement": sections.get("Direct Verification Requirement", ""),
            "sections": sections,
        }


def default_service() -> DevflowService:
    repository = os.environ.get("DEVFLOW_REPOSITORY", DEVFLOW_REPOSITORY).strip() or DEVFLOW_REPOSITORY
    return DevflowService(GitHubReader.from_env(), devflow_repository=repository)
