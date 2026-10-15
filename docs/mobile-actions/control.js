"use strict";
// Read-only on purpose: no API token, storage, POST, workflow dispatch, or timer loop.
const API = "https://api.github.com/repos/kinoko34077/devflow";
const ISSUE_URL = API + "/issues/554";
const RUNS_URL = API + "/actions/workflows/gpt-liveness-f8-manual.yml/runs?per_page=5";
const el = (id) => document.getElementById(id);
const setText = (id, text) => { el(id).textContent = String(text); };

async function readPublicJson(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(url, {
      method: "GET",
      credentials: "omit",
      redirect: "error",
      cache: "no-store",
      headers: { Accept: "application/vnd.github+json" },
      signal: controller.signal
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

function enrollmentStatus(body, now = new Date()) {
  if (typeof body !== "string") return "判定不可";
  const found = [...body.matchAll(/<!-- gpt-liveness:enrollment:v0\.1 (\{[^\n]*\}) -->/g)];
  if (found.length === 0) return "未登録";
  if (found.length !== 1) return "判定不可（複数）";
  try {
    const marker = JSON.parse(found[0][1]);
    if (marker.schema !== "gpt.liveness.v0.1" ||
        typeof marker.enabled !== "boolean" ||
        typeof marker.started_at !== "string" ||
        typeof marker.expires_at !== "string") return "判定不可";
    if (!marker.enabled) return "無効";
    const start = Date.parse(marker.started_at);
    const end = Date.parse(marker.expires_at);
    const time = now.getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return "判定不可";
    if (time >= end) return "期限切れ";
    if (time < start) return "開始前";
    return "登録マーカー有効（要再検証）";
  } catch {
    return "判定不可";
  }
}

function showIssue(issue) {
  if (!issue || issue.number !== 554 || !["open", "closed"].includes(issue.state)) {
    throw new Error("Issue identity mismatch");
  }
  setText("issue-state", issue.state === "open" ? "Open" : "Closed");
  setText("issue-comments", Number.isSafeInteger(issue.comments) ? issue.comments : "不明");
  const status = enrollmentStatus(issue.body);
  setText("enrollment", status);
  setText("enrollment-note",
    status === "無効" || status === "未登録" || status === "期限切れ"
      ? "有効な登録が確認できません。GitHub公式画面でsendを実行してもPINGは発生しない想定です。"
      : status === "登録マーカー有効（要再検証）"
        ? "表示はIssue本文と端末時刻に基づく暫定値です。実際の送信許可はサーバ側の再検証に従います。"
        : "登録状態は断定できません。GitHubのIssue本文と#555を直接確認してください。"
  );
}

function showRuns(data) {
  if (!data || !Array.isArray(data.workflow_runs)) throw new Error("Bad workflow response");
  const list = el("runs");
  list.replaceChildren();
  const runs = data.workflow_runs.slice(0, 5);
  if (runs.length === 0) {
    const li = document.createElement("li");
    li.textContent = "実行履歴がありません";
    list.append(li);
    setText("runs-state", "0件");
    return;
  }
  for (const run of runs) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.className = "runlabel";
    label.textContent = "#" + (Number.isSafeInteger(run.run_number) ? run.run_number : "—") +
      " " + (run.event === "workflow_dispatch" ? "手動" : "その他");
    const meta = document.createElement("span");
    meta.className = "runmeta";
    const conclusion = typeof run.conclusion === "string" ? run.conclusion : null;
    const state = typeof run.status === "string" ? run.status : "不明";
    const iso = typeof run.created_at === "string" ? Date.parse(run.created_at) : NaN;
    const stamp = Number.isFinite(iso)
      ? new Date(iso).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
      : "日時不明";
    meta.textContent = (conclusion || state) + " · " + stamp;
    li.append(label, meta);
    list.append(li);
  }
  setText("runs-state", "取得成功");
}

async function refresh() {
  const btn = el("refresh");
  if (btn.disabled) return;
  btn.disabled = true;
  setText("enrollment", "確認中");
  setText("issue-state", "確認中");
  setText("issue-comments", "確認中");
  setText("runs-state", "確認中");
  setText("enrollment-note", "GitHub公開APIを読み取っています。");
  el("runs").replaceChildren();
  try {
    const results = await Promise.allSettled([readPublicJson(ISSUE_URL), readPublicJson(RUNS_URL)]);
    if (results[0].status === "fulfilled") {
      try { showIssue(results[0].value); }
      catch { issueUnavailable(); }
    } else issueUnavailable();
    if (results[1].status === "fulfilled") {
      try { showRuns(results[1].value); }
      catch { runsUnavailable(); }
    } else runsUnavailable();
    setText("checked-at", "最終確認: " + new Date().toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }));
  } finally {
    btn.disabled = false;
  }
}

function issueUnavailable() {
  setText("enrollment", "未確認");
  setText("issue-state", "未確認");
  setText("issue-comments", "未確認");
  setText("enrollment-note", "GitHub APIから取得できません。未確認は停止状態を意味しません。公式Issueを参照してください。");
}

function runsUnavailable() {
  setText("runs-state", "取得不可");
  const li = document.createElement("li");
  li.textContent = "実行履歴を確認できません。GitHub公式ページを参照してください。";
  el("runs").replaceChildren(li);
}

document.addEventListener("DOMContentLoaded", () => {
  el("refresh").addEventListener("click", refresh);
  refresh();
});
