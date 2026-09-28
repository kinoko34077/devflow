#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.repository_bootstrap import (  # noqa: E402
    BootstrapContext,
    BootstrapError,
    BootstrapExecutor,
    GitHubApi,
    is_trusted_association,
    normalize_request,
    parse_request_body,
)

DEVFLOW_REPOSITORY = "kinoko34077/devflow"
TITLE_PREFIX = "[REPO CREATE] "


class EventError(BootstrapError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EventError(f"cannot read GitHub event JSON: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise EventError("GitHub event root must be an object")
    return value


def _event_path(value: str | None) -> Path:
    resolved = value or os.environ.get("GITHUB_EVENT_PATH")
    if not resolved:
        raise EventError("GITHUB_EVENT_PATH or --event is required")
    return Path(resolved)


def _event_identity(event: dict[str, Any]) -> tuple[dict[str, Any], str, int, str]:
    issue = event.get("issue")
    repository = event.get("repository")
    if not isinstance(issue, dict) or not isinstance(repository, dict):
        raise EventError("GitHub event must contain issue and repository objects")
    full_name = repository.get("full_name")
    if full_name != DEVFLOW_REPOSITORY:
        raise EventError("GitHub event repository identity does not match devflow")
    number = issue.get("number")
    if not isinstance(number, int) or number <= 0:
        raise EventError("GitHub event Issue number is invalid")
    expected_url = f"https://github.com/{DEVFLOW_REPOSITORY}/issues/{number}"
    html_url = issue.get("html_url")
    if html_url != expected_url:
        raise EventError("GitHub event Issue URL does not match observed identity")
    return issue, full_name, number, expected_url


def _write_output(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise EventError(f"GitHub output {key} must be one line")
            handle.write(f"{key}={value}\n")


def _comment_validation_failure(
    repository: str,
    issue_number: int,
    message: str,
) -> None:
    token = os.environ.get("DEVFLOW_TOKEN", "")
    if not token:
        return
    api = GitHubApi(token)
    bounded = message.replace("\r", " ").replace("\n", " ")[:600]
    api.comment_issue(
        repository,
        issue_number,
        "Repository-Bootstrap-State: FAILED\n"
        "Stage: VALIDATION\n"
        "Safe-Retry: yes\n"
        "Created/Observed Resources:\n"
        "- none\n"
        f"Failure: {bounded}\n"
        "Next-Action: Correct this trusted `[REPO CREATE]` request and edit/reopen the Issue to retry.",
    )


def validate_event(event_path: Path, github_output: Path) -> int:
    try:
        event = _load_json(event_path)
        issue, repository, number, _ = _event_identity(event)
    except BootstrapError as exc:
        _write_output(
            github_output,
            {"candidate": "false", "valid": "false", "authorized": "false", "repository_name": ""},
        )
        print(f"repository-bootstrap event ignored: {exc}", file=sys.stderr)
        return 0

    title = issue.get("title")
    if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
        _write_output(
            github_output,
            {"candidate": "false", "valid": "false", "authorized": "false", "repository_name": ""},
        )
        return 0

    association = issue.get("author_association")
    authorized = isinstance(association, str) and is_trusted_association(association)
    if not authorized:
        _write_output(
            github_output,
            {"candidate": "true", "valid": "false", "authorized": "false", "repository_name": ""},
        )
        print("repository-bootstrap request author is not trusted", file=sys.stderr)
        return 0

    try:
        body = issue.get("body")
        raw = parse_request_body(body if isinstance(body, str) else "")
        request = normalize_request(raw, title)
    except BootstrapError as exc:
        _write_output(
            github_output,
            {"candidate": "true", "valid": "false", "authorized": "true", "repository_name": ""},
        )
        try:
            _comment_validation_failure(repository, number, str(exc))
        except Exception as comment_exc:
            print(
                f"repository-bootstrap validation failure comment could not be recorded: {type(comment_exc).__name__}",
                file=sys.stderr,
            )
        print(f"repository-bootstrap request invalid: {exc}", file=sys.stderr)
        return 0

    _write_output(
        github_output,
        {
            "candidate": "true",
            "valid": "true",
            "authorized": "true",
            "repository_name": request.repository.name,
        },
    )
    print(f"validated repository-bootstrap request for {request.repository.full_name}")
    return 0


def _record_missing_credential(
    repository: str,
    issue_number: int,
    token: str,
) -> None:
    if not token:
        return
    api = GitHubApi(token)
    api.comment_issue(
        repository,
        issue_number,
        "Repository-Bootstrap-State: FAILED\n"
        "Stage: VALIDATION\n"
        "Safe-Retry: after-human-decision\n"
        "Created/Observed Resources:\n"
        "- none\n"
        "Failure: approved repository bootstrap credential is not configured\n"
        "Next-Action: Human authorization is required before creating/configuring `REPOSITORY_BOOTSTRAP_TOKEN` or changing credential/permission state.",
    )


def execute_event(event_path: Path) -> int:
    event = _load_json(event_path)
    issue, repository, number, issue_url = _event_identity(event)
    title = issue.get("title")
    body = issue.get("body")
    association = issue.get("author_association")
    if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
        raise EventError("execute-event requires a [REPO CREATE] Issue")
    if not isinstance(association, str) or not is_trusted_association(association):
        raise EventError("execute-event request author is not trusted")
    raw = parse_request_body(body if isinstance(body, str) else "")
    request = normalize_request(raw, title)

    devflow_token = os.environ.get("DEVFLOW_TOKEN", "")
    bootstrap_token = os.environ.get("REPOSITORY_BOOTSTRAP_TOKEN", "")
    if not devflow_token:
        raise EventError("DEVFLOW_TOKEN is required")
    if not bootstrap_token:
        _record_missing_credential(repository, number, devflow_token)
        raise EventError("approved REPOSITORY_BOOTSTRAP_TOKEN is not configured")

    context = BootstrapContext(
        request_ref=f"{repository}#{number}",
        request_url=issue_url,
        devflow_repo=repository,
        request_issue_number=number,
        request_title=title,
        author_association=association,
    )
    result = BootstrapExecutor(
        GitHubApi(bootstrap_token),
        GitHubApi(devflow_token),
    ).execute(request, context)
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="devflow repository-bootstrap.v1 event runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-event")
    validate.add_argument("--event", help="GitHub event JSON path; defaults to GITHUB_EVENT_PATH")
    validate.add_argument("--github-output", required=True, help="GitHub Actions output file")

    execute = subparsers.add_parser("execute-event")
    execute.add_argument("--event", help="GitHub event JSON path; defaults to GITHUB_EVENT_PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        event_path = _event_path(args.event)
        if args.command == "validate-event":
            return validate_event(event_path, Path(args.github_output))
        if args.command == "execute-event":
            return execute_event(event_path)
        raise EventError(f"unknown command: {args.command}")
    except BootstrapError as exc:
        print(f"repository-bootstrap error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
