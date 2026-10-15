# F8E — one-mailbox manual live trial, deployment gated

Work owner: [devflow #555](https://github.com/kinoko34077/devflow/issues/555), exact target [devflow #554](https://github.com/kinoko34077/devflow/issues/554). Canonical parent [#516](https://github.com/kinoko34077/devflow/issues/516). Native sender F8A–D accepted [PR #557](https://github.com/kinoko34077/devflow/pull/557). **Workflow deployment and verified PING delivery are separate milestones.** This manual-only workflow is already on main, but real F8 bot PING/ChatGPT ANSWER has NOT been demonstrated.

## Staged but not activated

`.github/workflows/gpt-liveness-f8-manual.yml` is a new **`workflow_dispatch`-only** entry point. No `push`, `schedule`, `issue_comment`, `issues.edited`, no webhook subscriber, no new PAT and no provider auto-wake. It is already present on main under the earlier user approval; no schedule was added. A later actual send still requires a separately valid enrollment and an explicitly authorized bounded trial.

The default invocation is `operation: preview`, which runs the existing one-mailbox CLI without `--send`. Its job has only `contents:read` and `issues:read` rights; it asserts no comments were posted. **Both preview and send require `github.actor == 'kinoko34077'` AND `github.triggering_actor == 'kinoko34077'`.** GitHub preserves the original actor's privileges on a rerun; checking both denies a rerun initiated by a different account. Other repository writers may have permission to click `Run workflow`, but these pilot jobs must SKIP for anyone except the owner. In `operation: send`, a separate job can run only if ALL of the following match:
- manual `workflow_dispatch` on `refs/heads/main`, repository `kinoko34077/devflow`, **original actor AND triggering actor** logins both `kinoko34077` (including reruns);
- `inputs.operation=send`, `inputs.confirm_mailbox=kinoko34077/devflow#554`;
- preview job succeeds on the real Issue; the send job alone has `issues:write`;
- Issue #554 is still `open` with exactly one valid short-lived explicitly enabled enrollment, valid `session_id` / `turn_id`, correct response actor and up to 3 outstanding challenges; no terminal ANSWER;
- existing `tools/gpt_liveness_f8_sender.py` validates F6/F7 and delegates to native F4 which re-reads Issue and full KAEP mailbox before sending; F4 sends via canonical `send_request` with idempotent key and actor-readback.

Input text never forms a shell command. The posted PING, if any, is an ordinary GitHub Issue comment, not an execution-coordinator Claim and cannot awaken an idle ChatGPT thread. If an earlier exchange has been answered terminally or the registration was disabled/expired, the sender emits a **no-new-PING** result, not false success.

## Controlled acceptance procedure (requires effectful approval first)

1. The single-issue manual workflow has already been merged by explicit user authorization; before any new pilot, check live main, owner-only `github.actor`/`github.triggering_actor` guards, exact-head Required CI, Formal Review and Readiness. Do not copy across repositories.
2. First run `preview` against #554 while **no active enrollment**, verify `NO_ACTIVE_ENROLLMENT`, no comment mutation. This still has no automatic timer.
3. Create one finite Issue-body registration (maximum 2h, preferably a short verification window) only after the user is ready for a live GPT tool session. Use unique opaque session/turn IDs, exact actor (`kinoko34077`) and `enabled:true`; do not quote historical registration markers verbatim in the same body.
4. Request exactly **one** `operation: send` manual invocation; provide exact `confirm_mailbox`. Inspect job log `F8_MANUAL_KAEP_PING_READBACK <comment_id>`, verify GitHub REST actor `github-actions[bot]` and the bound challenge.
5. In the active ChatGPT session, GPT must read the actual Issue comment then submit a correlated KAEP `ANSWER` via an approved tool. Verify actual server comment timestamp and exact `exchange_id`, `nonce`, session, turn and actor. **An ACK or GitHub bot activity is insufficient**.
6. Negative paths: send with disabled/expired registration, duplicate slot or terminal response and verify no new PING. If testing 3 unanswered requires multiple actual runs, do so only within explicit per-test effectful scope; do not infer it from offline test results.
7. Immediately set `enabled:false` (or allow finite expiry), read back the Issue and verify further preview/sends cannot post. Retain durable evidence in #555. If any unexpected Action or comment occurs, disable registration and STOP. Never change Claim/Lease.

## Acceptance split

- **READONLY / CODE ACCEPTED**: automated static workflow policy tests, full Required CI and same-system review; workflow dispatch file staged in PR, not installed.
- **LIVE_E2E_UNACCEPTED** until real bot PING, GPT ANSWER, timing/actor/nonce correlation, and stopped/expired no-send are independently checked.
- Strong cryptographic model identity, all-repository rollout, persistent scheduler, credentials/env additions, automatic agent wake and Claim takeover are explicitly out of scope.

## Connector limitation

The currently available GitHub connector exposes reads and Issue/code writes but **no workflow_dispatch method**. Therefore a supported authorized executor (owner GitHub Actions UI or an explicitly approved capable agent/tool) is necessary for the actual manual run. Never claim that a PR CI job or Github user-authored comment proves a bot PING.
