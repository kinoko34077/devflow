from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


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

    def _request(self, path_or_url: str) -> tuple[Any, Any]:
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
        r"^(?:None(?:\\.|\\s|$)|No\\s+active(?:\\s|$))",
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
    managed = _scalar_section(sections, "Repository")
    trusted = (
        str(control.get("author_association") or "").upper()
        in TRUSTED_ASSOCIATIONS
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
    work_status = (
        _scalar_section(sections, "Work Status") or ""
    ).upper()
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
