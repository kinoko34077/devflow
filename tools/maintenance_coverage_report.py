"""Derived, noncanonical SMC multi-angle coverage table.

This is a presentation layer for trusted GitHub Ledger observations, not an
audit runner, runtime claim/queue, or completion writer. An exact legacy v1
record never means current coverage is verified.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Sequence

from tools.maintenance_coverage_github import CoverageObservation

REPORT_SCHEMA = "smc-coverage-report.v1"


def build_coverage_report(observations: Sequence[CoverageObservation]) -> dict[str, object]:
    by_repo: dict[str, CoverageObservation] = {}
    for observed in observations:
        if observed.repository in by_repo:
            raise ValueError("duplicate repository coverage observation")
        by_repo[observed.repository] = observed

    rows: list[dict[str, object]] = []
    repositories: list[dict[str, object]] = []
    totals: Counter[str] = Counter()
    for repo, snapshot in sorted(by_repo.items()):
        counts = Counter(row.status for row in snapshot.rows)
        totals.update(counts)
        repositories.append({
            "repository": repo,
            "ledger_issue_number": snapshot.ledger_issue_number,
            "catalog_blob_sha": snapshot.catalog_blob_sha,
            "slot_depth_rows": len(snapshot.rows),
            "comments_scanned": snapshot.comments_scanned,
            "machine_records": snapshot.machine_records,
            "attested_records": snapshot.attested_records,
            "substantive_record_count": snapshot.substantive_legacy_records,
            "noncredit_record_count": snapshot.noncredit_records,
            "untrusted_record_count": snapshot.untrusted_records,
            "active_run_id": snapshot.active_run_id,
            "coverage_states": dict(sorted(counts.items())),
        })
        for row in sorted(
            snapshot.rows, key=lambda r: (r.slot_id, r.depth, r.scope_kind, r.scope_selector)
        ):
            if row.repository != repo:
                raise ValueError("row source does not match repository")
            rows.append(asdict(row))
    return {
        "schema_version": REPORT_SCHEMA,
        "repository_count": len(repositories),
        "row_count": len(rows),
        "coverage_state_counts": dict(sorted(totals.items())),
        "repositories": repositories,
        "rows": rows,
        "limits": [
            "No historical v1 run is automatically current-scope verified",
            "ATTESTED_SCOPE_MATCH is metadata binding, not independent audit proof",
            "Missing external freshness is UNKNOWN, never silently marked complete",
            "This report is not canonical task/claim or a fleet-wide audit acceptance",
        ],
    }


def _cell(value: object) -> str:
    if value is None:
        return "—"
    return (str(value).replace("\\", "\\\\").replace("|", "\\|")
            .replace("\n", " ").replace("\r", " ").replace("`", "'"))


def render_coverage_markdown(report: dict[str, object]) -> str:
    if report.get("schema_version") != REPORT_SCHEMA:
        raise ValueError("unknown coverage report version")
    out = [
        "# SMC 多角的監査カバレッジ（読み取り専用）",
        "",
        "各リポの真正な Audit Ledger から導出した状態。"
        " **ATTESTED_SCOPE_MATCH も監査内容そのものの完了証明ではありません。**",
        "",
        "## 対象リポ",
        "",
        "| リポ | Ledger | 観点×深度 | 実行記録 | 未完了・不信任 | 状態内訳 |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for item in report["repositories"]:
        out.append("| " + " | ".join(_cell(value) for value in (
            item["repository"], f"#{item['ledger_issue_number']}",
            item["slot_depth_rows"], item["machine_records"],
            item["noncredit_record_count"] + item["untrusted_record_count"],
            ", ".join(f"{k}={v}" for k, v in item["coverage_states"].items()),
        )) + " |")
    out += [
        "",
        "## 監査観点別の状態",
        "",
        "| リポ | 範囲 | Lens | 深度 | 判定 | 最終記録 | 根拠 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["rows"]:
        scope = str(row["scope_kind"]) + ":" + str(row["scope_selector"])
        out.append("| " + " | ".join(_cell(value) for value in (
            row["repository"], scope, row["lens"], row["depth"],
            row["status"], row["completed_at"], row["evidence_url"],
        )) + " |")
    out += [
        "",
        "## 解釈上の制限",
        "",
    ]
    out += ["- " + _cell(item) for item in report["limits"]]
    return "\n".join(out) + "\n"
