#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import devflow_mcp_core  # noqa: E402


SCHEMA_VERSION = "repository-projection-shadow.v1"


def _compact_text(value: object, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _machine_record_count(repository: dict[str, Any]) -> int:
    counts = repository.get("machine_type_counts") or {}
    if not isinstance(counts, dict):
        return 0
    return sum(
        value
        for value in counts.values()
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )


def build_shadow_report(
    portfolio: dict[str, Any],
    controls: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    repositories = portfolio.get("repositories")
    if not isinstance(repositories, list):
        raise ValueError("portfolio repositories must be an array")

    rows: list[dict[str, Any]] = []
    for item in repositories:
        if not isinstance(item, dict):
            raise ValueError("portfolio repository entry must be an object")
        repository = item.get("repository")
        if not isinstance(repository, str) or not repository:
            raise ValueError("portfolio repository identity is required")
        control = controls.get(repository)
        if not isinstance(control, dict):
            raise ValueError(f"missing Control comparison for {repository}")
        task_records = item.get("task_records") or []
        if not isinstance(task_records, list):
            raise ValueError("task_records must be an array")
        rows.append(
            {
                "repository": repository,
                "source_status": item.get("source_status"),
                "source_freshness": item.get("source_freshness"),
                "source_error": item.get("source_error"),
                "open_issue_count": item.get("open_issue_count", 0),
                "machine_record_count": _machine_record_count(item),
                "machine_task_count": item.get("machine_task_count", 0),
                "legacy_hint_count": item.get("legacy_hint_count", 0),
                "unclassified_count": item.get("unclassified_count", 0),
                "invalid_metadata_count": item.get("invalid_metadata_count", 0),
                "untrusted_metadata_count": item.get("untrusted_metadata_count", 0),
                "machine_type_counts": item.get("machine_type_counts") or {},
                "legacy_hint_type_counts": item.get("legacy_hint_type_counts") or {},
                "machine_task_refs": [
                    f"{repository}#{record.get('issue_number')}"
                    for record in task_records
                    if isinstance(record, dict)
                    and isinstance(record.get("issue_number"), int)
                ],
                "control_issue_number": control.get("issue_number"),
                "control_work_status": control.get("work_status"),
                "control_active_work_excerpt": _compact_text(
                    control.get("active_work")
                ),
                "control_active_work_text_present": bool(
                    str(control.get("active_work") or "").strip()
                ),
                "machine_metadata_coverage_complete": (
                    int(item.get("open_issue_count", 0))
                    == _machine_record_count(item)
                ),
            }
        )

    rows.sort(key=lambda item: str(item["repository"]).casefold())
    open_issue_count = int(portfolio.get("open_issue_count") or 0)
    legacy = int(portfolio.get("legacy_hint_count") or 0)
    unclassified = int(portfolio.get("unclassified_count") or 0)
    invalid = int(portfolio.get("invalid_metadata_count") or 0)
    untrusted = int(portfolio.get("untrusted_metadata_count") or 0)
    legacy_or_unclassified = legacy + unclassified
    non_machine = legacy_or_unclassified + invalid + untrusted
    machine_record_count = sum(
        int(item["machine_record_count"]) for item in rows
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": portfolio.get("observed_at"),
        "repository_count": int(portfolio.get("repository_count") or 0),
        "source_unavailable_count": int(
            portfolio.get("source_unavailable_count") or 0
        ),
        "open_issue_count": open_issue_count,
        "machine_record_count": machine_record_count,
        "machine_task_count": int(portfolio.get("machine_task_count") or 0),
        "legacy_hint_count": legacy,
        "unclassified_count": unclassified,
        "invalid_metadata_count": invalid,
        "untrusted_metadata_count": untrusted,
        "legacy_or_unclassified_count": legacy_or_unclassified,
        "legacy_or_unclassified_rate": (
            legacy_or_unclassified / open_issue_count if open_issue_count else 0.0
        ),
        "non_machine_metadata_count": non_machine,
        "machine_metadata_coverage_rate": (
            machine_record_count / open_issue_count if open_issue_count else 1.0
        ),
        "repositories_with_machine_tasks": sum(
            1 for item in rows if int(item["machine_task_count"]) > 0
        ),
        "repositories_with_open_issues_without_machine_tasks": sum(
            1
            for item in rows
            if int(item["open_issue_count"]) > 0
            and int(item["machine_task_count"]) == 0
        ),
        "operator_decision_ambiguous_repository_count": sum(
            1
            for item in rows
            if int(item["open_issue_count"]) > 0
            and not bool(item["machine_metadata_coverage_complete"])
        ),
        "repositories_with_control_active_work_text": sum(
            1 for item in rows if item["control_active_work_text_present"]
        ),
        "repositories": rows,
    }


def collect_shadow(service: devflow_mcp_core.DevflowService) -> dict[str, Any]:
    portfolio = service.get_portfolio_projection()
    repositories = portfolio.get("repositories")
    if not isinstance(repositories, list):
        raise devflow_mcp_core.DevflowMCPError(
            "portfolio projection repositories were not an array"
        )
    controls: dict[str, dict[str, Any]] = {}
    for item in repositories:
        if not isinstance(item, dict):
            raise devflow_mcp_core.DevflowMCPError(
                "portfolio projection repository entry was not an object"
            )
        repository = item.get("repository")
        if not isinstance(repository, str) or not repository:
            raise devflow_mcp_core.DevflowMCPError(
                "portfolio projection repository identity is missing"
            )
        controls[repository] = service.get_repository_control(repository)
    return build_shadow_report(portfolio, controls)


def _write_report(report: dict[str, Any], output: str) -> None:
    Path(output).write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only Repository Projection fleet shadow."
    )
    parser.add_argument(
        "--token-env",
        default="MAINTENANCE_AUDIT_TOKEN",
        help="Environment variable containing a read-capable GitHub token.",
    )
    parser.add_argument(
        "--output",
        default="repository-projection-shadow.json",
    )
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        raise SystemExit(
            f"required read token environment variable is missing: {args.token_env}"
        )
    service = devflow_mcp_core.DevflowService(
        devflow_mcp_core.GitHubReader(token=token)
    )
    report = collect_shadow(service)
    _write_report(report, args.output)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "repository_count",
                    "source_unavailable_count",
                    "open_issue_count",
                    "machine_record_count",
                    "machine_task_count",
                    "legacy_hint_count",
                    "unclassified_count",
                    "invalid_metadata_count",
                    "untrusted_metadata_count",
                    "legacy_or_unclassified_rate",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
