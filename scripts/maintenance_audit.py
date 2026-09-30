#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.maintenance_audit import (  # noqa: E402
    AuditContractError,
    classify_repository,
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
    portfolio.add_argument("--output")
    portfolio.set_defaults(func=_portfolio)

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
