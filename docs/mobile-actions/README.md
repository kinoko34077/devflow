# KiNoTch. Actions Control — iPhone Safari launchpad

Owner: [devflow #562](https://github.com/kinoko34077/devflow/issues/562). Runtime PING/ANSWER acceptance remains [devflow #555](https://github.com/kinoko34077/devflow/issues/555).

## Purpose and surface

This is a static, **read-only** mobile-first HTML/CSS/JavaScript page intended for Safari on iPhone. It is a separate web entrypoint, **not a mobile-compatible ChatGPT custom MCP app**: current [OpenAI documentation](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt) explicitly states custom MCP apps are web-only and not available on mobile. The original personal [KiNoTch. Actions Control plugin](https://chatgpt.com/plugins/plugins_6ad06b93d5f881919969b749d142ab9f) remains unchanged; neither plugin nor this webpage launches an idle ChatGPT instance.

Page files:
- `index.html`: mobile accessibility, state cards, official GitHub Actions/manual-run link
- `style.css`: iPhone safe-area/viewport, keyboard and 44px touch targets
- `control.js`: two direct public GitHub API GET attempts, then a same-origin `status.json` fallback if either fails; no browser credentials or writes
- `manifest.webmanifest`: optional iPhone Add to Home Screen standalone display, no background worker
- `status.json`: generated at Pages build by `tools/mobile_actions_snapshot.py`, with only allowlisted public fields, build timestamp, and no Issue body/session/turn or token

There is a **GitHub-hosted Pages build step**, not a new persistent server. The build uses GitHub's temporary `github.token` with `issues:read` and `actions:read` to generate a scrubbed snapshot. No token or raw Issue body is published, and the browser has no PAT, Service Worker, background polling, analytics, credential/session settings or Issue mutations. This is deliberately not a proxy for `workflow_dispatch`; official GitHub owner login and the existing workflow's exact `github.actor` validation remain on GitHub.

## What the UI shows and what it does not prove

The UI reads `GET /repos/kinoko34077/devflow/issues/554` and `GET /repos/kinoko34077/devflow/actions/workflows/gpt-liveness-f8-manual.yml/runs?per_page=5`. Each request is bounded, public, `credentials:omit` and `no-store`. It parses one accepted Issue-body marker only to report:
- `無効`, `未登録`, `期限切れ`, `開始前`, `判定不可`, or `登録マーカー有効（要再検証）`;
- Issue open/closed and comments **count**, and recent workflow run outcome;
- if direct browser access to GitHub API fails, the page displays the **saved publication-time snapshot** and its generation time, explicitly not live data. HTTP codes/timeouts/network failures are labelled. If both API and first-party snapshot fail, **未確認/取得不可** remains; never falsely assert stopped/alive.

An enrollment marker is provisional: only the server-side F8/F4 path has authority to recheck full mailbox/actual POST safety. Browser/phone clock is not independent proof. A successful workflow dispatch is not proof that a bot sent a PING; a PING is not proof ChatGPT was awake; strong model identity and Claim authority are not established.

## Intended iPhone flow (published site)

1. Open `https://kinoko34077.github.io/devflow/` in iPhone Safari. Optionally use Safari Share → Add to Home Screen.
2. Tap `状態を更新`. Live browser GET is attempted; if blocked, a labelled publication-time snapshot is used instead. Inspect #554 and #555 in GitHub before real decisions, because the saved state can be stale.
3. Use `公式の手動実行画面を開く` to go to `https://github.com/kinoko34077/devflow/actions/workflows/gpt-liveness-f8-manual.yml`.
4. Log in to GitHub as the authorized owner. GitHub itself exposes `Run workflow` for permitted users; iPhone Safari may require `デスクトップ用Webサイトを表示`. Start with `operation=preview`; a real `send` additionally needs separately authorized fresh registration and the exact `confirm_mailbox=kinoko34077/devflow#554`.
5. Return to the page and refresh; inspect full GitHub Actions logs and Issue comments before counting any real PING. Disable registration after a real trial as documented in #555.

## Hosting boundary

The site has previously been deployed by the explicitly approved `mobile-actions-pages.yml` workflow at `https://kinoko34077.github.io/devflow/`. This corrective PR changes the **existing, approved Pages artifact** to contain only the original four UI files plus one scrubbed, timestamped `status.json`. It does not create an additional server, issue credential, PING or schedule. User's reported Safari API failure is still a real-device issue until retested after this deployment. No repository secrets, token, raw Issue body, session/turn IDs or private Issues may be published.

## Verification

`python -m unittest tests.test_mobile_actions_control tests.test_mobile_actions_snapshot` or the repository-wide native Required CI. JavaScript syntax and enrollment-state checks run under Node when available. Verify actual mobile Safari rendering, browser CORS, GitHub authentication and availability of `Run workflow` separately after deployment.

Related: existing F8 workflow `.github/workflows/gpt-liveness-f8-manual.yml` remains unchanged and manual-only; Issue #554 currently has a disabled registration.
