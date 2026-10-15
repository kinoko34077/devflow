# KiNoTch. Actions Control — iPhone Safari launchpad

Owner: [devflow #562](https://github.com/kinoko34077/devflow/issues/562). Runtime PING/ANSWER acceptance remains [devflow #555](https://github.com/kinoko34077/devflow/issues/555).

## Purpose and surface

This is a static, **read-only** mobile-first HTML/CSS/JavaScript page intended for Safari on iPhone. It is a separate web entrypoint, **not a mobile-compatible ChatGPT custom MCP app**: current [OpenAI documentation](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt) explicitly states custom MCP apps are web-only and not available on mobile. The original personal [KiNoTch. Actions Control plugin](https://chatgpt.com/plugins/plugins_6ad06b93d5f881919969b749d142ab9f) remains unchanged; neither plugin nor this webpage launches an idle ChatGPT instance.

Page files:
- `index.html`: mobile accessibility, state cards, official GitHub Actions/manual-run link
- `style.css`: iPhone safe-area/viewport, keyboard and 44px touch targets
- `control.js`: **two public GitHub API GET operations only**, no credentials or writes
- `manifest.webmanifest`: optional iPhone Add to Home Screen standalone display, no background worker

No build step, frameworks, server, token, PAT, Service Worker, background polling, analytics, credential/session settings or Issue mutations. This is deliberately not a proxy for `workflow_dispatch`; official GitHub owner login and the existing workflow's exact `github.actor` validation remain on GitHub.

## What the UI shows and what it does not prove

The UI reads `GET /repos/kinoko34077/devflow/issues/554` and `GET /repos/kinoko34077/devflow/actions/workflows/gpt-liveness-f8-manual.yml/runs?per_page=5`. Each request is bounded, public, `credentials:omit` and `no-store`. It parses one accepted Issue-body marker only to report:
- `無効`, `未登録`, `期限切れ`, `開始前`, `判定不可`, or `登録マーカー有効（要再検証）`;
- Issue open/closed and comments **count**, and recent workflow run outcome;
- if GitHub is inaccessible, **未確認/取得不可**, never falsely asserting a stopped agent.

An enrollment marker is provisional: only the server-side F8/F4 path has authority to recheck full mailbox/actual POST safety. Browser/phone clock is not independent proof. A successful workflow dispatch is not proof that a bot sent a PING; a PING is not proof ChatGPT was awake; strong model identity and Claim authority are not established.

## Intended iPhone flow, once hosted

1. Open the HTTPS page in iPhone Safari. Optionally use Safari Share → Add to Home Screen.
2. Tap `状態を更新` to retrieve live **public** state. Inspect #554 and #555 in GitHub if API is unavailable or enrollment is ambiguous.
3. Use `公式の手動実行画面を開く` to go to `https://github.com/kinoko34077/devflow/actions/workflows/gpt-liveness-f8-manual.yml`.
4. Log in to GitHub as the authorized owner. GitHub itself exposes `Run workflow` for permitted users; iPhone Safari may require `デスクトップ用Webサイトを表示`. Start with `operation=preview`; a real `send` additionally needs separately authorized fresh registration and the exact `confirm_mailbox=kinoko34077/devflow#554`.
5. Return to the page and refresh; inspect full GitHub Actions logs and Issue comments before counting any real PING. Disable registration after a real trial as documented in #555.

## Hosting boundary

**No hosted URL or actual iPhone E2E is claimed by this PR.** The branch/PR is staged code, not a GitHub Pages site. GitHub Pages publication may require adding a Pages source or workflow and must be explicitly authorized as an external publication/deployment. Do not invent a URL until public HTTPS deployment is live and validated. Pages deployment should publish only these four static files; never repository secrets or private Issues.

## Verification

`python -m unittest tests.test_mobile_actions_control` or the repository-wide native Required CI. JavaScript syntax and enrollment-state checks run under Node when available. Verify actual mobile Safari rendering, browser CORS, GitHub authentication and availability of `Run workflow` separately after deployment.

Related: existing F8 workflow `.github/workflows/gpt-liveness-f8-manual.yml` remains unchanged and manual-only; Issue #554 currently has a disabled registration.
