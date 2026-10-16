"""Standalone offline Project-like HTML for already verified KAEP search-list results.

Presentation only. No GitHub client/API, credentials, telemetry, storage,
external assets, remote scripts or background refresh. The canonical reader,
reply status and source validation are supplied by kaep_issue_search_view.
"""
from __future__ import annotations

import base64
import hashlib
import html
import re
from typing import Any

ISSUE_LINK = re.compile(
    r"https://github\.com/kinoko34077/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*\Z"
)
COMMENT_LINK = re.compile(
    r"https://github\.com/kinoko34077/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*"
    r"#issuecomment-[1-9][0-9]*\Z"
)

CSS = r"""
:root{color-scheme:light;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#17212c;background:#f6f8fb}
*{box-sizing:border-box}body{margin:0}main{max-width:1440px;margin:auto;padding:22px 20px 60px}
h1{font-size:1.42rem;letter-spacing:-.02em;margin:0 0 6px}h2{font-size:1rem;margin:0}
p{line-height:1.45}a{color:#1554a1;text-decoration:none}a:hover{text-decoration:underline}
.meta{font-size:.85rem;color:#506072;margin:0 0 16px}.notice{padding:12px 14px;border:1px solid #aabacb;border-radius:8px;background:#fff;line-height:1.5;margin:12px 0}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
.stat{background:#fff;border:1px solid #dbe2e9;border-radius:10px;min-width:132px;flex:1;padding:12px}
.stat strong{display:block;font-size:1.32rem;font-variant-numeric:tabular-nums}
.stat span{font-size:.78rem;color:#516174}
.controls{display:grid;grid-template-columns:minmax(190px,2fr) repeat(3,minmax(110px,1fr));gap:10px;background:#fff;border:1px solid #dbe2e9;padding:12px;border-radius:10px;margin:14px 0}
.control{display:flex;flex-direction:column;gap:4px;font-size:.78rem;font-weight:600;color:#3e4c5d}
input,select{font:inherit;font-size:.9rem;width:100%;border:1px solid #b8c6d4;border-radius:6px;background:#fff;color:#17212c;padding:8px;min-height:36px}
.tableframe{width:100%;overflow:auto;border:1px solid #dbe2e9;border-radius:10px;background:#fff}
table{border-collapse:collapse;width:100%;min-width:1040px;font-size:.83rem}
th{position:sticky;top:0;background:#f0f4f8;text-align:left;color:#314052;font-weight:650;white-space:nowrap}
th,td{padding:10px 12px;border-bottom:1px solid #ecf0f4;vertical-align:top}
td:nth-child(2){max-width:330px;min-width:180px;overflow-wrap:anywhere}
td:nth-child(1){white-space:nowrap;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}tr[hidden]{display:none}tbody tr:hover{background:#fafcff}
.small{font-size:.74rem;color:#576677} .pill{display:inline-block;background:#f1f4f8;color:#384b60;padding:3px 7px;border-radius:5px;font-size:.76rem}
.unknown{font-weight:650;color:#704710}.footer{font-size:.77rem;color:#566677;margin-top:14px}
details{background:#fff;border:1px solid #dbe2e9;border-radius:8px;padding:10px 13px;margin:12px 0;font-size:.83rem}
summary{cursor:pointer;font-weight:650}.errors{margin:10px 0 0;padding-left:24px;overflow-wrap:anywhere} .count{margin:10px 0;color:#435366;font-size:.83rem}
@media(max-width:850px){main{padding:16px 12px}.controls{grid-template-columns:repeat(2,minmax(0,1fr))}.stat{min-width:120px}}
@media(max-width:480px){.controls{grid-template-columns:1fr}.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}}
"""

JS = r"""
(function(){
  "use strict";
  const table=document.getElementById("entries");
  const body=table.tBodies[0];
  const rows=Array.from(body.rows);
  const search=document.getElementById("q");
  const selects=["repository","role","state","recipient","reply","validation"];
  function fillOptions(){
    for(const key of selects){
      const sel=document.getElementById(key);
      const opts=Array.from(new Set(rows.map(row=>row.dataset[key]).filter(Boolean))).sort();
      for(const val of opts){const o=document.createElement("option");o.value=val;o.textContent=val;sel.appendChild(o);}
    }
  }
  function update(){
    const q=search.value.toLocaleLowerCase().trim();
    let shown=0;
    for(const row of rows){
      const match=(!q||row.dataset.search.includes(q)) &&
        selects.every(key=>!document.getElementById(key).value ||
          row.dataset[key]===document.getElementById(key).value);
      row.hidden=!match;
      if(match)shown++;
    }
    document.getElementById("shown").textContent=shown+" / "+rows.length+" 件（限定検索対象）";
  }
  function sort(){
    const mode=document.getElementById("sort").value;
    const compare=(a,b)=>{
      if(mode==="issue-asc"||mode==="issue-desc"){
        const c=a.dataset.repository.localeCompare(b.dataset.repository) ||
          Number(a.dataset.number)-Number(b.dataset.number);
        return mode==="issue-desc"?-c:c;
      }
      const c=a.dataset[mode].localeCompare(b.dataset[mode]);
      return c||Number(a.dataset.number)-Number(b.dataset.number);
    };
    rows.sort(compare);
    for(const row of rows)body.appendChild(row);
    update();
  }
  fillOptions();
  search.addEventListener("input",update);
  for(const key of selects)document.getElementById(key).addEventListener("change",update);
  document.getElementById("sort").addEventListener("change",sort);
  sort();
})();
"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else "-"), quote=True)


def _safe_link(value: Any, *, source: bool) -> str | None:
    if type(value) is not str:
        return None
    pattern = COMMENT_LINK if source else ISSUE_LINK
    return value if pattern.fullmatch(value) else None


def _anchor(value: Any, label: str, *, source: bool) -> str:
    link = _safe_link(value, source=source)
    return (f'<a href="{_esc(link)}" target="_blank" rel="noopener noreferrer">'
            f'{_esc(label)}</a>') if link else _esc(label) + "（リンク未検証）"


def _hash(source: str) -> str:
    return base64.b64encode(hashlib.sha256(source.encode("utf-8")).digest()).decode("ascii")


def to_html(result: dict[str, Any]) -> str:
    """Render a local interactive table; all source data remains inert text."""
    rows = result.get("rows", [])
    errors = result.get("errors", [])
    if type(rows) is not list or type(errors) is not list:
        raise ValueError("INVALID_DISPLAY_RESULT")
    cells = []
    for row in rows:
        if type(row) is not dict:
            raise ValueError("INVALID_DISPLAY_ROW")
        repo = str(row.get("repository") or "-")
        role = str(row.get("issue_role") or "UNCLASSIFIED")
        issue_type = str(row.get("issue_type") or "-")
        state = str(row.get("issue_state") or "-")
        recipient = str(row.get("recipient") or "-")
        reply = str(row.get("reply_observation") or "UNKNOWN")
        validation = str(row.get("source_validation") or "UNKNOWN")
        number = row.get("issue_number")
        if type(number) is not int or number < 1:
            raise ValueError("INVALID_DISPLAY_ISSUE")
        title = str(row.get("title_hint") or "")
        intent = str(row.get("intent") or "-")
        comment_id = row.get("source_comment_id")
        marker = f"#{number}"
        sourcelabel = f"コメント {comment_id}" if type(comment_id) is int else "原典"
        text_search = " ".join((repo, marker, title, role, issue_type, state,
                                recipient, intent, reply, validation)).lower()
        attr = {
            "repository": repo, "role": role, "state": state,
            "recipient": recipient, "reply": reply, "validation": validation,
            "number": str(number), "search": text_search,
        }
        data = " ".join(f'data-{key}="{_esc(value)}"' for key, value in attr.items())
        source_status = ("unknown" if validation != "STRICT_COMPLETE_FOR_CANDIDATE" else "")
        cells.append(
            f"<tr {data}><td>{_anchor(row.get('issue_url'), repo.split('/')[-1]+' '+marker, source=False)}</td>"
            f"<td>{_esc(title)}</td><td>{_esc(state)}</td>"
            f"<td><span class='pill'>{_esc(role)}</span><div class='small'>{_esc(issue_type)}</div></td>"
            f"<td>{_esc(recipient)}<div class='small'>{_esc(intent)}</div></td>"
            f"<td>{_esc(reply)}</td><td class='{source_status}'>{_esc(validation)}</td>"
            f"<td>{_anchor(row.get('source_url'), sourcelabel, source=True)}</td></tr>"
        )
    diagnostic = []
    if result.get("reason_code"):
        diagnostic.append("<li>読取失敗: " + _esc(result["reason_code"]) + "</li>")
    for err in errors:
        if type(err) is not dict:
            continue
        url = err.get("owning_issue")
        label = _anchor(url, "Issue", source=False) if url else _esc(err.get("repository") or "一般")
        diagnostic.append(f"<li>{label}: {_esc(err.get('reason_code') or 'UNKNOWN')}"
                          f" (comment {_esc(err.get('comment_id') or '-')})</li>")
    if not diagnostic:
        diagnostic.append("<li>今回の取得範囲で検出された診断エラーはありません。</li>")
    partial = result.get("status") != "BOUNDED_SEARCH_READ" or errors
    label = "一部不明（PARTIAL / UNKNOWN）" if partial else "限定取得（完全性未保証）"
    meta = (
        "候補検索であり、全Issueの網羅性・現在のHEAD・AIによる受信や返信を保証しません。"
        "この一覧だけで実行を許可せず、原典Issueを再検証してください。"
        "手動Controlと#503の経路は維持されます。"
    )
    summary = [
        ("候補Issue数", result.get("searched_candidates", "?")),
        ("原典検証済みIssue数", result.get("validated_source_issues", "?")),
        ("部分不明Issue数", result.get("partial_source_issues", "?")),
        ("KAEP候補件数", len(rows)),
        ("診断件数", len(errors)),
    ]
    stats = "".join(f'<div class="stat"><strong>{_esc(v)}</strong><span>{_esc(k)}</span></div>'
                    for k, v in summary)
    selects = [
        ("repository", "リポジトリ"), ("role", "Issue区分"),
        ("state", "Issue状態"), ("recipient", "宛先"),
        ("reply", "返信状況"), ("validation", "原典検証"),
    ]
    controls = ''.join(
        f'<label class="control" for="{k}">{_esc(label)}'
        f'<select id="{k}"><option value="">すべて</option></select></label>'
        for k, label in selects
    )
    control_ui = (
        '<label class="control" for="q">一覧を検索'
        '<input id="q" type="search" placeholder="Issue番号・タイトル・宛先など"></label>'
        + controls
        + '<label class="control" for="sort">並べ替え'
        '<select id="sort"><option value="issue-desc">Issue番号 降順</option>'
        '<option value="issue-asc">Issue番号 昇順</option>'
        '<option value="recipient">宛先</option>'
        '<option value="reply">返信状況</option></select></label>'
    )
    csp = (
        "default-src 'none'; base-uri 'none'; object-src 'none'; "
        "connect-src 'none'; img-src 'none'; form-action 'none'; "
        f"script-src 'sha256-{_hash(JS)}'; style-src 'sha256-{_hash(CSS)}'"
    )
    document = (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{_esc(csp)}">'
        '<title>KAEP依頼一覧｜AI向け候補索引</title>'
        f'<style>{CSS}</style></head><body><main data-source-status="{_esc(result.get("status", "BLOCKED"))}">'
        '<h1>KAEP依頼一覧</h1><p>AIが依頼の原典Issueを探すための候補索引です。表示情報だけでは作業の開始・返信はできません。</p>'
        f'<p class="meta">取得日時（UTC）: {_esc(result.get("observed_at", "unknown"))} '
        f'| 対象リポジトリ: {_esc(", ".join(result.get("repositories", [])))} '
        f'| 取得状態: {_esc(label)}</p>'
        f'<div class="notice" role="status"><strong>{_esc(label)}</strong> — {_esc(meta)}</div>'
        f'<section aria-label="取得件数" class="stats">{stats}</section>'
        f'<section class="controls" aria-label="一覧の絞り込み">{control_ui}</section>'
        f'<p class="count" id="shown" aria-live="polite">{len(rows)} / {len(rows)} rows in bounded search</p>'
        '<div class="tableframe"><table id="entries"><thead><tr>'
        '<th>リポジトリ / Issue</th><th>タイトル</th><th>状態</th>'
        '<th>区分 / 種類</th><th>宛先 / 依頼種別</th><th>返信状況</th>'
        '<th>原典検証</th><th>原典コメント</th>'
        '</tr></thead><tbody>' + "".join(cells) +
        '</tbody></table></div>'
        f'<details {"open" if errors else ""}><summary>取得・検証時の注意（{len(errors)}件）</summary>'
        f'<ol class="errors">{"".join(diagnostic)}</ol></details>'
        '<p class="footer">公開時点の読取専用一覧。GitHub Projectとは連動しません。'
        '自動更新・保存・認証情報の埋め込みはありません。'
        '更新時は読取CLIかオーナー限定Pages更新で再生成してください。</p>'
        '<noscript><p class="footer">絞り込みにはJavaScriptが必要です。一覧と'
        '診断情報はJavaScriptなしでも閲覧できます。</p></noscript>'
        f'</main><script>{JS}</script></body></html>'
    )
    # Guarantees Windows redirection under CP932 can produce a faithful HTML
    # file with Unicode text represented as numeric character references.
    return document.encode("ascii", errors="xmlcharrefreplace").decode("ascii")
