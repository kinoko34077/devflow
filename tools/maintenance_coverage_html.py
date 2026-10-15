"""Standalone, offline-only SMC audit-coverage viewer.

Derived from already validated, read-only Ledger observations. Rendering adds
no GitHub requests, audit claims, browser storage, network assets or mutations.
"""
from __future__ import annotations

import base64
import hashlib
import html
import re
from typing import Mapping

from tools.maintenance_coverage_report import REPORT_SCHEMA

_CSS = """
:root { color-scheme: light dark; font: 16px/1.5 system-ui, -apple-system, sans-serif; }
body { margin: 0; padding: 1.2rem; max-width: 1400px; margin-inline: auto; }
h1 { font-size: 1.4rem; margin: 0 0 .5rem; }
h2 { font-size: 1.12rem; margin-top: 1.6rem; }
p, .hint { max-width: 90ch; }
.hint, footer, small { opacity: .85; }
.controls { display: flex; flex-wrap: wrap; gap: .8rem; padding-block: .7rem; }
.controls label { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
select { font: inherit; min-height: 2.4rem; max-width: 100%; padding-inline: .5rem; }
.table-wrap { max-width: 100%; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { border-bottom: 1px solid currentColor; padding: .55rem .7rem; text-align: start; vertical-align: top; }
th { font-weight: 650; }
tbody tr:focus-within { outline: 2px solid currentColor; outline-offset: -2px; }
td { overflow-wrap: anywhere; }
.reason { max-width: 34ch; }
code { font-size: .87em; overflow-wrap: anywhere; }
a { text-underline-offset: .15rem; }
.summary { font-weight: 600; }
[hidden] { display: none !important; }
@media (max-width: 640px) {
  body { padding: .8rem; }
  h1 { font-size: 1.2rem; }
  table { min-width: 740px; }
  .controls { display: block; }
  .controls label { margin-bottom: .7rem; }
}
"""

_JS = """
(function () {
  'use strict';
  const byId = id => document.getElementById(id);
  const repository = byId('repository-filter');
  const status = byId('status-filter');
  const counter = byId('visible-count');
  const rows = Array.from(document.querySelectorAll('#coverage-rows tr'));
  function update() {
    let visible = 0;
    for (const row of rows) {
      const acceptedRepo = repository.value === 'all' || row.dataset.repo === repository.value;
      const acceptedStatus = status.value === 'all' || row.dataset.status === status.value;
      row.hidden = !(acceptedRepo && acceptedStatus);
      if (!row.hidden) visible += 1;
    }
    counter.textContent = String(visible) + ' / ' + String(rows.length) + ' rows';
  }
  repository.addEventListener('change', update);
  status.addEventListener('change', update);
  update();
}());
"""


def _escape(value: object) -> str:
    return html.escape("—" if value is None else str(value), quote=True)


def _csp_hash(source: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(source.encode("utf-8")).digest()).decode("ascii") + "'"


def _evidence(value: object, repository: str) -> str:
    if value is None:
        return "—"
    text = str(value)
    # Avoid turning arbitrary untrusted issue text/URLs into navigable links.
    expected = re.escape("https://github.com/" + repository + "/issues/")
    if re.fullmatch(expected + r"[1-9][0-9]*#issuecomment-[1-9][0-9]*", text):
        safe = _escape(text)
        return '<a href="' + safe + '" rel="noopener noreferrer">' + safe + '</a>'
    return _escape(text)


def render_coverage_html(report: Mapping[str, object]) -> str:
    """Render an escaped, no-network, filterable local HTML report.

    The input must be an accepted coverage report, not a raw GitHub comment.
    All user-controlled fields are escaped; no arbitrary URLs become links.
    """
    if not isinstance(report, Mapping) or report.get("schema_version") != REPORT_SCHEMA:
        raise ValueError("unsupported SMC coverage report schema")
    repos = report.get("repositories")
    rows = report.get("rows")
    if not isinstance(repos, list) or not isinstance(rows, list):
        raise ValueError("coverage report must contain repository and row arrays")
    if report.get("repository_count") != len(repos) or report.get("row_count") != len(rows):
        raise ValueError("coverage report row/repository count does not match")
    canonical: set[str] = set()
    for repo in repos:
        if not isinstance(repo, dict):
            raise ValueError("invalid repository summary row")
        name = repo.get("repository")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
            raise ValueError("untrusted repository identity")
        if name in canonical:
            raise ValueError("duplicate repository in coverage report")
        canonical.add(name)
    statuses = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("repository") not in canonical:
            raise ValueError("invalid or foreign coverage row")
        status = row.get("status")
        if not isinstance(status, str) or not re.fullmatch(r"[A-Z][A-Z_]*", status):
            raise ValueError("invalid coverage status")
        statuses.add(status)
    links = []
    for repo in repos:
        counts = repo.get("coverage_states")
        if not isinstance(counts, dict):
            raise ValueError("missing repository coverage counts")
        stats = ", ".join(str(k) + "=" + str(v) for k, v in sorted(counts.items()))
        links.append("<tr><td>" + _escape(repo["repository"]) +
                     "</td><td>" + _escape(repo.get("ledger_issue_number")) +
                     "</td><td>" + _escape(repo.get("slot_depth_rows")) +
                     "</td><td>" + _escape(repo.get("noncredit_record_count")) +
                     "</td><td>" + _escape(stats) + "</td></tr>")
    rendered = []
    for row in rows:
        repo = row["repository"]
        state = row["status"]
        cells = (
            repo,
            str(row.get("scope_kind", "")) + ":" + str(row.get("scope_selector", "")),
            row.get("lens"),
            row.get("depth"),
            state,
            row.get("reason"),
            row.get("completed_at"),
        )
        rendered.append('<tr data-repo="' + _escape(repo) +
                        '" data-status="' + _escape(state) + '">' +
                        "".join("<td>" + _escape(cell) + "</td>" for cell in cells) +
                        "<td>" + _evidence(row.get("evidence_url"), repo) + "</td></tr>")
    repo_options = "".join('<option value="' + _escape(name) + '">' +
                           _escape(name) + "</option>" for name in sorted(canonical))
    status_options = "".join('<option value="' + _escape(state) + '">' +
                             _escape(state) + "</option>" for state in sorted(statuses))
    limits = report.get("limits")
    if not isinstance(limits, list) or not all(isinstance(t, str) for t in limits):
        raise ValueError("coverage limitations unavailable")
    limitations = "".join("<li>" + _escape(value) + "</li>" for value in limits)
    policy = ("default-src 'none'; base-uri 'none'; form-action 'none'; "
              "connect-src 'none'; img-src 'none'; frame-src 'none'; "
              "style-src " + _csp_hash(_CSS) + "; "
              "script-src " + _csp_hash(_JS))
    return (
        '<!doctype html>\n<html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="' + _escape(policy) + '">'
        '<title>SMC 多角的監査カバレッジ — 読み取り専用</title>'
        '<style>' + _CSS + '</style></head><body>'
        '<h1>SMC 多角的監査カバレッジ</h1>'
        '<p class="summary">読み取り専用の監査履歴表示です。'
        'ATTESTED_SCOPE_MATCH は監査対象の記録一致を示すだけで、実際の監査内容の完了証明ではありません。</p>'
        '<p class="hint">未検証・履歴不足・監査失敗を検証済みに変換しません。'
        '対象は認可済みPILOTの読み取り結果に限定します。</p>'
        '<h2>リポ別状況</h2><div class="table-wrap"><table>'
        '<thead><tr><th>リポ</th><th>Ledger</th><th>観点×深度</th><th>未完了</th><th>状態内訳</th>'
        '</tr></thead><tbody>' + "".join(links) + '</tbody></table></div>'
        '<h2>監査観点別の状態</h2><div class="controls">'
        '<label for="repository-filter">リポ <select id="repository-filter">'
        '<option value="all">すべて</option>' + repo_options + '</select></label>'
        '<label for="status-filter">判定 <select id="status-filter">'
        '<option value="all">すべて</option>' + status_options + '</select></label>'
        '<span id="visible-count" role="status" aria-live="polite">' +
        str(len(rows)) + ' / ' + str(len(rows)) + ' rows</span></div>'
        '<div class="table-wrap"><table><thead><tr><th>リポ</th><th>範囲</th>'
        '<th>観点</th><th>深度</th><th>判定</th><th>理由</th><th>最終記録</th>'
        '<th>根拠</th></tr></thead><tbody id="coverage-rows">' +
        "".join(rendered) + '</tbody></table></div>'
        '<h2>制限事項</h2><ul>' + limitations + '</ul>'
        '<footer>ローカル表示。外部送信・永続保存・監査実行・GitHubへの書込みは行いません。</footer>'
        '<script>' + _JS + '</script></body></html>\n'
    )
