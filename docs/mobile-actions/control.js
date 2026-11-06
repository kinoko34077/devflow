"use strict";
// This interface NEVER handles credentials or writes. Cross-origin GET is
// optional; a same-origin, timestamped build snapshot is the fallback.
const API = "https://api.github.com/repos/kinoko34077/devflow";
const ISSUE_URL = API + "/issues/554";
const RUNS_URL = API + "/actions/workflows/gpt-liveness-f8-manual.yml/runs?per_page=5";
const SNAPSHOT_URL = "./status.json";
const SNAPSHOT_SCHEMA = "devflow.mobile-actions-snapshot.v1";
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

function errorLabel(error) {
  if (error && error.name === "AbortError") return "10秒でタイムアウト";
  if (error && typeof error.message === "string" && /^HTTP [0-9]{3}$/.test(error.message)) {
    return error.message;
  }
  return "通信エラー（ネットワーク・CORS等）";
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

function showIssue(issue, enrollmentOverride) {
  if (!issue || issue.number !== 554 || !["open", "closed"].includes(issue.state)) {
    throw new Error("Issue identity mismatch");
  }
  setText("issue-state", issue.state === "open" ? "Open" : "Closed");
  setText("issue-comments", Number.isSafeInteger(issue.comments) ? issue.comments : "不明");
  const status = typeof enrollmentOverride === "string" ? enrollmentOverride : enrollmentStatus(issue.body);
  setText("enrollment", status);
  setText("enrollment-note",
    status === "無効" || status === "未登録" || status === "期限切れ"
      ? "有効な登録が確認できません。GitHub公式画面でsendを実行してもPINGは発生しない想定です。"
      : status === "登録マーカー有効（要再検証）"
        ? "登録マーカーは有効に見えます。実際の送信許可はサーバ側の再検証に従います。"
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

function isValidSnapshot(data) {
  if (!data || data.schema !== SNAPSHOT_SCHEMA || typeof data.generated_at !== "string") return false;
  const time = Date.parse(data.generated_at);
  return Number.isFinite(time) && time <= Date.now() + 300000;
}

async function readSnapshot() {
  // Same-origin fetch is allowed by CSP and does not depend on api.github.com.
  const data = await readPublicJson(SNAPSHOT_URL);
  if (!isValidSnapshot(data)) throw new Error("Invalid snapshot");
  return data;
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
    const failedIssue = results[0].status !== "fulfilled";
    const failedRuns = results[1].status !== "fulfilled";
    let snapshot = null;
    if (failedIssue || failedRuns) {
      try { snapshot = await readSnapshot(); }
      catch { snapshot = null; }
    }
    const snapshotTime = snapshot
      ? new Date(Date.parse(snapshot.generated_at)).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })
      : null;
    let issueIsLive = false, runsAreLive = false;
    if (!failedIssue) {
      try { showIssue(results[0].value); issueIsLive = true; }
      catch { issueUnavailable("GitHub APIの応答形式を確認できません"); }
    } else if (snapshot && snapshot.issue && typeof snapshot.enrollment_status === "string") {
      try {
        showIssue(snapshot.issue, snapshot.enrollment_status);
        setText("enrollment-note", "公開時点 " + snapshotTime + " の保存情報です。現在の状態と異なる可能性があります。GitHub API: " + errorLabel(results[0].reason));
      } catch { issueUnavailable(errorLabel(results[0].reason)); }
    } else issueUnavailable(errorLabel(results[0].reason));
    if (!failedRuns) {
      try { showRuns(results[1].value); runsAreLive = true; }
      catch { runsUnavailable("GitHub APIの応答形式を確認できません"); }
    } else if (snapshot && snapshot.runs) {
      try {
        showRuns(snapshot.runs);
        setText("runs-state", "保存時点 " + snapshotTime);
      } catch { runsUnavailable(errorLabel(results[1].reason)); }
    } else runsUnavailable(errorLabel(results[1].reason));
    setText("checked-at",
      "表示: " + (issueIsLive && runsAreLive ? "APIから現在取得" : snapshotTime ? "保存情報を含む（" + snapshotTime + "）" : "一部または全部が未確認")
      + " / 確認操作: " + new Date().toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }));
  } finally {
    btn.disabled = false;
  }
}

function issueUnavailable(reason) {
  setText("enrollment", "未確認");
  setText("issue-state", "未確認");
  setText("issue-comments", "未確認");
  setText("enrollment-note", "GitHub APIから取得できません（" + reason + "）。未確認は停止状態を意味しません。公式Issueを参照してください。");
}

function runsUnavailable(reason) {
  setText("runs-state", "取得不可（" + reason + "）");
  const li = document.createElement("li");
  li.textContent = "実行履歴を確認できません。GitHub公式ページを参照してください。";
  el("runs").replaceChildren(li);
}

document.addEventListener("DOMContentLoaded", () => {
  el("refresh").addEventListener("click", refresh);
  refresh();
});
