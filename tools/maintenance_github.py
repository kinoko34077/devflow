from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class GitHubReadError(RuntimeError):
    pass


class GitHubReadTransport:
    def __init__(self, token: str, api_base: str = "https://api.github.com"):
        self._token = token
        self._api_base = api_base.rstrip("/")

    def _request_json(self, path: str) -> object:
        request = urllib.request.Request(
            self._api_base + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise GitHubReadError(f"GitHub read failed for {path}") from exc

    def get_repository(self, repository: str) -> dict[str, Any]:
        value = self._request_json(f"/repos/{repository}")
        if not isinstance(value, dict):
            raise GitHubReadError("repository response is not an object")
        return dict(value)

    def get_issue(self, repository: str, number: int) -> dict[str, Any]:
        value = self._request_json(f"/repos/{repository}/issues/{number}")
        if not isinstance(value, dict):
            raise GitHubReadError("issue response is not an object")
        return dict(value)


def _control_number(repository: str, control_ref: str) -> int:
    prefix = repository + "#"
    if not control_ref.startswith(prefix):
        raise GitHubReadError("control identity does not match repository")
    try:
        number = int(control_ref[len(prefix):])
    except ValueError as exc:
        raise GitHubReadError("control reference has invalid issue number") from exc
    if number <= 0:
        raise GitHubReadError("control reference has invalid issue number")
    return number


def collect_repository(
    transport: object,
    repository: str,
    control_ref: str,
    observed_at: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "repository": repository,
        "control_ref": control_ref,
        "observed_at": observed_at,
    }
    try:
        repo = transport.get_repository(repository)
        control = transport.get_issue(repository, _control_number(repository, control_ref))
    except GitHubReadError as exc:
        result["source_error"] = str(exc)
        return result

    result["repository_revision"] = repo.get("revision") or repo.get("default_branch")
    result["control"] = control
    return result


def collect_portfolio(
    transport: object,
    controls: list[dict[str, object]],
    observed_at: str,
) -> list[dict[str, object]]:
    values = [
        collect_repository(
            transport,
            str(control["repository"]),
            str(control["control_ref"]),
            observed_at,
        )
        for control in controls
    ]
    return sorted(values, key=lambda value: str(value["repository"]))
