from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

try:
    from tools import devflow_mcp_core, workflow_contract
    from tools.maintenance_catalog import (
        MaintenanceCatalogError,
        canonical_catalog_digest,
        parse_common_baseline_text,
        parse_repository_catalog_text,
        resolve_catalog,
    )
    from tools.maintenance_ledger import (
        MaintenanceLedgerError,
        RunRecord,
        next_generation,
        parse_run_comment,
    )
    from tools.maintenance_selector import (
        RunEvidence,
        SelectionContext,
        canonical_fingerprint,
        select_maintenance,
    )
except ImportError:  # direct module execution
    import devflow_mcp_core
    import workflow_contract
    from maintenance_catalog import (
        MaintenanceCatalogError,
        canonical_catalog_digest,
        parse_common_baseline_text,
        parse_repository_catalog_text,
        resolve_catalog,
    )
    from maintenance_ledger import (
        MaintenanceLedgerError,
        RunRecord,
        next_generation,
        parse_run_comment,
    )
    from maintenance_selector import (
        RunEvidence,
        SelectionContext,
        canonical_fingerprint,
        select_maintenance,
    )

WORKFLOW_CONTRACT = workflow_contract.WORKFLOW_CONTRACT


API_BASE = "https://api.github.com"
DEVFLOW_REPOSITORY = "kinoko34077/devflow"
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
CANDIDATE_BEGIN = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->"
CANDIDATE_END = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->"
_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:(?P<owner>[A-Za-z0-9_.-]+)/)?"
    r"(?P<repo>[A-Za-z0-9_.-]+)#(?P<number>[1-9][0-9]*)"
)


class GitHubReadError(RuntimeError):
    """Read-only GitHub transport failure with credential-safe messages."""


def _redact(text: str, token: str) -> str:
    return text.replace(token, "[REDACTED]") if token else text


def _next_link(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.split(","):
        fields = [field.strip() for field in part.split(";")]
        if not fields or len(fields) < 2:
            continue
        target = fields[0]
        relations = fields[1:]
        if (
            any(rel == 'rel="next"' for rel in relations)
            and target.startswith("<")
            and target.endswith(">")
        ):
            return target[1:-1]
    return None


class GitHubReadTransport:
    """Minimal GET-only GitHub REST transport for maintenance observation."""

    def __init__(
        self,
        token: str,
        api_base: str = API_BASE,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout: float = 30.0,
    ) -> None:
        if not isinstance(token, str):
            raise TypeError("token must be a string")
        self._token = token
        self.api_base = api_base.rstrip("/")
        self._opener = opener
        self._timeout = timeout

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("https://"):
            return path_or_url
        if not path_or_url.startswith("/"):
            path_or_url = "/" + path_or_url
        return self.api_base + path_or_url

    def _request(
        self,
        path_or_url: str,
        *,
        allow_404: bool = False,
    ) -> tuple[Any, Any]:
        request = urllib.request.Request(
            self._url(path_or_url),
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "kinotch-devflow-maintenance-audit",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read()
                try:
                    payload = json.loads(raw.decode("utf-8")) if raw else None
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise GitHubReadError("GitHub read returned invalid JSON") from exc
                return payload, response.headers
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None, {}
            raise GitHubReadError(
                f"GitHub read failed with HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            reason = _redact(str(exc.reason), self._token)
            raise GitHubReadError(f"GitHub read failed: {reason}") from None
        except GitHubReadError:
            raise
        except Exception as exc:
            detail = _redact(str(exc), self._token)
            raise GitHubReadError(
                f"GitHub read failed: {type(exc).__name__}: {detail}"
            ) from None

    def get_json(self, path_or_url: str) -> Any:
        payload, _headers = self._request(path_or_url)
        return payload

    def get_paginated(self, path_or_url: str) -> list[Any]:
        items: list[Any] = []
        next_url: str | None = path_or_url
        seen: set[str] = set()
        while next_url is not None:
            absolute = self._url(next_url)
            if absolute in seen:
                raise GitHubReadError("GitHub pagination loop detected")
            seen.add(absolute)
            payload, headers = self._request(next_url)
            if not isinstance(payload, list):
                raise GitHubReadError(
                    "GitHub paginated read did not return an array"
                )
            items.extend(payload)
            next_url = _next_link(
                headers.get("Link") if hasattr(headers, "get") else None
            )
        return items

    def get_paginated_key(
        self,
        path_or_url: str,
        key: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = path_or_url
        seen: set[str] = set()
        while next_url is not None:
            absolute = self._url(next_url)
            if absolute in seen:
                raise GitHubReadError(
                    "GitHub pagination loop detected"
                )
            seen.add(absolute)
            payload, headers = self._request(next_url)
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get(key), list)
            ):
                raise GitHubReadError(
                    f"GitHub paginated read missing array: {key}"
                )
            items.extend(
                dict(item)
                for item in payload[key]
                if isinstance(item, dict)
            )
            next_url = _next_link(
                headers.get("Link")
                if hasattr(headers, "get")
                else None
            )
        return items

    def get_repository(self, repository: str) -> dict[str, Any]:
        value = self.get_json(f"/repos/{repository}")
        if not isinstance(value, dict):
            raise GitHubReadError("repository read did not return an object")
        return value

    def get_issue(self, repository: str, number: int) -> dict[str, Any]:
        value = self.get_json(f"/repos/{repository}/issues/{number}")
        if not isinstance(value, dict):
            raise GitHubReadError("Issue read did not return an object")
        _validate_issue_identity(value, repository, number)
        return value

    def list_issues(
        self,
        repository: str,
        state: str = "open",
    ) -> list[dict[str, Any]]:
        encoded_state = urllib.parse.quote(state, safe="")
        return [
            dict(item)
            for item in self.get_paginated(
                f"/repos/{repository}/issues?state={encoded_state}&per_page=100"
            )
            if isinstance(item, dict)
        ]

    def list_issue_comments(
        self,
        repository: str,
        issue_number: int,
    ) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self.get_paginated(
                f"/repos/{repository}/issues/{issue_number}/comments?per_page=100"
            )
            if isinstance(item, dict)
        ]

    def get_file(
        self,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, Any] | None:
        encoded_path = urllib.parse.quote(path, safe="/")
        suffix = (
            "?ref=" + urllib.parse.quote(ref, safe="")
            if ref is not None
            else ""
        )
        value, _headers = self._request(
            f"/repos/{repository}/contents/{encoded_path}{suffix}",
            allow_404=True,
        )
        if value is None:
            return None
        if not isinstance(value, dict) or value.get("type") not in (None, "file"):
            raise GitHubReadError("repository contents read did not return a file")
        encoded = value.get("content")
        if not isinstance(encoded, str):
            raise GitHubReadError("repository file content is unavailable")
        try:
            content = base64.b64decode(
                encoded.encode("ascii"),
                validate=False,
            ).decode("utf-8")
        except (UnicodeError, ValueError) as exc:
            raise GitHubReadError(
                "repository file content is not UTF-8 text"
            ) from exc
        return {
            "content": content,
            "sha": value.get("sha"),
        }

    def get_repository_file(
        self,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, Any] | None:
        return self.get_file(repository, path, ref=ref)

    def get_pull(self, repository: str, number: int) -> dict[str, Any]:
        value = self.get_json(f"/repos/{repository}/pulls/{number}")
        if not isinstance(value, dict):
            raise GitHubReadError("PR read did not return an object")
        return value

    def get_check_runs(
        self,
        repository: str,
        head_sha: str,
    ) -> list[dict[str, Any]]:
        return self.get_paginated_key(
            (
                f"/repos/{repository}/commits/{head_sha}/"
                "check-runs?per_page=100"
            ),
            "check_runs",
        )

    def get_reviews(
        self,
        repository: str,
        number: int,
    ) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self.get_paginated(
                f"/repos/{repository}/pulls/{number}/reviews?per_page=100"
            )
            if isinstance(item, dict)
        ]

    def get_default_branch(self, repository: str) -> dict[str, Any]:
        repo = self.get_repository(repository)
        branch = repo.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise GitHubReadError("repository default branch is unavailable")
        value = self.get_json(
            f"/repos/{repository}/branches/"
            f"{urllib.parse.quote(branch, safe='')}"
        )
        if not isinstance(value, dict):
            raise GitHubReadError(
                "default-branch read did not return an object"
            )
        return value

    def get_pull_evidence(
        self,
        repository: str,
        number: int,
    ) -> dict[str, Any]:
        pull = self.get_pull(repository, number)
        head = pull.get("head")
        head_sha = head.get("sha") if isinstance(head, dict) else None
        if not isinstance(head_sha, str) or len(head_sha) != 40:
            raise GitHubReadError("PR head SHA is unavailable")
        reviews = self.get_reviews(repository, number)
        current_reviews = [
            review
            for review in reviews
            if review.get("commit_id") == head_sha
        ]
        stale_reviews = [
            review
            for review in reviews
            if review.get("commit_id") != head_sha
        ]
        return {
            "pull": pull,
            "head_sha": head_sha,
            "check_runs": self.get_check_runs(
                repository,
                head_sha,
            ),
            "reviews": current_reviews,
            "stale_reviews": stale_reviews,
        }


def _issue_revision(issue: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "number": issue.get("number"),
            "state": issue.get("state"),
            "updated_at": issue.get("updated_at"),
            "body": issue.get("body") or "",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha1(material).hexdigest()


def _sections(body: str) -> dict[str, str]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    normalized = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip()
            result.setdefault(current, [])
        elif current is not None:
            result[current].append(line)
    return {
        key: "\n".join(lines).strip()
        for key, lines in result.items()
    }


def _scalar_section(
    sections: dict[str, str],
    name: str,
) -> str | None:
    value = sections.get(name)
    if value is None:
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    text = lines[0]
    if len(text) >= 2 and text[0] == text[-1] == "`":
        text = text[1:-1].strip()
    return text or None


def _normalize_ref(match: re.Match[str]) -> str:
    owner = match.group("owner") or "kinoko34077"
    return f"{owner}/{match.group('repo')}#{match.group('number')}"


def _refs(text: str) -> list[str]:
    return sorted(
        {
            _normalize_ref(match)
            for match in _REF_RE.finditer(text or "")
        }
    )


def _split_ref(value: str) -> tuple[str, int]:
    match = re.fullmatch(
        r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)",
        value,
    )
    if not match:
        raise GitHubReadError("Issue reference is malformed")
    return match.group(1), int(match.group(2))


def _candidate_tasks(
    body: str,
    repository: str | None = None,
    control_ref: str | None = None,
) -> list[str]:
    begin_count = body.count(CANDIDATE_BEGIN)
    end_count = body.count(CANDIDATE_END)
    if begin_count == 0 and end_count == 0:
        return []
    if begin_count != 1 or end_count != 1:
        raise GitHubReadError(
            "candidate projection markers are missing or duplicated"
        )
    start = body.index(CANDIDATE_BEGIN) + len(CANDIDATE_BEGIN)
    end = body.index(CANDIDATE_END)
    if end <= start:
        raise GitHubReadError("candidate projection markers are out of order")
    payload = body[start:end].strip()
    if payload.startswith("```json"):
        payload = payload[len("```json"):].lstrip("\r\n")
        if not payload.endswith("```"):
            raise GitHubReadError(
                "candidate projection JSON fence is not closed"
            )
        payload = payload[:-3].rstrip()
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GitHubReadError(
            "candidate projection contains invalid JSON"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("candidates"), list)
    ):
        raise GitHubReadError("candidate projection schema is invalid")
    if repository is not None and value.get("repository") != repository:
        raise GitHubReadError(
            "candidate projection repository identity mismatch"
        )
    if control_ref is not None and value.get("source_ref") != control_ref:
        raise GitHubReadError(
            "candidate projection source identity mismatch"
        )

    tasks: list[str] = []
    for item in value["candidates"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("task"), str)
            or not item["task"]
        ):
            raise GitHubReadError(
                "candidate projection contains malformed task entry"
            )
        tasks.append(item["task"])
    if len(set(tasks)) != len(tasks):
        raise GitHubReadError(
            "candidate projection contains duplicate task refs"
        )
    return sorted(tasks)


def _explicit_no_active_work(control_body: str) -> bool:
    sections = _sections(control_body)
    active_text = (
        sections.get("Active Work")
        or sections.get("Active Work / current routing")
        or ""
    )
    first = next(
        (
            line.strip()
            for line in active_text.splitlines()
            if line.strip()
        ),
        "",
    )
    return re.match(
        r"^(?:None(?:\.|\s|$)|No\s+active(?:\s|$))",
        first,
        re.IGNORECASE,
    ) is not None


def _active_owner_ref(
    control_body: str,
    repository: str,
    control_ref: str | None = None,
) -> tuple[str | None, bool]:
    candidates = [
        ref
        for ref in _candidate_tasks(
            control_body,
            repository,
            control_ref,
        )
        if ref.rsplit("#", 1)[0] == repository
    ]
    if len(candidates) == 1:
        return candidates[0], True
    sections = _sections(control_body)
    active_text = (
        sections.get("Active Work")
        or sections.get("Active Work / current routing")
        or ""
    )
    if _explicit_no_active_work(control_body):
        return None, False
    refs = [
        ref
        for ref in _refs(active_text)
        if ref.rsplit("#", 1)[0] == repository
    ]
    if len(refs) == 1:
        return refs[0], refs[0] in candidates
    return None, False



def _expected_issue_url(repository: str, number: int) -> str:
    return f"https://github.com/{repository}/issues/{number}"


def _validate_issue_identity(
    issue: dict[str, Any],
    repository: str,
    number: int,
    *,
    expected_title: str | None = None,
    require_open: bool = False,
) -> None:
    if issue.get("number") != number:
        raise GitHubReadError("Issue number identity mismatch")
    if "pull_request" in issue:
        raise GitHubReadError("PR object cannot satisfy Issue authority")
    if issue.get("html_url") != _expected_issue_url(repository, number):
        raise GitHubReadError("Issue URL identity mismatch")
    repository_url = issue.get("repository_url")
    if repository_url is not None and repository_url != (
        f"https://api.github.com/repos/{repository}"
    ):
        raise GitHubReadError("Issue repository identity mismatch")
    state = str(issue.get("state") or "").lower()
    if state not in {"open", "closed"}:
        raise GitHubReadError("Issue state is unavailable")
    if require_open and state != "open":
        raise GitHubReadError("canonical Control Issue is not open")
    if expected_title is not None and issue.get("title") != expected_title:
        raise GitHubReadError("canonical Control title mismatch")


def _control_is_trusted(
    transport: Any,
    control: dict[str, Any],
    repository: str,
) -> bool:
    association = str(control.get("author_association") or "").upper()
    if association in TRUSTED_ASSOCIATIONS:
        return True
    try:
        return devflow_mcp_core.DevflowService(
            transport
        ).is_repository_control_trusted(
            control,
            repository,
        )
    except (
        devflow_mcp_core.DevflowMCPError,
        GitHubReadError,
    ):
        return False


def _unavailable(
    repository: str,
    observed_at: str,
    control_ref: str,
    detail: str,
) -> dict[str, object]:
    return {
        "repository": repository,
        "observed_at": observed_at,
        "control_ref": control_ref,
        "source_status": "UNAVAILABLE",
        "source_error": detail,
        "evidence_refs": [control_ref],
    }


def collect_repository(
    transport: Any,
    repository: str,
    control_ref: str,
    observed_at: str,
) -> dict[str, object]:
    try:
        control_repo, control_number = _split_ref(control_ref)
        control = transport.get_json(
            f"/repos/{control_repo}/issues/{control_number}"
        )
        if not isinstance(control, dict):
            raise GitHubReadError(
                "Control read did not return an object"
            )
        _validate_issue_identity(
            control,
            control_repo,
            control_number,
            expected_title=f"[REPO] {repository.rsplit('/', 1)[-1]}",
            require_open=True,
        )
    except (GitHubReadError, ValueError) as exc:
        return _unavailable(
            repository,
            observed_at,
            control_ref,
            str(exc),
        )

    body = str(control.get("body") or "")
    sections = _sections(body)
    try:
        WORKFLOW_CONTRACT.validate_repository_control_sections(sections)
    except workflow_contract.WorkflowContractError as exc:
        return _unavailable(
            repository,
            observed_at,
            control_ref,
            str(exc),
        )
    managed = _scalar_section(sections, "Repository")
    trusted = _control_is_trusted(
        transport,
        control,
        repository,
    )
    next_action = sections.get("Next Action", "")
    control_human_gate = (
        "[USER_DECISION]" in next_action
        or "[HUMAN_GATE]" in next_action
    )
    try:
        owner_ref, candidate_present = _active_owner_ref(
            body,
            repository,
            control_ref,
        )
    except GitHubReadError as exc:
        return _unavailable(
            repository,
            observed_at,
            control_ref,
            str(exc),
        )
    explicit_idle = (
        owner_ref is None
        and not candidate_present
        and _explicit_no_active_work(body)
    )
    source_status = "OK"
    if (
        managed != repository
        or not trusted
        or (owner_ref is None and not explicit_idle)
    ):
        source_status = "AMBIGUOUS"

    if owner_ref is None:
        control_revision = _issue_revision(control)
        return {
            "repository": repository,
            "observed_at": observed_at,
            "control_count": 1,
            "control": {
                "ref": control_ref,
                "repository": repository,
                "trusted": trusted,
                "revision": control_revision,
                "active_owner_ref": None,
                "candidate_present": candidate_present,
            },
            "owner": {
                "ref": None,
                "repository": repository,
                "revision": control_revision,
                "state": "NONE" if explicit_idle else "UNKNOWN",
                "runnable": False,
                "terminal": False,
            },
            "source_status": source_status,
            "producer_active": False,
            "reviewer_gate": False,
            "human_gate": control_human_gate,
            "external_wait": False,
            "semantic_projection_suspected": False,
            "search_state": None,
            "evidence_refs": [control_ref],
        }

    owner_repo, owner_number = _split_ref(owner_ref)
    try:
        owner = transport.get_json(
            f"/repos/{owner_repo}/issues/{owner_number}"
        )
        if not isinstance(owner, dict):
            raise GitHubReadError(
                "owner read did not return an object"
            )
        _validate_issue_identity(
            owner,
            owner_repo,
            owner_number,
        )
    except GitHubReadError:
        owner = {
            "number": owner_number,
            "state": "unknown",
            "updated_at": None,
            "body": "",
        }
        source_status = "UNAVAILABLE"

    owner_association = str(
        owner.get("author_association") or ""
    ).upper()
    if owner_association not in TRUSTED_ASSOCIATIONS:
        source_status = "UNAVAILABLE"

    owner_sections = _sections(str(owner.get("body") or ""))
    work_status = (
        _scalar_section(owner_sections, "Work Status") or ""
    ).upper()
    state = str(owner.get("state") or "UNKNOWN").upper()
    terminal = state == "CLOSED" or work_status == "DONE"
    runnable = work_status in {
        "READY_FOR_IMPLEMENTATION",
        "AWAITING_REVIEW",
        "WORK_ORDER_READY",
    }
    producer_active = work_status == "IMPLEMENTING"
    reviewer_gate = work_status == "AWAITING_REVIEW"

    return {
        "repository": repository,
        "observed_at": observed_at,
        "control_count": 1,
        "control": {
            "ref": control_ref,
            "repository": repository,
            "trusted": trusted,
            "revision": _issue_revision(control),
            "active_owner_ref": owner_ref,
            "candidate_present": candidate_present,
        },
        "owner": {
            "ref": owner_ref,
            "repository": repository,
            "revision": _issue_revision(owner),
            "state": state,
            "runnable": runnable,
            "terminal": terminal,
        },
        "source_status": source_status,
        "producer_active": producer_active,
        "reviewer_gate": reviewer_gate,
        "human_gate": control_human_gate,
        "external_wait": False,
        "semantic_projection_suspected": False,
        "search_state": None,
        "evidence_refs": [control_ref, owner_ref],
    }


def collect_portfolio(
    transport: Any,
    controls: list[dict[str, object]],
    observed_at: str,
) -> list[dict[str, object]]:
    grouped: dict[str, list[str]] = {}
    for item in controls:
        repository = item.get("repository")
        control_ref = item.get("control_ref") or item.get("ref")
        if isinstance(repository, str) and isinstance(control_ref, str):
            grouped.setdefault(repository, []).append(control_ref)

    observations: list[dict[str, object]] = []
    for repository in sorted(grouped):
        refs = sorted(set(grouped[repository]))
        if len(refs) != 1:
            observations.append(
                _unavailable(
                    repository,
                    observed_at,
                    refs[0] if refs else "UNKNOWN",
                    "duplicate or missing Repository Control",
                )
            )
            continue
        observations.append(
            collect_repository(
                transport,
                repository,
                refs[0],
                observed_at,
            )
        )
    return observations


def discover_controls(
    transport: GitHubReadTransport,
) -> list[dict[str, object]]:
    issues = transport.get_paginated(
        f"/repos/{DEVFLOW_REPOSITORY}/issues?state=open&per_page=100"
    )
    found: list[dict[str, object]] = []
    for item in issues:
        if not isinstance(item, dict) or "pull_request" in item:
            continue
        title = str(item.get("title") or "")
        if not title.startswith("[REPO] "):
            continue
        number = item.get("number")
        if not isinstance(number, int):
            continue
        exact = transport.get_issue(DEVFLOW_REPOSITORY, number)
        sections = _sections(str(exact.get("body") or ""))
        repository = _scalar_section(sections, "Repository")
        if repository:
            found.append(
                {
                    "repository": repository,
                    "control_ref": (
                        f"{DEVFLOW_REPOSITORY}#{number}"
                    ),
                }
            )
    return sorted(
        found,
        key=lambda item: (
            str(item["repository"]),
            str(item["control_ref"]),
        ),
    )


MAINTENANCE_BASELINE_PATH = "docs/spec/maintenance/common-baseline.v1.yaml"
MAINTENANCE_CATALOG_PATH = ".devflow/maintenance.yaml"
MAINTENANCE_LEDGER_TITLE = "[MAINTENANCE] Audit Ledger"
MAINTENANCE_SELECTION_SCHEMA = "maintenance-selection.v1"


def _default_head(transport: Any, repository: str) -> str:
    branch = transport.get_default_branch(repository)
    commit = branch.get("commit") if isinstance(branch, dict) else None
    head = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(head, str) or len(head) != 40:
        raise GitHubReadError("default-branch head SHA is unavailable")
    return head


def _catalog_bundle(
    transport: Any,
    repository: str,
) -> tuple[object, object, tuple[object, ...], str, str, dict[str, Any], dict[str, Any]]:
    target_head = _default_head(transport, repository)
    baseline_head = _default_head(transport, DEVFLOW_REPOSITORY)

    baseline_file = transport.get_repository_file(
        DEVFLOW_REPOSITORY,
        MAINTENANCE_BASELINE_PATH,
        ref=baseline_head,
    )
    if not isinstance(baseline_file, dict):
        raise GitHubReadError("maintenance common baseline is unavailable")

    catalog_file = transport.get_repository_file(
        repository,
        MAINTENANCE_CATALOG_PATH,
        ref=target_head,
    )
    if catalog_file is None:
        raise FileNotFoundError(MAINTENANCE_CATALOG_PATH)
    if not isinstance(catalog_file, dict):
        raise GitHubReadError("maintenance catalog read is malformed")

    baseline_text = baseline_file.get("content")
    catalog_text = catalog_file.get("content")
    if not isinstance(baseline_text, str) or not isinstance(catalog_text, str):
        raise GitHubReadError("maintenance catalog content is unavailable")

    baseline = parse_common_baseline_text(baseline_text)
    catalog = parse_repository_catalog_text(catalog_text, baseline)
    if catalog.repository != repository:
        raise MaintenanceCatalogError(
            "maintenance catalog repository identity mismatch"
        )
    slots = resolve_catalog(baseline, catalog)
    digest = canonical_catalog_digest(baseline, catalog)
    return (
        baseline,
        catalog,
        slots,
        digest,
        target_head,
        dict(baseline_file),
        dict(catalog_file),
    )


def collect_maintenance_catalog(
    transport: Any,
    repository: str,
    control_ref: str,
) -> dict[str, object]:
    try:
        baseline, catalog, slots, digest, head, baseline_file, catalog_file = _catalog_bundle(
            transport,
            repository,
        )
    except FileNotFoundError:
        return {
            "schema_version": MAINTENANCE_SELECTION_SCHEMA,
            "repository": repository,
            "control_ref": control_ref,
            "status": "NO_CATALOG",
            "reason_code": "CATALOG_NOT_FOUND",
        }
    except (MaintenanceCatalogError, GitHubReadError, ValueError) as exc:
        return {
            "schema_version": MAINTENANCE_SELECTION_SCHEMA,
            "repository": repository,
            "control_ref": control_ref,
            "status": "NEEDS_EVIDENCE",
            "reason_code": "CATALOG_INVALID",
            "detail": str(exc),
        }

    return {
        "schema_version": MAINTENANCE_SELECTION_SCHEMA,
        "repository": repository,
        "control_ref": control_ref,
        "status": "OK",
        "reason_code": "CATALOG_READY",
        "code_sha": head,
        "catalog_digest": digest,
        "rollout": catalog.rollout,
        "risk_profile": catalog.risk_profile,
        "slot_count": len(slots),
        "baseline_file_sha": baseline_file.get("sha"),
        "catalog_file_sha": catalog_file.get("sha"),
        "evidence_refs": [
            f"{DEVFLOW_REPOSITORY}:{MAINTENANCE_BASELINE_PATH}@{baseline_file.get('sha')}",
            f"{repository}:{MAINTENANCE_CATALOG_PATH}@{catalog_file.get('sha')}",
            control_ref,
        ],
    }


def _trusted_issue(issue: Mapping[str, object]) -> bool:
    return str(issue.get("author_association") or "").upper() in TRUSTED_ASSOCIATIONS


def find_maintenance_ledger(
    transport: Any,
    repository: str,
) -> tuple[dict[str, Any] | None, str | None]:
    matches = [
        dict(item)
        for item in transport.list_issues(repository, state="open")
        if isinstance(item, dict)
        and "pull_request" not in item
        and item.get("title") == MAINTENANCE_LEDGER_TITLE
        and _trusted_issue(item)
    ]
    if not matches:
        return None, "LEDGER_NOT_FOUND"
    if len(matches) != 1:
        return None, "LEDGER_DUPLICATE"
    issue = matches[0]
    number = issue.get("number")
    if not isinstance(number, int):
        return None, "LEDGER_INVALID"
    return issue, None


def collect_maintenance_history(
    transport: Any,
    repository: str,
    ledger_issue: int,
) -> tuple[RunRecord, ...]:
    records: list[RunRecord] = []
    for comment in transport.list_issue_comments(repository, ledger_issue):
        if not isinstance(comment, dict):
            continue
        body = comment.get("body")
        if not isinstance(body, str):
            continue
        if str(comment.get("author_association") or "").upper() not in TRUSTED_ASSOCIATIONS:
            continue
        try:
            record = parse_run_comment(body)
        except MaintenanceLedgerError as exc:
            raise GitHubReadError(
                f"trusted maintenance Ledger comment is malformed: {exc}"
            ) from exc
        if record is None:
            continue
        if record.repository != repository:
            raise GitHubReadError(
                "maintenance Ledger run repository identity mismatch"
            )
        records.append(record)
    records.sort(key=lambda item: (item.completed_at, item.run_id))
    return tuple(records)


def build_maintenance_fingerprint(
    code_sha: str,
    catalog_digest: str,
    external_state: Mapping[str, object] | None = None,
) -> str:
    return canonical_fingerprint(
        {
            "code_sha": code_sha,
            "catalog_digest": catalog_digest,
            "external_state": dict(external_state or {}),
        }
    )


def _parse_observed_at(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise GitHubReadError("maintenance observed_at must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise GitHubReadError(
            "maintenance observed_at must be RFC3339 UTC"
        ) from exc


def collect_maintenance_selection(
    transport: Any,
    repository: str,
    control_ref: str,
    observed_at: str,
    *,
    external_state: Mapping[str, object] | None = None,
    previous_repository: str | None = None,
) -> dict[str, object]:
    public = collect_maintenance_catalog(
        transport,
        repository,
        control_ref,
    )
    if public.get("status") != "OK":
        return public

    try:
        baseline, catalog, slots, digest, head, _baseline_file, _catalog_file = _catalog_bundle(
            transport,
            repository,
        )
    except (MaintenanceCatalogError, GitHubReadError, FileNotFoundError, ValueError) as exc:
        return {
            "schema_version": MAINTENANCE_SELECTION_SCHEMA,
            "repository": repository,
            "control_ref": control_ref,
            "status": "NEEDS_EVIDENCE",
            "reason_code": "CATALOG_DRIFT",
            "detail": str(exc),
        }

    ledger, ledger_error = find_maintenance_ledger(
        transport,
        repository,
    )
    if ledger_error is not None:
        return {
            "schema_version": MAINTENANCE_SELECTION_SCHEMA,
            "repository": repository,
            "control_ref": control_ref,
            "status": "NEEDS_EVIDENCE",
            "reason_code": ledger_error,
        }
    assert ledger is not None
    number = ledger["number"]
    try:
        history = collect_maintenance_history(
            transport,
            repository,
            number,
        )
    except GitHubReadError as exc:
        return {
            "schema_version": MAINTENANCE_SELECTION_SCHEMA,
            "repository": repository,
            "control_ref": control_ref,
            "status": "NEEDS_EVIDENCE",
            "reason_code": "LEDGER_INVALID",
            "detail": str(exc),
        }

    if catalog.rollout == "DISABLED":
        return {
            "schema_version": MAINTENANCE_SELECTION_SCHEMA,
            "repository": repository,
            "control_ref": control_ref,
            "ledger_ref": f"{repository}#{number}",
            "status": "NO_ELIGIBLE_WORK",
            "reason_code": "MAINTENANCE_DISABLED",
        }

    current_fingerprint = build_maintenance_fingerprint(
        head,
        digest,
        external_state,
    )
    current_fingerprints = {
        f"{slot.repository}::{slot.slot_id}": current_fingerprint
        for slot in slots
    }
    slot_by_id = {slot.slot_id: slot for slot in slots}
    selector_history: list[RunEvidence] = []
    for record in history:
        slot = slot_by_id.get(record.slot_id)
        if slot is None:
            continue
        selector_history.append(
            RunEvidence(
                repository=record.repository,
                slot_id=record.slot_id,
                lens=record.lens,
                coverage_key=slot.coverage_key,
                scope_kind=slot.scope.kind,
                scope_selector=slot.scope.selector,
                depth=record.depth,
                fingerprint=record.fingerprint,
                completed_at=_parse_observed_at(record.completed_at),
                evidence_complete=record.result not in {"BLOCKED", "NEEDS_REAUDIT"},
            )
        )

    context = SelectionContext(
        observed_at=_parse_observed_at(observed_at),
        target_repository=repository,
        previous_repository=previous_repository,
        eligible_repositories=frozenset({repository}),
        current_fingerprints=current_fingerprints,
        relevant_changes=frozenset(),
        security_events=frozenset(),
        finding_reaudits=frozenset(),
        external_stale=frozenset(),
        incomplete_evidence=frozenset(
            f"{item.repository}::{item.slot_id}"
            for item in selector_history
            if not item.evidence_complete
        ),
        recovery_needed=frozenset(),
        explicit_user_requests=frozenset(),
        justified_deep=frozenset(),
        blocked_slots=frozenset(),
        risk_policy=baseline.risk_policy,
        selector_weights=baseline.selector_weights,
    )
    selected = select_maintenance(
        tuple(slots),
        context,
        tuple(selector_history),
    )
    ledger_ref = f"{repository}#{number}"
    if selected is None:
        return {
            "schema_version": MAINTENANCE_SELECTION_SCHEMA,
            "repository": repository,
            "control_ref": control_ref,
            "ledger_ref": ledger_ref,
            "catalog_digest": digest,
            "code_sha": head,
            "status": "NO_ELIGIBLE_WORK",
            "reason_code": "MAINTENANCE_EXHAUSTED",
        }

    generation = next_generation(
        history,
        repository,
        selected.slot.slot_id,
    )
    run_id = (
        f"audit:{repository}:{selected.slot.slot_id}:{generation}"
    )
    return {
        "schema_version": MAINTENANCE_SELECTION_SCHEMA,
        "repository": repository,
        "control_ref": control_ref,
        "ledger_ref": ledger_ref,
        "status": "SELECTED",
        "reason_code": "MAINTENANCE_SELECTED",
        "catalog_digest": digest,
        "code_sha": head,
        "selected": {
            "run_id": run_id,
            "slot_id": selected.slot.slot_id,
            "generation": generation,
            "lens": selected.slot.lens,
            "depth": selected.depth,
            "coverage_key": selected.slot.coverage_key,
            "scope": asdict(selected.slot.scope),
            "fingerprint": selected.fingerprint,
            "score": selected.score,
            "score_breakdown": [
                {"name": name, "value": value}
                for name, value in selected.score_breakdown.components
            ],
        },
        "evidence_refs": public.get("evidence_refs", []) + [ledger_ref],
    }
