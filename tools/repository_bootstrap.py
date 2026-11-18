from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from .github_issue_trust import is_trusted_issue_author
except ImportError:  # direct module execution
    from github_issue_trust import is_trusted_issue_author

try:
    from .github_api_http_diagnostics import MAX_ERROR_BODY_BYTES, summarize_github_http_error
except ImportError:  # direct script execution
    from github_api_http_diagnostics import MAX_ERROR_BODY_BYTES, summarize_github_http_error

try:
    from . import workflow_contract
except ImportError:  # direct module execution
    import workflow_contract

WORKFLOW_CONTRACT = workflow_contract.WORKFLOW_CONTRACT


SCHEMA_VERSION = "repository-bootstrap.v1"
PROVENANCE_SCHEMA = "repository-bootstrap-provenance.v1"
START_MARKER = "<!-- repository-bootstrap:v1:start -->"
END_MARKER = "<!-- repository-bootstrap:v1:end -->"
CONTROL_PROVENANCE_SCHEMA = "repository-bootstrap-control.v1"
CONTROL_START_MARKER = "<!-- repository-bootstrap-control:v1:start -->"
CONTROL_END_MARKER = "<!-- repository-bootstrap-control:v1:end -->"
ALLOWED_OWNER = "kinoko34077"
EXCLUDED_REPOSITORIES = WORKFLOW_CONTRACT.excluded_repositories
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
VISIBILITIES = frozenset({"private", "public"})
PRIORITIES = WORKFLOW_CONTRACT.priorities
RISKS = WORKFLOW_CONTRACT.risks
WORK_STATES = WORKFLOW_CONTRACT.work_states
REPOSITORY_STATES = WORKFLOW_CONTRACT.repository_states
TEMPLATES = frozenset({"minimal"})
STANDARD_FEATURES = frozenset({"repo_native_dispatch", "generated-artifact-writeback"})
MAIN_PROTECTION_POLICY = "public-only-v1"
REQUIRED_MANAGED_STANDARD_FEATURES = frozenset(
    {"repo_native_dispatch", "generated-artifact-writeback"}
)
STANDARD_FEATURE_MANIFEST_PATH = ".devflow/standard-features.json"
STANDARD_ROLLOUT_CALLER_PATH = ".github/workflows/verified-artifacts-rollout.yml"
VERIFY_WORKFLOW_PATH = ".github/workflows/verify.yml"
LEGACY_REPO_NATIVE_DISPATCH_SHA256 = "8f5fb94577be6d03f14faed8a39ee35bcc65058a93ec2a60df51c0678ec460f0"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
ISSUE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class BootstrapError(ValueError):
    """Invalid, ambiguous, or unsupported repository bootstrap input."""


class GitHubApiError(RuntimeError):
    """Bounded GitHub transport/API error that never embeds credentials."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
    repo_native_dispatch: bool
    generated_artifact_writeback: bool
    main_protection: str | None
    standard_features: tuple[str, ...]
    standard_features_declared: bool
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
    author: Mapping[str, Any]
    devflow_sha: str


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


def _reject_unknown_keys(value: Mapping[str, Any], field: str, allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BootstrapError(
            f"{field} contains unsupported field(s): {', '.join(unknown)}"
        )


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
    _reject_unknown_keys(raw, "request", {"schema", "repository", "classification", "bootstrap", "initial_content", "issues", "devflow"})
    schema = _string(raw.get("schema"), "schema")
    if schema != SCHEMA_VERSION:
        raise BootstrapError(f"unsupported schema: {schema}")

    repository = _mapping(raw.get("repository"), "repository")
    _reject_unknown_keys(repository, "repository", {"owner", "name", "description", "visibility"})
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
    _reject_unknown_keys(classification, "classification", {"kind", "priority", "risk"})
    kind = _string(classification.get("kind"), "classification.kind")
    priority = _enum(classification.get("priority"), "classification.priority", PRIORITIES)
    risk = _enum(classification.get("risk"), "classification.risk", RISKS)

    bootstrap = _mapping(raw.get("bootstrap", {}), "bootstrap")
    _reject_unknown_keys(
        bootstrap, "bootstrap",
        {"template", "devflow_managed", "repo_native_dispatch", "standard_features", "main_protection"},
    )
    template = _enum(bootstrap.get("template", "minimal"), "bootstrap.template", TEMPLATES)
    if "devflow_managed" in bootstrap:
        devflow_managed = _boolean(bootstrap.get("devflow_managed"), "bootstrap.devflow_managed")
    else:
        devflow_managed = name not in EXCLUDED_REPOSITORIES
    if name in EXCLUDED_REPOSITORIES and devflow_managed:
        raise BootstrapError(f"repository {name!r} is excluded from devflow management")
    # The optional feature list is absent from historical v1 Issues. Keep those
    # requests replay-compatible; current emitters opt into the standard set.
    standard_features_declared = "standard_features" in bootstrap
    if standard_features_declared:
        raw_features = bootstrap["standard_features"]
        if not isinstance(raw_features, list) or any(not isinstance(item, str) for item in raw_features):
            raise BootstrapError("bootstrap.standard_features must be an array of feature IDs")
        if len(raw_features) != len(set(raw_features)):
            raise BootstrapError("bootstrap.standard_features contains duplicate feature IDs")
        unknown_features = sorted(set(raw_features) - STANDARD_FEATURES)
        if unknown_features:
            raise BootstrapError(
                "bootstrap.standard_features contains unsupported feature(s): "
                + ", ".join(unknown_features)
            )
        standard_features = tuple(sorted(raw_features))
        repo_native_dispatch = "repo_native_dispatch" in standard_features
        if "repo_native_dispatch" in bootstrap and _boolean(
            bootstrap["repo_native_dispatch"], "bootstrap.repo_native_dispatch"
        ) != repo_native_dispatch:
            raise BootstrapError("bootstrap.repo_native_dispatch conflicts with standard_features")
    else:
        # Absent means legacy v1 minimal behavior: retries do not add the new
        # feature manifest or mutate the historical receiver.
        repo_native_dispatch = _boolean(
            bootstrap.get("repo_native_dispatch", False), "bootstrap.repo_native_dispatch"
        )
        standard_features = ("repo_native_dispatch",) if repo_native_dispatch else ()
    generated_artifact_writeback = "generated-artifact-writeback" in standard_features
    if (
        standard_features_declared
        and devflow_managed
        and not REQUIRED_MANAGED_STANDARD_FEATURES.issubset(standard_features)
    ):
        raise BootstrapError(
            "managed bootstrap.standard_features must include the standard defaults: "
            + ", ".join(sorted(REQUIRED_MANAGED_STANDARD_FEATURES))
        )
    if generated_artifact_writeback and not repo_native_dispatch:
        raise BootstrapError("generated-artifact-writeback requires repo_native_dispatch")
    if standard_features and not devflow_managed:
        raise BootstrapError("bootstrap.standard_features requires devflow_managed=true")
    if repo_native_dispatch and not devflow_managed:
        raise BootstrapError("bootstrap.repo_native_dispatch requires devflow_managed=true")
    main_protection = None
    if "main_protection" in bootstrap:
        main_protection = _enum(
            bootstrap["main_protection"],
            "bootstrap.main_protection",
            {MAIN_PROTECTION_POLICY},
        )
        if not devflow_managed:
            raise BootstrapError("bootstrap.main_protection requires devflow_managed=true")

    initial = _mapping(raw.get("initial_content", {}), "initial_content")
    _reject_unknown_keys(initial, "initial_content", {"readme", "specification", "license"})
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
        _reject_unknown_keys(issue, f"issues[{index}]", {"key", "title", "body", "role"})
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
    _reject_unknown_keys(devflow, "devflow", {"create_control", "work_status", "repository_state", "next_action"})
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
        repo_native_dispatch=repo_native_dispatch,
        generated_artifact_writeback=generated_artifact_writeback,
        main_protection=main_protection,
        standard_features=standard_features,
        standard_features_declared=standard_features_declared,
        readme=readme,
        specification=specification,
        license=None,
        issues=tuple(issues),
        create_control=create_control,
        work_status=work_status,
        repository_state=repository_state,
        next_action=next_action,
    )


def standard_feature_manifest(request: BootstrapRequest) -> dict[str, Any]:
    """Describe installed capabilities without granting effectful authority."""
    features: list[dict[str, Any]] = []
    if request.generated_artifact_writeback:
        features.append({
            "id": "generated-artifact-writeback",
            "status": "INSTALLED",
            "entrypoint": ".github/workflows/kinotch-repo-command.yml",
            "dry_run_caller": STANDARD_ROLLOUT_CALLER_PATH,
            "recipe_registry": "tools.generated_artifact_rollout.select_fixed_recipe",
            "writer": "tools.generated_artifact_writer.verified_writeback",
            "no_output": {
                "status": "NOT_APPLICABLE",
                "reason": "NO_GENERATED_OUTPUT",
            },
            "effectful_write": {
                "enabled_by_bootstrap": False,
                "dry_run_enabled_by_bootstrap": True,
                "human_gate_required": True,
                "required_job_permissions": [
                    "contents:write",
                    "actions:read",
                    "pull-requests:read",
                ],
            },
        })
    return {
        "schema": "devflow-standard-features.v1",
        "repository": request.repository.full_name,
        "standard_features": list(request.standard_features),
        "features": features,
    }


def render_standard_rollout_caller(devflow_sha: str) -> str:
    """Render the shared dry-run caller pinned to the exact Bootstrap source SHA."""
    if not isinstance(devflow_sha, str) or not SHA_RE.fullmatch(devflow_sha):
        raise BootstrapError("GITHUB_SHA must be a 40-character lowercase commit SHA")
    path = Path(__file__).resolve().parents[1] / "templates/bootstrap/verified-artifacts-rollout.yml"
    template = path.read_text(encoding="utf-8")
    if template.count("<DEVFLOW_SHA>") != 2:
        raise BootstrapError("trusted generated-artifact caller template must contain exactly two SHA pins")
    return template.replace("<DEVFLOW_SHA>", devflow_sha)


def is_standard_rollout_caller(content: Any) -> bool:
    """Recognize the exact current read-only caller at any prior immutable SHA pin."""
    if not isinstance(content, str):
        return False
    try:
        template = (
            Path(__file__).resolve().parents[1]
            / "templates/bootstrap/verified-artifacts-rollout.yml"
        ).read_text(encoding="utf-8")
    except OSError:
        return False
    match = re.search(r"(?m)^      devflow_sha: ([0-9a-f]{40})$", content)
    if match is None:
        return False
    sha = match.group(1)
    return (
        content.count(sha) == 2
        and template.count("<DEVFLOW_SHA>") == 2
        and content.replace(sha, "<DEVFLOW_SHA>") == template
    )


def is_trusted_association(value: str) -> bool:
    """Legacy metadata helper; association is not an authorization grant."""
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


def parse_provenance_document(content: str) -> dict[str, str]:
    """Parse the exact provenance document persisted in the target repository."""
    if not isinstance(content, str):
        raise BootstrapError("bootstrap provenance must be text")
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError as exc:
        raise BootstrapError("bootstrap provenance is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise BootstrapError("bootstrap provenance must be an object")
    expected_keys = {"schema", "request_ref", "request_url", "repository"}
    if set(decoded) != expected_keys:
        raise BootstrapError("bootstrap provenance has unsupported or missing fields")
    result: dict[str, str] = {}
    for key in expected_keys:
        value = decoded.get(key)
        if not isinstance(value, str) or not value.strip():
            raise BootstrapError(f"bootstrap provenance field {key!r} must be a non-empty string")
        result[key] = value
    if result["schema"] != PROVENANCE_SCHEMA:
        raise BootstrapError("unsupported bootstrap provenance schema")
    return result


def render_control_provenance(context: BootstrapContext, full_name: str) -> str:
    payload = {
        "schema": CONTROL_PROVENANCE_SCHEMA,
        "request_ref": context.request_ref,
        "request_url": context.request_url,
        "repository": full_name,
    }
    return (
        f"{CONTROL_START_MARKER}\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n"
        f"{CONTROL_END_MARKER}"
    )


def parse_control_provenance(body: str) -> dict[str, str]:
    """Parse new machine-readable or canonical legacy bootstrap Control provenance."""
    normalized = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    marker_count = normalized.count(CONTROL_START_MARKER) + normalized.count(CONTROL_END_MARKER)
    if marker_count:
        if (
            normalized.count(CONTROL_START_MARKER) != 1
            or normalized.count(CONTROL_END_MARKER) != 1
        ):
            raise BootstrapError("Control provenance markers must occur exactly once")
        start = normalized.index(CONTROL_START_MARKER) + len(CONTROL_START_MARKER)
        end = normalized.index(CONTROL_END_MARKER)
        if end <= start:
            raise BootstrapError("Control provenance markers are out of order")
        try:
            decoded = json.loads(normalized[start:end].strip())
        except json.JSONDecodeError as exc:
            raise BootstrapError("Control provenance is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise BootstrapError("Control provenance must be an object")
        expected_keys = {"schema", "request_ref", "request_url", "repository"}
        if set(decoded) != expected_keys:
            raise BootstrapError("Control provenance has unsupported or missing fields")
        result: dict[str, str] = {}
        for key in expected_keys:
            value = decoded.get(key)
            if not isinstance(value, str) or not value.strip():
                raise BootstrapError(f"Control provenance field {key!r} must be a non-empty string")
            result[key] = value
        if result["schema"] != CONTROL_PROVENANCE_SCHEMA:
            raise BootstrapError("unsupported Control provenance schema")
        return result

    repository_match = re.search(r"(?m)^## Repository\s*\n\s*`([^`]+)`", normalized)
    state_match = re.search(
        r"Repository was initialized through `([^`]+)` using `repository-bootstrap\.v1`",
        normalized,
    )
    explicit_state_match = re.search(
        r"Repository was initialized through `([^`]+)` using `([^`]+)`",
        normalized,
    )
    if explicit_state_match and not state_match:
        raise BootstrapError("Control uses an unsupported bootstrap schema")
    request_match = re.search(
        r"Bootstrap request:\s*(https://github\.com/[^\s]+)",
        normalized,
    )
    if not repository_match or not request_match:
        raise BootstrapError("Control has no canonical bootstrap provenance")
    request_url = request_match.group(1).rstrip(".,)")
    parsed_url = urllib.parse.urlsplit(request_url)
    path_parts = parsed_url.path.split("/")
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc.lower() != "github.com"
        or parsed_url.query
        or parsed_url.fragment
        or len(path_parts) != 5
        or path_parts[0]
        or path_parts[3] != "issues"
        or not path_parts[1]
        or not path_parts[2]
        or not path_parts[4].isdigit()
    ):
        raise BootstrapError("Control bootstrap request URL is not canonical")
    request_ref = (
        state_match.group(1)
        if state_match
        else f"{path_parts[1]}/{path_parts[2]}#{path_parts[4]}"
    )
    return {
        "schema": CONTROL_PROVENANCE_SCHEMA,
        "request_ref": request_ref,
        "request_url": request_url,
        "repository": repository_match.group(1),
    }


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
    def _main_protection_baseline() -> dict[str, Any]:
        return {
            "required_status_checks": {
                "strict": False,
                "contexts": ["verify"],
                "checks": [{"context": "verify", "app_id": 15368}],
            },
            "enforce_admins": True,
            "required_pull_request_reviews": {
                "required_approving_review_count": 0,
                "bypass_pull_request_allowances": {
                    "users": [],
                    "teams": [],
                    "apps": [],
                },
            },
            "required_conversation_resolution": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "restrictions": None,
        }

    @staticmethod
    def _protection_enabled(value: Any) -> Any:
        return value.get("enabled") if isinstance(value, dict) else value

    @classmethod
    def _main_protection_matches(cls, observed: Any) -> bool:
        if not isinstance(observed, dict):
            return False
        checks = observed.get("required_status_checks")
        if not isinstance(checks, dict) or checks.get("strict") is not False:
            return False
        contexts = checks.get("contexts")
        observed_checks = checks.get("checks")
        if contexts != ["verify"] or observed_checks != [{"context": "verify", "app_id": 15368}]:
            return False

        reviews = observed.get("required_pull_request_reviews")
        bypass = reviews.get("bypass_pull_request_allowances") if isinstance(reviews, dict) else None
        if not isinstance(reviews, dict) or reviews.get("required_approving_review_count") != 0:
            return False
        if not isinstance(bypass, dict) or any(bypass.get(key) != [] for key in ("users", "teams", "apps")):
            return False
        # The accepted payload sets restrictions=null; require an explicit
        # null readback so a pre-existing push restriction is not accepted as
        # the same bootstrap policy.
        if "restrictions" not in observed or observed["restrictions"] is not None:
            return False

        return (
            cls._protection_enabled(observed.get("enforce_admins")) is True
            and cls._protection_enabled(observed.get("required_conversation_resolution")) is True
            and cls._protection_enabled(observed.get("allow_force_pushes")) is False
            and cls._protection_enabled(observed.get("allow_deletions")) is False
        )

    def _call_main_protection(
        self,
        context: BootstrapContext,
        resources: list[str],
        operation: Any,
    ) -> Any:
        try:
            return operation()
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            needs_human = (
                type(status_code) is int
                and 400 <= status_code < 500
                and status_code not in {408, 429}
            )
            self._raise_failure(
                context,
                "MAIN_PROTECTION",
                f"{type(exc).__name__}: {exc}",
                safe_retry="after-human-decision" if needs_human else "yes",
                resources=resources,
            )

    def _ensure_verify_workflow(
        self,
        context: BootstrapContext,
        full_name: str,
        resources: list[str],
    ) -> None:
        verify_workflow_path = Path(__file__).resolve().parents[1] / "templates/bootstrap/verify.yml"
        content = self._call(
            context,
            "SEED",
            resources,
            lambda: verify_workflow_path.read_text(encoding="utf-8"),
        )
        existing = self._call(
            context,
            "SEED",
            resources,
            lambda: self.repository_api.get_file(full_name, VERIFY_WORKFLOW_PATH),
        )
        if existing is None:
            self._call(
                context,
                "SEED",
                resources,
                lambda: self.repository_api.create_file(
                    full_name,
                    VERIFY_WORKFLOW_PATH,
                    content,
                    f"chore: add bootstrap verify workflow ({context.request_ref})",
                ),
                safe_retry="after-human-decision",
            )
        elif existing.get("content") != content:
            self._raise_failure(
                context,
                "SEED",
                "existing verify workflow differs from trusted bootstrap template; never overwrite",
                safe_retry="after-human-decision",
                resources=resources,
            )
        resources.append(f"file:{VERIFY_WORKFLOW_PATH}")

    def _ensure_main_protection(
        self,
        request: BootstrapRequest,
        context: BootstrapContext,
        full_name: str,
        default_branch: str,
        resources: list[str],
    ) -> str:
        if request.main_protection is None:
            return "NOT_APPLICABLE/LEGACY_V1_REQUEST"

        observed_repo = self._call_main_protection(
            context,
            resources,
            lambda: self.repository_api.get_repository(full_name),
        )
        observed_full_name = observed_repo.get("full_name") if isinstance(observed_repo, dict) else None
        observed_visibility = observed_repo.get("visibility") if isinstance(observed_repo, dict) else None
        if (
            observed_full_name is None
            or observed_full_name.lower() != full_name.lower()
            or observed_visibility != request.repository.visibility
        ):
            self._raise_failure(
                context,
                "MAIN_PROTECTION",
                "repository identity or visibility readback does not match the Bootstrap request",
                safe_retry="after-human-decision",
                resources=resources,
            )

        if observed_visibility == "private":
            resources.append("main-protection:not-applicable:private-repository")
            return "NOT_APPLICABLE/PRIVATE_REPOSITORY"

        if observed_visibility != "public" or default_branch != "main":
            self._raise_failure(
                context,
                "MAIN_PROTECTION",
                "public main protection requires the verified default branch to be exactly main",
                safe_retry="after-human-decision",
                resources=resources,
            )

        # Install the exact status check before making it a branch-protection
        # requirement. Private Free repositories never need or receive this
        # Actions workflow.
        self._ensure_verify_workflow(context, full_name, resources)

        baseline = self._main_protection_baseline()
        protection = self._call_main_protection(
            context,
            resources,
            lambda: self.repository_api.get_branch_protection(full_name, "main"),
        )
        if protection is None:
            self._call_main_protection(
                context,
                resources,
                lambda: self.repository_api.set_branch_protection(full_name, "main", baseline),
            )
            protection = self._call_main_protection(
                context,
                resources,
                lambda: self.repository_api.get_branch_protection(full_name, "main"),
            )

        if not self._main_protection_matches(protection):
            self._raise_failure(
                context,
                "MAIN_PROTECTION",
                "main branch protection readback differs from the accepted Bootstrap baseline; existing settings were not overwritten",
                safe_retry="after-human-decision",
                resources=resources,
            )
        resources.append("main-protection:main:verified")
        return "VERIFIED/PROTECTED"

    @staticmethod
    def _find_exact_title(api: Any, full_name: str, title: str) -> list[dict[str, Any]]:
        # Control identity is safety-critical. Use the authoritative Issues listing
        # rather than the eventually-consistent Search index.
        return [
            issue
            for issue in api.list_issues(full_name, state="open")
            if issue.get("title") == title and "pull_request" not in issue
        ]

    def execute(self, request: BootstrapRequest, context: BootstrapContext) -> BootstrapResult:
        resources: list[str] = []
        if request.generated_artifact_writeback and not SHA_RE.fullmatch(context.devflow_sha):
            raise BootstrapError("generated-artifact Bootstrap requires the exact GITHUB_SHA")
        if not is_trusted_issue_author({"user": context.author}):
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
        if request.repo_native_dispatch:
            # Versioned/trusted source from devflow accepted main. No
            # repository-wide App or new Actions secret is provisioned.
            workflow_path = Path(__file__).resolve().parents[1] / "templates/bootstrap/kinotch-repo-command.yml"
            command_workflow = self._call(
                context, "SEED", resources,
                lambda: workflow_path.read_text(encoding="utf-8"),
            )
            seed_files.append((".github/workflows/kinotch-repo-command.yml", command_workflow))
        if request.generated_artifact_writeback:
            seed_files.append((
                STANDARD_ROLLOUT_CALLER_PATH,
                render_standard_rollout_caller(context.devflow_sha),
            ))
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
                    # Workflow-file creation needs an extra one-time
                    # credential permission; stop for a Human scope review,
                    # never auto-retry with a broader credential.
                    safe_retry=(
                        "after-human-decision"
                        if path in {
                            ".github/workflows/kinotch-repo-command.yml",
                            STANDARD_ROLLOUT_CALLER_PATH,
                        }
                        else "yes"
                    ),
                )
            elif path == ".github/workflows/kinotch-repo-command.yml" and existing.get("content") != content:
                existing_content = existing.get("content")
                legacy_receiver = (
                    not request.standard_features_declared
                    and isinstance(existing_content, str)
                    and hashlib.sha256(existing_content.encode("utf-8")).hexdigest()
                    == LEGACY_REPO_NATIVE_DISPATCH_SHA256
                )
                if not legacy_receiver:
                    self._raise_failure(
                        context, "SEED",
                        "existing native-dispatch workflow differs from trusted template; never overwrite",
                        safe_retry="after-human-decision", resources=resources,
                    )
            elif path == STANDARD_ROLLOUT_CALLER_PATH and existing.get("content") != content:
                if not is_standard_rollout_caller(existing.get("content")):
                    self._raise_failure(
                        context, "SEED",
                        "existing generated-artifact caller differs from trusted read-only template; never overwrite",
                        safe_retry="after-human-decision", resources=resources,
                    )
            resources.append(f"file:{path}")

        if request.standard_features_declared:
            manifest = json.dumps(
                standard_feature_manifest(request),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
            existing = self._call(
                context,
                "SEED",
                resources,
                lambda: self.repository_api.get_file(full_name, STANDARD_FEATURE_MANIFEST_PATH),
            )
            if existing is None:
                self._call(
                    context,
                    "SEED",
                    resources,
                    lambda: self.repository_api.create_file(
                        full_name,
                        STANDARD_FEATURE_MANIFEST_PATH,
                        manifest,
                        f"chore: record standard repository features ({context.request_ref})",
                    ),
                )
            elif existing.get("content") != manifest:
                self._raise_failure(
                    context,
                    "SEED",
                    "existing standard-feature manifest differs from trusted Bootstrap request; never overwrite",
                    safe_retry="after-human-decision",
                    resources=resources,
                )
            resources.append(f"file:{STANDARD_FEATURE_MANIFEST_PATH}")

        audit_ref = self._call(
            context,
            "SEED",
            resources,
            lambda: self.repository_api.get_default_branch_name(full_name),
        )
        main_protection_status = self._ensure_main_protection(
            request,
            context,
            full_name,
            audit_ref,
            resources,
        )
        # Protection setup can seed the required verify workflow on a new
        # Public repository. Capture the accepted head only after every
        # bootstrap-owned file write is complete.
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
                if request.standard_features_declared:
                    entry_points.append(f"- `{STANDARD_FEATURE_MANIFEST_PATH}`")
                entry_points.extend(issue_refs)
                control_body = (
                    f"## Repository\n\n`{full_name}`\n\n"
                    f"## Work Status\n\n`{request.work_status}`\n\n"
                    "## Type\n\n`FEATURE`\n\n"
                    f"## Repository State\n\n`{request.repository_state}`\n\n"
                    f"## Priority\n\n`{request.priority}`\n\n"
                    f"## Risk\n\n`{request.risk}`\n\n"
                    f"## Audit SHA\n\n`{head_sha}`\n\n"
                    f"## Audit Ref\n\n`{audit_ref}`\n\n"
                    f"## Active Work\n\n{active_work}\n\n"
                    f"## Next Action\n\n`{request.next_action}`\n\n"
                    "## Canonical Entry Points\n\n"
                    + "\n".join(entry_points)
                    + "\n\n## Control Notes\n\n"
                    f"Repository was initialized through `{context.request_ref}` using `{SCHEMA_VERSION}`. "
                    f"Accepted initial head is `{head_sha}`. No implementation beyond the requested bootstrap seed is implied by this Control.\n\n"
                    f"{render_control_provenance(context, full_name)}\n\n"
                    f"Cross-repository routing summary only. Bootstrap request: {context.request_url}. "
                    f"Repository kind recorded by the request: `{request.kind}`. Detailed technical truth belongs in `{full_name}`. "
                    "M3 P0/P1 dual-read: retain Active Work and Next Action as manual fallback for local-work and Human/policy/cross-repository decisions; owning repository Issues/PRs remain canonical. "
                    "Machine-derived TASK records are centrally projected, not a second task ledger or execution authority. Do not manually edit machine-owned projection markers. "
                    "Missing, stale, untrusted, incomplete or truncated machine source is unknown, not an empty task queue. "
                    "M3.1/M3.3 manual-authority retirement requires separate per-repository/per-consumer admission."
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
            f"Main-Protection: {main_protection_status}",
            *(f"Initial-Issue: {url}" for url in issue_urls),
        ]
        if request.generated_artifact_writeback:
            done_lines.append(
                "Generated-Artifact-Writeback: NOT_APPLICABLE/NO_GENERATED_OUTPUT"
            )
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
            if allow_404 and code == 404:
                exc.close()
                return None
            try:
                # HTTPError is a readable response. Bound the read and never
                # expose arbitrary response text or headers in exceptions.
                error_body = exc.read(MAX_ERROR_BODY_BYTES)
            except (OSError, ValueError):
                error_body = b""
            finally:
                exc.close()
            diagnostic = summarize_github_http_error(code, exc.headers, error_body)
            # Do not chain the raw HTTPError: it may retain the request/headers.
            raise GitHubApiError(
                f"{method} {path} failed with HTTP {code} ({diagnostic})",
                status_code=code,
            ) from None
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

    def get_issue(self, full_name: str, issue_number: int) -> dict[str, Any]:
        if type(issue_number) is not int or issue_number <= 0:
            raise BootstrapError("Issue number must be a positive integer")
        result = self._request(
            "GET",
            f"/repos/{self._repo_path(full_name)}/issues/{issue_number}",
        )
        if not isinstance(result, dict) or "pull_request" in result:
            raise GitHubApiError("get Issue returned a malformed or non-Issue response")
        return result

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
        principal_id = identity.get("id") if isinstance(identity, dict) else None
        if principal_id != 79015263:
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

    def get_default_branch_name(self, full_name: str) -> str:
        repo = self.get_repository(full_name)
        if not isinstance(repo, dict):
            raise GitHubApiError(f"repository {full_name} disappeared during bootstrap")
        branch = repo.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise GitHubApiError(f"repository {full_name} has no default branch after seed")
        return branch

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

    def get_branch_protection(self, full_name: str, branch: str) -> dict[str, Any] | None:
        if not isinstance(branch, str) or not branch:
            raise BootstrapError("branch name must be a non-empty string")
        encoded_branch = urllib.parse.quote(branch, safe="")
        result = self._request(
            "GET",
            f"/repos/{self._repo_path(full_name)}/branches/{encoded_branch}/protection",
            allow_404=True,
        )
        if result is not None and not isinstance(result, dict):
            raise GitHubApiError("branch protection response is malformed")
        return result

    def set_branch_protection(
        self,
        full_name: str,
        branch: str,
        protection: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(branch, str) or not branch:
            raise BootstrapError("branch name must be a non-empty string")
        if not isinstance(protection, Mapping):
            raise BootstrapError("branch protection must be an object")
        encoded_branch = urllib.parse.quote(branch, safe="")
        result = self._request(
            "PUT",
            f"/repos/{self._repo_path(full_name)}/branches/{encoded_branch}/protection",
            protection,
        )
        if not isinstance(result, dict):
            raise GitHubApiError("set branch protection returned a malformed response")
        return result

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
