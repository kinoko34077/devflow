#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.maintenance_audit import (  # noqa: E402
    AuditContractError,
    classify_repository,
)
from tools.maintenance_triage import triage  # noqa: E402
from tools.maintenance_sync_check import (  # noqa: E402
    SyncCheckContractError,
    build_sync_check_plan,
    canonical_body_sha256,
    execute_sync_check,
)
from tools.maintenance_supply import (  # noqa: E402
    MaintenanceSupplyError,
    build_existing_owner_candidate,
    extract_existing_admission,
    reconcile_control_projection_body,
)
from tools.maintenance_github import (  # noqa: E402
    DEVFLOW_REPOSITORY,
    GitHubReadError,
    GitHubReadTransport,
    collect_portfolio,
    collect_repository,
    discover_controls,
)

PORTFOLIO_SCHEMA = "maintenance-audit-portfolio.v1"
ERROR_SCHEMA = "maintenance-audit-error.v1"


def _utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _token_from_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise GitHubReadError(
            "required GitHub token environment variable is missing: "
            + name
        )
    return value


def _write(value: object, output: str | None) -> None:
    text_value = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
    if output:
        Path(output).write_text(text_value, encoding="utf-8")
    else:
        sys.stdout.write(text_value)


def _source_failure_report(
    observation: dict[str, object],
) -> dict[str, object]:
    material = {
        "repository": observation.get("repository"),
        "control_ref": observation.get("control_ref"),
        "source_status": observation.get("source_status"),
    }
    report_id = (
        "sha256:"
        + hashlib.sha256(
            _canonical_json(material).encode("utf-8")
        ).hexdigest()
    )
    return {
        "schema_version": "maintenance-audit-report.v1",
        "report_id": report_id,
        "repository": observation.get("repository"),
        "control_ref": observation.get("control_ref"),
        "observed_at": observation.get("observed_at"),
        "disposition": "NEEDS_EVIDENCE",
        "reason_codes": ["REQUIRED_SOURCE_UNAVAILABLE"],
        "finding_classes": [
            "SOURCE_UNAVAILABLE_OR_AMBIGUOUS"
        ],
        "owner_class": "UNKNOWN",
        "evidence_refs": list(
            observation.get("evidence_refs") or []
        ),
        "recheck_trigger": "SOURCE_RECOVERED",
    }


def _classify_observation(
    observation: dict[str, object],
) -> dict[str, object]:
    required = {"control_count", "control", "owner"}
    if not required.issubset(observation):
        return _source_failure_report(observation)
    return classify_repository(observation)


def _repository(args: argparse.Namespace) -> int:
    token = _token_from_env(args.token_env)
    transport = GitHubReadTransport(token)
    observed_at = args.observed_at or _utc_now()
    control_ref = f"{DEVFLOW_REPOSITORY}#{args.control}"
    observation = collect_repository(
        transport,
        args.repository,
        control_ref,
        observed_at,
    )
    report = _classify_observation(observation)
    _write(report, args.output)
    return 0


def _portfolio(args: argparse.Namespace) -> int:
    token = _token_from_env(args.token_env)
    transport = GitHubReadTransport(token)
    observed_at = args.observed_at or _utc_now()
    controls = discover_controls(transport)
    observations = collect_portfolio(
        transport,
        controls,
        observed_at,
    )
    reports = [
        _classify_observation(observation)
        for observation in observations
    ]
    payload = {
        "schema_version": PORTFOLIO_SCHEMA,
        "observed_at": observed_at,
        "repository_count": len(reports),
        "reports": reports,
    }
    if args.triage:
        payload["triage"] = [
            asdict(triage(report))
            for report in reports
        ]
    _write(payload, args.output)
    return 0


def _split_issue_ref(value: str) -> tuple[str, int]:
    if "#" not in value:
        raise SyncCheckContractError("Issue reference is malformed")
    repository, number = value.rsplit("#", 1)
    if (
        "/" not in repository
        or not number.isdigit()
        or int(number) < 1
    ):
        raise SyncCheckContractError("Issue reference is malformed")
    return repository, int(number)


def _sections(body: str) -> dict[str, str]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        if line.startswith("## "):
            current = line[3:].strip()
            result.setdefault(current, [])
        elif current is not None:
            result[current].append(line)
    return {
        key: "\n".join(lines).strip()
        for key, lines in result.items()
    }


def _scalar_section(sections: dict[str, str], name: str) -> str | None:
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


def _candidate_snapshot_from_body(
    body: str,
) -> tuple[list[str], bool, bool]:
    begin = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->"
    end = "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->"
    if body.count(begin) != 1 or body.count(end) != 1:
        raise SyncCheckContractError(
            "Control candidate projection block is missing or ambiguous"
        )
    start = body.index(begin) + len(begin)
    stop = body.index(end)
    if stop <= start:
        raise SyncCheckContractError(
            "Control candidate projection markers are out of order"
        )
    try:
        value = json.loads(body[start:stop].strip())
    except json.JSONDecodeError as exc:
        raise SyncCheckContractError(
            "Control candidate projection is invalid JSON"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("candidates"), list)
    ):
        raise SyncCheckContractError(
            "Control candidate projection schema is invalid"
        )
    tasks: list[str] = []
    human_gate = False
    external_wait = False
    for item in value["candidates"]:
        if not isinstance(item, dict) or not isinstance(item.get("task"), str):
            raise SyncCheckContractError(
                "Control candidate projection entry is invalid"
            )
        blocked = item.get("blocked")
        requires_confirmation = item.get("requires_user_confirmation")
        if not isinstance(blocked, bool) or not isinstance(
            requires_confirmation,
            bool,
        ):
            raise SyncCheckContractError(
                "candidate blocked/confirmation gates must be boolean"
            )
        tasks.append(item["task"])
        external_wait = external_wait or blocked
        human_gate = human_gate or requires_confirmation
    if len(set(tasks)) != len(tasks):
        raise SyncCheckContractError(
            "Control candidate projection contains duplicate task refs"
        )
    return tasks, human_gate, external_wait


def _candidate_tasks_from_body(body: str) -> list[str]:
    tasks, _human_gate, _external_wait = _candidate_snapshot_from_body(body)
    return tasks


class _SyncCheckGitHubTransport(GitHubReadTransport):
    def get_control(
        self,
        repository: str,
        control_ref: str,
    ) -> dict[str, object]:
        control_repo, number = _split_issue_ref(control_ref)
        issue = self.get_issue(control_repo, number)
        body = str(issue.get("body") or "")
        candidate_tasks, human_gate, external_wait = (
            _candidate_snapshot_from_body(body)
        )
        return {
            "repository": repository,
            "control_ref": control_ref,
            "body": body,
            "body_sha256": canonical_body_sha256(body),
            "candidate_tasks": candidate_tasks,
            "producer_active": False,
            "human_gate": human_gate,
            "reviewer_gate": False,
            "external_wait": external_wait,
            "security_gate": False,
        }

    def get_owner(
        self,
        repository: str,
        owner_ref: str,
    ) -> dict[str, object]:
        owner_repo, number = _split_issue_ref(owner_ref)
        if owner_repo != repository:
            raise SyncCheckContractError(
                "owner repository does not match audit repository"
            )
        issue = self.get_issue(owner_repo, number)
        body = str(issue.get("body") or "")
        sections = _sections(body)
        work_status = (_scalar_section(sections, "Work Status") or "").upper()
        state = str(issue.get("state") or "UNKNOWN").upper()
        terminal = state == "CLOSED" or work_status == "DONE"
        runnable = work_status in {
            "READY_FOR_IMPLEMENTATION",
            "AWAITING_REVIEW",
            "WORK_ORDER_READY",
        }
        return {
            "repository": repository,
            "owner_ref": owner_ref,
            "body_sha256": canonical_body_sha256(body),
            "state": state,
            "terminal": terminal,
            "runnable": runnable,
            "producer_active": work_status == "IMPLEMENTING",
            "human_gate": False,
            "reviewer_gate": work_status == "AWAITING_REVIEW",
            "external_wait": work_status in {"BLOCKED", "WAIT"},
            "security_gate": False,
        }

    def update_control_body(
        self,
        repository: str,
        control_ref: str,
        expected_body_sha256: str,
        body: str,
    ) -> bool:
        control_repo, number = _split_issue_ref(control_ref)
        live = self.get_issue(control_repo, number)
        live_body = str(live.get("body") or "")
        if canonical_body_sha256(live_body) != expected_body_sha256:
            return False

        payload = json.dumps({"body": body}).encode("utf-8")
        request = urllib.request.Request(
            self._url(
                f"/repos/{control_repo}/issues/{number}"
            ),
            data=payload,
            method="PATCH",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "kinotch-devflow-maintenance-sync-check",
            },
        )
        try:
            with self._opener(
                request,
                timeout=self._timeout,
            ) as response:
                raw = response.read()
                if raw:
                    value = json.loads(raw.decode("utf-8"))
                    if not isinstance(value, dict):
                        return False
        except urllib.error.HTTPError as exc:
            raise GitHubReadError(
                f"GitHub bounded Control update failed with HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            raise GitHubReadError(
                f"GitHub bounded Control update failed: {exc.reason}"
            ) from None
        return True

    def post_supply_transition(self, body: str) -> bool:
        if not isinstance(body, str) or not body.strip():
            raise MaintenanceSupplyError(
                "supply transition body must be non-empty"
            )
        payload = json.dumps({"body": body}).encode("utf-8")
        request = urllib.request.Request(
            self._url(
                "/repos/kinoko34077/devflow/issues/209/comments"
            ),
            data=payload,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "kinotch-devflow-maintenance-supply",
            },
        )
        try:
            with self._opener(
                request,
                timeout=self._timeout,
            ) as response:
                raw = response.read()
                if not raw:
                    return False
                try:
                    value = json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    return False
                return isinstance(value, dict)
        except urllib.error.HTTPError as exc:
            raise GitHubReadError(
                f"GitHub #209 transition comment failed with HTTP {exc.code}"
            ) from None
        except urllib.error.URLError:
            raise GitHubReadError(
                "GitHub #209 transition comment transport failed"
            ) from None


def _sync_check(args: argparse.Namespace) -> int:
    token = _token_from_env(args.token_env)
    transport = _SyncCheckGitHubTransport(token)
    observed_at = args.observed_at or _utc_now()
    control_ref = f"{DEVFLOW_REPOSITORY}#{args.control}"
    observation = collect_repository(
        transport,
        args.repository,
        control_ref,
        observed_at,
    )
    report = _classify_observation(observation)
    owner_ref = report.get("owner_ref")
    if not isinstance(owner_ref, str):
        payload = {
            "schema_version": "maintenance-sync-check-result.v1",
            "report": report,
            "plan": None,
            "result": None,
        }
        _write(payload, args.output)
        return 0

    control_snapshot = transport.get_control(
        args.repository,
        control_ref,
    )
    owner_snapshot = transport.get_owner(
        args.repository,
        owner_ref,
    )
    plan = build_sync_check_plan(
        report,
        control_snapshot,
        owner_snapshot,
    )
    if plan is None:
        payload = {
            "schema_version": "maintenance-sync-check-result.v1",
            "report": report,
            "plan": None,
            "result": None,
        }
        _write(payload, args.output)
        return 0

    payload: dict[str, object] = {
        "schema_version": "maintenance-sync-check-result.v1",
        "report": report,
        "plan": asdict(plan),
        "result": None,
    }
    if args.apply:
        payload["result"] = asdict(
            execute_sync_check(plan, transport)
        )
    _write(payload, args.output)
    return 0


def _owner_supply_snapshot(
    transport: _SyncCheckGitHubTransport,
    repository: str,
    owner_ref: str,
    admission: dict[str, object],
) -> dict[str, object]:
    owner_repo, number = _split_issue_ref(owner_ref)
    if owner_repo != repository:
        raise MaintenanceSupplyError(
            "owner repository does not match publication repository"
        )
    if admission.get("task") != owner_ref:
        raise MaintenanceSupplyError(
            "existing candidate admission does not match owner"
        )
    roles = admission.get("roles")
    if roles != [
        {
            "role": "implementer",
            "next_action_tag": "IMPLEMENT",
        }
    ]:
        raise MaintenanceSupplyError(
            "maintenance supply requires an existing implementer/IMPLEMENT admission"
        )

    issue = transport.get_issue(owner_repo, number)
    body = str(issue.get("body") or "")
    if not body.strip():
        raise MaintenanceSupplyError(
            "owning Issue body must be non-empty"
        )
    association = str(
        issue.get("author_association") or ""
    ).upper()
    trusted = association in {
        "OWNER",
        "MEMBER",
        "COLLABORATOR",
    }

    work_order_ref = admission.get("work_order_ref")
    if work_order_ref is not None:
        work_order_repo, work_order_number = _split_issue_ref(
            str(work_order_ref)
        )
        if work_order_repo != DEVFLOW_REPOSITORY:
            raise MaintenanceSupplyError(
                "work_order_ref must identify a devflow Work Order"
            )
        work_order = transport.get_issue(
            work_order_repo,
            work_order_number,
        )
        work_order_association = str(
            work_order.get("author_association") or ""
        ).upper()
        if (
            str(work_order.get("state") or "").lower() != "open"
            or "pull_request" in work_order
            or work_order_association
            not in {"OWNER", "MEMBER", "COLLABORATOR"}
            or not str(work_order.get("title") or "")
            .strip()
            .startswith("[WORK ORDER]")
        ):
            raise MaintenanceSupplyError(
                "work_order_ref does not resolve to a trusted open [WORK ORDER] Issue"
            )

    return {
        "task_ref": owner_ref,
        "repository": repository,
        "body_sha256": canonical_body_sha256(body),
        "state": str(issue.get("state") or "UNKNOWN").upper(),
        "work_status": admission.get("task_work_status"),
        "scope_ready": admission.get("scope_ready"),
        "blocked": admission.get("blocked"),
        "requires_user_confirmation": admission.get(
            "requires_user_confirmation"
        ),
        "conflict_keys": tuple(
            admission.get("conflict_keys") or ()
        ),
        "work_order_ref": admission.get("work_order_ref"),
        "trusted": trusted,
        "is_pull_request": "pull_request" in issue,
        "entry_ref": admission.get("entry_ref"),
        "human_gate": admission.get(
            "requires_user_confirmation"
        ),
        "reviewer_gate": False,
        "external_wait": admission.get("blocked"),
        "security_gate": False,
        "required_capabilities": (),
        "required_environment": (),
    }


def _control_supply_snapshot(
    transport: _SyncCheckGitHubTransport,
    repository: str,
    control_ref: str,
    *,
    owner_ref: str,
    observed_at: str,
    attempt_id: str,
) -> tuple[dict[str, object], str, dict[str, object] | None]:
    control_repo, number = _split_issue_ref(control_ref)
    issue = transport.get_issue(control_repo, number)
    body = str(issue.get("body") or "")
    sections = _sections(body)
    managed = _scalar_section(sections, "Repository")
    if managed != repository:
        raise MaintenanceSupplyError(
            "Control repository identity mismatch"
        )
    association = str(
        issue.get("author_association") or ""
    ).upper()
    next_action = sections.get("Next Action", "")
    admission = extract_existing_admission(
        body,
        repository=repository,
        control_ref=control_ref,
        task_ref=owner_ref,
    )
    observed = dt.datetime.fromisoformat(
        observed_at.replace("Z", "+00:00")
    )
    fresh_until = (
        observed + dt.timedelta(hours=1)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    snapshot: dict[str, object] = {
        "repository": repository,
        "control_ref": control_ref,
        "repository_state": (
            _scalar_section(sections, "Repository State")
            or ""
        ),
        "trusted": association
        in {"OWNER", "MEMBER", "COLLABORATOR"},
        "human_gate": (
            "[USER_DECISION]" in next_action
            or "[HUMAN_GATE]" in next_action
        ),
        "external_wait": False,
        "observed_at": observed_at,
        "fresh_until": fresh_until,
        "publisher_execution_attempt_id": attempt_id,
    }
    if admission is not None:
        snapshot["expected_owner_body_sha256"] = admission[
            "task_body_sha256"
        ]
    return snapshot, body, admission


def _publish_supply(args: argparse.Namespace) -> int:
    token = _token_from_env(args.token_env)
    transport = _SyncCheckGitHubTransport(token)
    observed_at = args.observed_at or _utc_now()
    control_ref = f"{DEVFLOW_REPOSITORY}#{args.control}"

    control_snapshot, control_body, admission = _control_supply_snapshot(
        transport,
        args.repository,
        control_ref,
        owner_ref=args.owner,
        observed_at=observed_at,
        attempt_id=args.attempt_id,
    )

    desired = None
    if admission is not None:
        owner_snapshot = _owner_supply_snapshot(
            transport,
            args.repository,
            args.owner,
            admission,
        )
        decision = {
            "action": "PUBLISH_EXISTING_OWNER",
            "report_id": (
                "sha256:"
                + hashlib.sha256(
                    (
                        args.repository
                        + "\0"
                        + args.owner
                        + "\0"
                        + args.work_class
                    ).encode("utf-8")
                ).hexdigest()
            ),
            "disposition": "AUTO_ADVANCE",
            "work_class": args.work_class,
            "owner_ref": args.owner,
            "reason_codes": ("EXISTING_OWNER_SUPPLY",),
        }
        desired = build_existing_owner_candidate(
            decision,
            owner_snapshot,
            control_snapshot,
        )

    edited, changed = reconcile_control_projection_body(
        control_body,
        desired,
        task_ref=args.owner,
    )
    payload: dict[str, object] = {
        "schema_version": "maintenance-supply-publication.v1",
        "repository": args.repository,
        "control_ref": control_ref,
        "owner_ref": args.owner,
        "work_class": args.work_class,
        "changed": changed,
        "desired_publication_id": (
            desired.get("publication_id")
            if isinstance(desired, dict)
            else None
        ),
        "applied": False,
    }
    if not changed or not args.apply:
        _write(payload, args.output)
        return 0

    expected = canonical_body_sha256(control_body)
    if not transport.update_control_body(
        args.repository,
        control_ref,
        expected,
        edited,
    ):
        raise MaintenanceSupplyError(
            "Control changed before bounded supply publication"
        )
    observed = transport.get_control(
        args.repository,
        control_ref,
    )
    if observed.get("body") != edited:
        raise MaintenanceSupplyError(
            "post-write Control body differs from intended supply projection"
        )

    action = "published" if desired is not None else "withdrawn"
    transition = (
        "## Stage-2 maintenance supply transition\n\n"
        f"- repository: `{args.repository}`\n"
        f"- owner: `{args.owner}`\n"
        f"- work_class: `{args.work_class}`\n"
        f"- action: **{action}**\n"
        f"- publisher attempt: `{args.attempt_id}`\n"
        "- authority: exact existing machine-readable candidate admission + "
        "owning Issue freshness; publication is not a runtime claim and cannot "
        "be consumed by the same execution attempt."
    )
    payload["applied"] = True
    payload["action"] = action
    try:
        transition_recorded = transport.post_supply_transition(
            transition
        )
    except GitHubReadError as exc:
        payload["transition_recorded"] = False
        payload["reporting_error"] = str(exc)
        _write(payload, args.output)
        return 2
    if not transition_recorded:
        payload["transition_recorded"] = False
        payload["reporting_error"] = (
            "supply changed but #209 transition comment was not confirmed"
        )
        _write(payload, args.output)
        return 2
    payload["transition_recorded"] = True
    _write(payload, args.output)
    return 0


def _summarize(args: argparse.Namespace) -> int:
    value = json.loads(
        Path(args.input).read_text(encoding="utf-8")
    )
    reports = value.get("reports") if isinstance(value, dict) else None
    if not isinstance(reports, list):
        reports = (
            [value]
            if isinstance(value, dict)
            and "disposition" in value
            else []
        )

    counts = Counter(
        str(report.get("disposition", "UNKNOWN"))
        for report in reports
        if isinstance(report, dict)
    )
    print("## Maintenance audit")
    print()
    print(f"Repositories: {len(reports)}")
    for disposition in sorted(counts):
        print(f"- {disposition}: {counts[disposition]}")

    findings: list[str] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        classes = report.get("finding_classes") or []
        if classes:
            findings.append(
                f"{report.get('repository')}: "
                + ", ".join(str(item) for item in classes)
            )
    if findings:
        print("\nFindings:")
        for item in findings:
            print(f"- {item}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only Stage-2 maintenance auditor"
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    repository = sub.add_parser("repository")
    repository.add_argument("--repository", required=True)
    repository.add_argument(
        "--control",
        required=True,
        type=int,
    )
    repository.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
    )
    repository.add_argument("--observed-at")
    repository.add_argument("--output")
    repository.set_defaults(func=_repository)

    portfolio = sub.add_parser("portfolio")
    portfolio.add_argument(
        "--token-env",
        default="MAINTENANCE_AUDIT_TOKEN",
    )
    portfolio.add_argument("--observed-at")
    portfolio.add_argument(
        "--triage",
        action="store_true",
        help="include deterministic triage decisions",
    )
    portfolio.add_argument("--output")
    portfolio.set_defaults(func=_portfolio)

    sync_check = sub.add_parser("sync-check")
    sync_check.add_argument("--repository", required=True)
    sync_check.add_argument(
        "--control",
        required=True,
        type=int,
    )
    sync_check.add_argument(
        "--token-env",
        default="MAINTENANCE_SYNC_TOKEN",
    )
    sync_check.add_argument("--observed-at")
    sync_check.add_argument("--output")
    sync_check.add_argument(
        "--apply",
        action="store_true",
        help="apply the single allowlisted Control projection repair",
    )
    sync_check.set_defaults(func=_sync_check)

    publish = sub.add_parser("publish-supply")
    publish.add_argument("--repository", required=True)
    publish.add_argument(
        "--control",
        required=True,
        type=int,
    )
    publish.add_argument("--owner", required=True)
    publish.add_argument(
        "--work-class",
        required=True,
        choices=(
            "audit",
            "triage",
            "sync-check",
            "quickfix",
            "implementation",
        ),
    )
    publish.add_argument("--attempt-id", required=True)
    publish.add_argument(
        "--token-env",
        default="MAINTENANCE_SUPPLY_TOKEN",
    )
    publish.add_argument("--observed-at")
    publish.add_argument("--output")
    publish.add_argument(
        "--apply",
        action="store_true",
        help="apply bounded existing-owner supply publication/withdrawal",
    )
    publish.set_defaults(func=_publish_supply)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("--input", required=True)
    summarize.set_defaults(func=_summarize)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (
        GitHubReadError,
        AuditContractError,
        SyncCheckContractError,
        MaintenanceSupplyError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        error = {
            "schema_version": ERROR_SCHEMA,
            "error": type(exc).__name__,
            "message": str(exc),
        }
        output = getattr(args, "output", None)
        _write(error, output)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
