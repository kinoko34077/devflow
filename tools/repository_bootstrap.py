from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = "repository-bootstrap.v1"
PROVENANCE_SCHEMA = "repository-bootstrap-provenance.v1"
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
    """Invalid, ambiguous, or unsupported repository bootstrap input."""


class GitHubApiError(RuntimeError):
    """Bounded GitHub transport/API error that never embeds credentials."""


class BootstrapFailure(BootstrapError):
    def __init__(
        self,
        stage: str,
        message: str,
        *,
        safe_retry: str,
        resources: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.safe_retry = safe_retry
        self.resources = resources


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
    license: None
    issues: tuple[InitialIssue, ...]
    create_control: bool
    work_status: str
    repository_state: str
    next_action: str


@dataclass(frozen=True)
class BootstrapContext:
    request_ref: str
    request_url: str
    devflow_repo: str
    request_issue_number: int
    request_title: str
    author_association: str


@dataclass(frozen=True)
class BootstrapResult:
    repository_url: str
    head_sha: str
    issue_urls: tuple[str, ...]
    control_url: str | None
    resources: tuple[str, ...]


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
    if name in {".", ".."} or name != name.strip() or REPOSITORY_NAME_RE.fullmatch(name) is None:
        raise BootstrapError("repository.name is invalid")
    expected_title = f"[REPO CREATE] {name}"
    if issue_title != expected_title:
        raise BootstrapError(f"Issue title must be exactly {expected_title!r}")
    description = repository.get("description", "")
    if not isinstance(description, str):
        raise BootstrapError("repository.description must be a string")
    visibility = _enum(repository.get("visibility", "private"), "repository.visibility", VISIBILITIES)

    classification = _mapping(raw.get("classification"), "classification")
    kind = _string(classification.get("kind"), "classification.kind")
    priority = _enum(classification.get("priority"), "classification.priority", PRIORITIES)
    risk = _enum(classification.get("risk"), "classification.risk", RISKS)

    bootstrap = _mapping(raw.get("bootstrap", {}), "bootstrap")
    template = _enum(bootstrap.get("template", "minimal"), "bootstrap.template", TEMPLATES)
    if "devflow_managed" in bootstrap:
        devflow_managed = _boolean(bootstrap.get("devflow_managed"), "bootstrap.devflow_managed")
    else:
        devflow_managed = name not in EXCLUDED_REPOSITORIES
    if name in EXCLUDED_REPOSITORIES and devflow_managed:
        raise BootstrapError(f"repository {name!r} is excluded from devflow management")

    initial = _mapping(raw.get("initial_content", {}), "initial_content")
    readme = initial.get("readme", f"# {name}\n")
    if not isinstance(readme, str):
        raise BootstrapError("initial_content.readme must be a string")
    specification = _optional_string(initial.get("specification"), "initial_content.specification")
    if initial.get("license") is not None:
        raise BootstrapError("initial_content.license is unsupported in repository-bootstrap.v1; use null/omit")

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
        issues.append(
            InitialIssue(
                key=key,
                title=_string(issue.get("title"), f"issues[{index}].title"),
                body=_string(issue.get("body"), f"issues[{index}].body", allow_empty=True),
                role=_optional_string(issue.get("role"), f"issues[{index}].role"),
            )
        )

    devflow = _mapping(raw.get("devflow", {}), "devflow")
    create_control = _boolean(devflow.get("create_control", devflow_managed), "devflow.create_control")
    if create_control and not devflow_managed:
        raise BootstrapError("devflow.create_control requires bootstrap.devflow_managed=true")
    work_status = _enum(devflow.get("work_status", "WORK_ORDER_READY"), "devflow.work_status", WORK_STATES)
    repository_state = _enum(devflow.get("repository_state", "ACTIVE"), "devflow.repository_state", REPOSITORY_STATES)
    next_action = _string(
        devflow.get("next_action", "[SPECIFY] Define the first implementation slice."),
        "devflow.next_action",
    )

    return BootstrapRequest(
        schema=schema,
        repository=RepositorySpec(owner, name, description, visibility),
        kind=kind,
        priority=priority,
        risk=risk,
        template=template,
        devflow_managed=devflow_managed,
        readme=readme,
        specification=specification,
        license=None,
        issues=tuple(issues),
        create_control=create_control,
        work_status=work_status,
        repository_state=repository_state,
        next_action=next_action,
    )


def is_trusted_association(value: str) -> bool:
    return value in TRUSTED_ASSOCIATIONS


def _provenance(context: BootstrapContext, full_name: str) -> str:
    return json.dumps(
        {
            "schema": PROVENANCE_SCHEMA,
            "request_ref": context.request_ref,
            "request_url": context.request_url,
            "repository": full_name,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _issue_marker(context: BootstrapContext, key: str) -> str:
    return f"<!-- repository-bootstrap:{context.request_ref}:issue:{key} -->"


def _repository_field_matches(body: str, full_name: str) -> bool:
    return f"## Repository\n\n`{full_name}`" in (body or "").replace("\r\n", "\n")


class BootstrapExecutor:
    """Deterministic ensure-oriented provisioning over narrow GitHub adapters."""

    def __init__(self, repository_api: Any, devflow_api: Any) -> None:
        self.repository_api = repository_api
        self.devflow_api = devflow_api

    def _comment(self, context: BootstrapContext, body: str) -> None:
        self.devflow_api.comment_issue(context.devflow_repo, context.request_issue_number, body)

    def _raise_failure(
        self,
        context: BootstrapContext,
        stage: str,
        message: str,
        *,
        safe_retry: str,
        resources: list[str],
    ) -> None:
        lines = [
            "Repository-Bootstrap-State: FAILED",
            f"Stage: {stage}",
            f"Safe-Retry: {safe_retry}",
            "Created/Observed Resources:",
            *(f"- {item}" for item in resources),
            f"Failure: {message}",
            "Next-Action: Re-read this request and observed live resources before retrying.",
        ]
        try:
            self._comment(context, "\n".join(lines))
        except Exception:
            pass
        raise BootstrapFailure(stage, message, safe_retry=safe_retry, resources=tuple(resources))

    def _call(
        self,
        context: BootstrapContext,
        stage: str,
        resources: list[str],
        operation: Any,
        *,
        safe_retry: str = "yes",
    ) -> Any:
        try:
            return operation()
        except BootstrapFailure:
            raise
        except Exception as exc:
            self._raise_failure(
                context,
                stage,
                f"{type(exc).__name__}: {exc}",
                safe_retry=safe_retry,
                resources=resources,
            )

    @staticmethod
    def _find_exact_title(api: Any, full_name: str, title: str) -> list[dict[str, Any]]:
        finder = getattr(api, "find_issues_by_exact_title", None)
        if callable(finder):
            return list(finder(full_name, title, state="open"))
        return [
            issue
            for issue in api.list_issues(full_name, state="open")
            if issue.get("title") == title and "pull_request" not in issue
        ]

    def execute(self, request: BootstrapRequest, context: BootstrapContext) -> BootstrapResult:
        resources: list[str] = []
        if not is_trusted_association(context.author_association):
            self._raise_failure(
                context,
                "VALIDATION",
                "request author association is not trusted",
                safe_retry="after-human-decision",
                resources=resources,
            )
        if context.request_title != f"[REPO CREATE] {request.repository.name}":
            self._raise_failure(
                context,
                "VALIDATION",
                "request context title does not match normalized repository name",
                safe_retry="after-human-decision",
                resources=resources,
            )

        self._call(
            context,
            "FINALIZE",
            resources,
            lambda: self._comment(
                context,
                "Repository-Bootstrap-State: PROVISIONING\n"
                f"Request: {context.request_ref}\n"
                f"Repository: `{request.repository.full_name}`",
            ),
        )

        full_name = request.repository.full_name
        repo = self._call(context, "REPOSITORY", resources, lambda: self.repository_api.get_repository(full_name))
        repository_was_created = repo is None
        if repo is None:
            repo = self._call(
                context,
                "REPOSITORY",
                resources,
                lambda: self.repository_api.create_repository(
                    request.repository.owner,
                    request.repository.name,
                    request.repository.description,
                    request.repository.visibility,
                ),
            )
            observed_full_name = repo.get("full_name") if isinstance(repo, dict) else None
            if not isinstance(observed_full_name, str) or observed_full_name.lower() != full_name.lower():
                self._raise_failure(
                    context,
                    "REPOSITORY",
                    "created repository identity does not match request",
                    safe_retry="after-human-decision",
                    resources=resources,
                )
        else:
            observed_full_name = repo.get("full_name") if isinstance(repo, dict) else None
            if observed_full_name and observed_full_name.lower() != full_name.lower():
                self._raise_failure(
                    context,
                    "REPOSITORY",
                    "observed repository identity does not match request",
                    safe_retry="after-human-decision",
                    resources=resources,
                )
        repository_url = repo.get("html_url") or f"https://github.com/{full_name}"
        resources.append(f"repository:{repository_url}")

        provenance_path = ".github/repository-bootstrap.json"
        expected_provenance = _provenance(context, full_name)
        existing_provenance = self._call(
            context,
            "PROVENANCE",
            resources,
            lambda: self.repository_api.get_file(full_name, provenance_path),
            safe_retry="after-human-decision" if repository_was_created else "yes",
        )
        if existing_provenance is None:
            if not repository_was_created:
                self._raise_failure(
                    context,
                    "REPOSITORY",
                    "existing repository has no matching bootstrap provenance",
                    safe_retry="after-human-decision",
                    resources=resources,
                )
            self._call(
                context,
                "PROVENANCE",
                resources,
                lambda: self.repository_api.create_file(
                    full_name,
                    provenance_path,
                    expected_provenance,
                    f"chore: record repository bootstrap provenance ({context.request_ref})",
                ),
                safe_retry="after-human-decision",
            )
        elif existing_provenance.get("content") != expected_provenance:
            self._raise_failure(
                context,
                "REPOSITORY",
                "existing repository bootstrap provenance does not match request",
                safe_retry="after-human-decision",
                resources=resources,
            )
        resources.append(f"file:{provenance_path}")

        seed_files: list[tuple[str, str]] = [("README.md", request.readme)]
        if request.specification is not None:
            seed_files.append(("docs/SPECIFICATION.md", request.specification))
        for path, content in seed_files:
            existing = self._call(
                context,
                "SEED",
                resources,
                lambda path=path: self.repository_api.get_file(full_name, path),
            )
            if existing is None:
                self._call(
                    context,
                    "SEED",
                    resources,
                    lambda path=path, content=content: self.repository_api.create_file(
                        full_name,
                        path,
                        content,
                        f"chore: add bootstrap seed {path} ({context.request_ref})",
                    ),
                )
            resources.append(f"file:{path}")

        head_sha = self._call(
            context,
            "SEED",
            resources,
            lambda: self.repository_api.get_default_branch_head(full_name),
        )
        resources.append(f"head:{head_sha}")

        owner_issues = self._call(
            context,
            "ISSUES",
            resources,
            lambda: self.repository_api.list_issues(full_name, state="all"),
        )
        issue_urls: list[str] = []
        issue_refs: list[str] = []
        for requested_issue in request.issues:
            marker = _issue_marker(context, requested_issue.key)
            matches = [
                issue
                for issue in owner_issues
                if marker in (issue.get("body") or "") and "pull_request" not in issue
            ]
            if len(matches) > 1:
                self._raise_failure(
                    context,
                    "ISSUES",
                    f"multiple Issues match bootstrap key {requested_issue.key!r}",
                    safe_retry="after-human-decision",
                    resources=resources,
                )
            if matches:
                issue = matches[0]
                if issue.get("title") != requested_issue.title:
                    self._raise_failure(
                        context,
                        "ISSUES",
                        f"existing Issue for key {requested_issue.key!r} has conflicting title",
                        safe_retry="after-human-decision",
                        resources=resources,
                    )
            else:
                body_parts = [marker]
                if requested_issue.role:
                    body_parts.extend(["", f"Bootstrap-Role: `{requested_issue.role}`"])
                body_parts.extend(["", requested_issue.body])
                issue = self._call(
                    context,
                    "ISSUES",
                    resources,
                    lambda requested_issue=requested_issue, body="\n".join(body_parts): self.repository_api.create_issue(
                        full_name, requested_issue.title, body
                    ),
                )
                owner_issues.append(issue)
            issue_url = issue.get("html_url") or ""
            issue_urls.append(issue_url)
            issue_refs.append(f"- `{full_name}#{issue.get('number')}` — {requested_issue.title}")
            resources.append(f"issue:{issue_url}")

        control_url: str | None = None
        if request.create_control:
            control_title = f"[REPO] {request.repository.name}"
            controls = self._call(
                context,
                "CONTROL",
                resources,
                lambda: self._find_exact_title(self.devflow_api, context.devflow_repo, control_title),
            )
            if len(controls) > 1:
                self._raise_failure(
                    context,
                    "CONTROL",
                    f"multiple open Repository Controls exist for {full_name}",
                    safe_retry="after-human-decision",
                    resources=resources,
                )
            if controls:
                control = controls[0]
                if not _repository_field_matches(control.get("body") or "", full_name):
                    self._raise_failure(
                        context,
                        "CONTROL",
                        "existing Repository Control title points to a different repository",
                        safe_retry="after-human-decision",
                        resources=resources,
                    )
            else:
                active_work = "\n".join(issue_refs) if issue_refs else "No repository-local bootstrap Issue was requested."
                entry_points = ["- `README.md`"]
                if request.specification is not None:
                    entry_points.append("- `docs/SPECIFICATION.md`")
                entry_points.extend(issue_refs)
                control_body = (
                    f"## Repository\n\n`{full_name}`\n\n"
                    f"## Work Status\n\n`{request.work_status}`\n\n"
                    "## Type\n\n`FEATURE`\n\n"
                    f"## Repository State\n\n`{request.repository_state}`\n\n"
                    f"## Priority\n\n`{request.priority}`\n\n"
                    f"## Risk\n\n`{request.risk}`\n\n"
                    f"## Audit SHA\n\n`{head_sha}`\n\n"
                    f"## Active Work\n\n{active_work}\n\n"
                    f"## Next Action\n\n`{request.next_action}`\n\n"
                    "## Canonical Entry Points\n\n"
                    + "\n".join(entry_points)
                    + "\n\n## Detailed Current State\n\n"
                    f"Repository was initialized through `{context.request_ref}` using `{SCHEMA_VERSION}`. "
                    f"Accepted initial head is `{head_sha}`. No implementation beyond the requested bootstrap seed is implied by this Control.\n\n"
                    "## Control Notes\n\n"
                    f"Cross-repository routing summary only. Bootstrap request: {context.request_url}. "
                    f"Repository kind recorded by the request: `{request.kind}`. Detailed technical truth belongs in `{full_name}`."
                )
                control = self._call(
                    context,
                    "CONTROL",
                    resources,
                    lambda: self.devflow_api.create_issue(context.devflow_repo, control_title, control_body),
                )
            control_url = control.get("html_url") or ""
            resources.append(f"control:{control_url}")

        done_lines = [
            "Repository-Bootstrap-State: DONE",
            f"Repository: {repository_url}",
            f"Initial-Accepted-SHA: `{head_sha}`",
            *(f"Initial-Issue: {url}" for url in issue_urls),
        ]
        if control_url:
            done_lines.append(f"Repository-Control: {control_url}")
        self._call(
            context,
            "FINALIZE",
            resources,
            lambda: self._comment(context, "\n".join(done_lines)),
        )
        return BootstrapResult(
            repository_url=repository_url,
            head_sha=head_sha,
            issue_urls=tuple(issue_urls),
            control_url=control_url,
            resources=tuple(resources),
        )


class GitHubApi:
    """Narrow GitHub REST adapter for repository-bootstrap operations only."""

    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        timeout: float = 30.0,
    ) -> None:
        if not token:
            raise BootstrapError("GitHub token must not be empty")
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._api_version = api_version
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        allow_404: bool = False,
    ) -> Any:
        url = f"{self._api_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": self._api_version,
                "User-Agent": "kinoko34077-devflow-repository-bootstrap",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if allow_404 and code == 404:
                return None
            raise GitHubApiError(f"{method} {path} failed with HTTP {code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubApiError(f"{method} {path} transport failed: {type(exc).__name__}") from exc
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubApiError(f"{method} {path} returned malformed JSON") from exc

    @staticmethod
    def _repo_path(full_name: str) -> str:
        owner, sep, name = full_name.partition("/")
        if not sep or not owner or not name or "/" in name:
            raise BootstrapError("repository full name must be owner/name")
        return f"{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(name, safe='')}"

    def get_repository(self, full_name: str) -> dict[str, Any] | None:
        return self._request("GET", f"/repos/{self._repo_path(full_name)}", allow_404=True)

    def create_repository(
        self,
        owner: str,
        name: str,
        description: str,
        visibility: str,
    ) -> dict[str, Any]:
        if owner != ALLOWED_OWNER:
            raise BootstrapError(f"unsupported repository owner: {owner}")
        identity = self._request("GET", "/user")
        login = identity.get("login") if isinstance(identity, dict) else None
        if not isinstance(login, str) or login.lower() != owner.lower():
            raise BootstrapError("repository bootstrap credential owner does not match requested owner")
        result = self._request(
            "POST",
            "/user/repos",
            {
                "name": name,
                "description": description,
                "private": visibility == "private",
                "has_issues": True,
                "auto_init": False,
            },
        )
        if not isinstance(result, dict):
            raise GitHubApiError("create repository returned malformed response")
        expected = f"{owner}/{name}"
        observed = result.get("full_name")
        if not isinstance(observed, str) or observed.lower() != expected.lower():
            raise GitHubApiError("create repository returned mismatched repository identity")
        return result

    def get_file(self, full_name: str, path: str) -> dict[str, Any] | None:
        encoded_path = urllib.parse.quote(path, safe="/")
        result = self._request(
            "GET",
            f"/repos/{self._repo_path(full_name)}/contents/{encoded_path}",
            allow_404=True,
        )
        if result is None:
            return None
        if not isinstance(result, dict) or result.get("type") not in (None, "file"):
            raise GitHubApiError(f"contents response for {path} is not a file")
        encoded = result.get("content")
        if not isinstance(encoded, str):
            raise GitHubApiError(f"contents response for {path} has no content")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=False).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise GitHubApiError(f"contents response for {path} is not UTF-8 text") from exc
        return {"content": content, "sha": result.get("sha")}

    def create_file(self, full_name: str, path: str, content: str, message: str) -> dict[str, Any]:
        encoded_path = urllib.parse.quote(path, safe="/")
        result = self._request(
            "PUT",
            f"/repos/{self._repo_path(full_name)}/contents/{encoded_path}",
            {
                "message": message,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            },
        )
        if not isinstance(result, dict):
            raise GitHubApiError(f"create file {path} returned malformed response")
        commit = result.get("commit") or {}
        return {"commit_sha": commit.get("sha")}

    def get_default_branch_head(self, full_name: str) -> str:
        repo = self.get_repository(full_name)
        if not isinstance(repo, dict):
            raise GitHubApiError(f"repository {full_name} disappeared during bootstrap")
        branch = repo.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise GitHubApiError(f"repository {full_name} has no default branch after seed")
        branch_result = self._request(
            "GET",
            f"/repos/{self._repo_path(full_name)}/branches/{urllib.parse.quote(branch, safe='')}",
        )
        try:
            sha = branch_result["commit"]["sha"]
        except (TypeError, KeyError) as exc:
            raise GitHubApiError("branch response has no commit SHA") from exc
        if not isinstance(sha, str) or not sha:
            raise GitHubApiError("branch response has invalid commit SHA")
        return sha

    def list_issues(self, full_name: str, state: str = "all") -> list[dict[str, Any]]:
        if state not in {"open", "closed", "all"}:
            raise BootstrapError(f"unsupported Issue state: {state}")
        results: list[dict[str, Any]] = []
        for page in range(1, 101):
            batch = self._request(
                "GET",
                f"/repos/{self._repo_path(full_name)}/issues?state={state}&per_page=100&page={page}",
            )
            if not isinstance(batch, list):
                raise GitHubApiError("list issues returned malformed response")
            results.extend(
                item for item in batch if isinstance(item, dict) and "pull_request" not in item
            )
            if len(batch) < 100:
                return results
        raise GitHubApiError("Issue pagination exceeded bootstrap safety limit")

    def find_issues_by_exact_title(
        self, full_name: str, title: str, state: str = "open"
    ) -> list[dict[str, Any]]:
        if state not in {"open", "closed", "all"}:
            raise BootstrapError(f"unsupported Issue state: {state}")
        state_qualifier = f"is:{state}" if state != "all" else ""
        query = f'repo:{full_name} is:issue {state_qualifier} in:title "{title}"'.strip()
        encoded_query = urllib.parse.urlencode({"q": query, "per_page": 100})
        result = self._request("GET", f"/search/issues?{encoded_query}")
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise GitHubApiError("Issue search returned malformed response")
        return [
            item
            for item in result["items"]
            if isinstance(item, dict)
            and item.get("title") == title
            and "pull_request" not in item
        ]

    def create_issue(self, full_name: str, title: str, body: str) -> dict[str, Any]:
        result = self._request(
            "POST",
            f"/repos/{self._repo_path(full_name)}/issues",
            {"title": title, "body": body},
        )
        if not isinstance(result, dict):
            raise GitHubApiError("create Issue returned malformed response")
        return result

    def comment_issue(self, full_name: str, issue_number: int, body: str) -> dict[str, Any]:
        if not isinstance(issue_number, int) or issue_number <= 0:
            raise BootstrapError("Issue number must be a positive integer")
        result = self._request(
            "POST",
            f"/repos/{self._repo_path(full_name)}/issues/{issue_number}/comments",
            {"body": body},
        )
        if not isinstance(result, dict):
            raise GitHubApiError("create Issue comment returned malformed response")
        return result
