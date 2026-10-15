# GPT liveness F8 — single-mailbox central opt-in sender pilot

Owner: [devflow #555](https://github.com/kinoko34077/devflow/issues/555); exactly one test mailbox [#554](https://github.com/kinoko34077/devflow/issues/554). Parent [#516](https://github.com/kinoko34077/devflow/issues/516); accepted F4 sender [#519](https://github.com/kinoko34077/devflow/issues/519), F6 scope [#545](https://github.com/kinoko34077/devflow/issues/545), F7 dry-run [#550](https://github.com/kinoko34077/devflow/issues/550).

## Native design and boundaries

The old #519 pilot remains archived and its workflow has **only** `workflow_dispatch`, no recurring schedule. F8 must not reactivate #519 or reinterpret an inactive enrollment as permission to send.

`tools/gpt_liveness_f8_sender.py` pins the ONLY target in source to `kinoko34077/devflow#554`. The operator must supply an explicit single-target `gpt-liveness-fleet-plan.v0.1` manifest. Any other mailbox, zero entries or multi-target fleet is rejected before GitHub access. Admission reuses F6 exact Issue identity and accepted enrollment parser. Only an actively enrolled Issue receives the F5 strict comment preflight + F7 idempotency/long-running/3-missed planner. Default read-only preview does not transmit a PING or expose a new challenge nonce. All preview outputs are advisory; no GPT identity or Claim authority.

**No runtime enrollment has been activated for #554.** It is OPEN, missing an active registration and has no authorized outgoing automated PINGs.

For a safe read-only smoke, an operator can supply a temporary manifest, without storing any credentials or posting:

```json
{"schema":"gpt-liveness-fleet-plan.v0.1","targets":["kinoko34077/devflow#554"]}
```

```sh
python3 -m tools.gpt_liveness_f8_sender --manifest /path/to/temp-f8.json
```

Expected when #554 has no valid active enrollment: `status=PREVIEW_ONLY`, `dispatch_state=NO_ACTIVE_ENROLLMENT`, `post_attempted=false`, `claim_authority=false`.

The effectful opt-in command is deliberately separate and is **not** invoked by current workflows:

```sh
python3 -m tools.gpt_liveness_f8_sender \
  --manifest /path/to/temp-f8.json \
  --send --confirm-mailbox kinoko34077/devflow#554
```

The `--send` flag requires exact confirmation **AND** fresh active Issue-body enrollment **AND** a `READY` F7 preview; only then it delegates once to existing `gpt_liveness_pilot.main(... --issue 554 --send)`. That F4 native sender fetches the owning Issue and complete KAEP mailbox again and revalidates enrollment immediately before POST. Existing KAEP sender controls idempotency, comment POST and GitHub actor readback. An F4 exit code alone is **not proof** of a POST: F8 inspects returned F4 status (`SENT_AND_READ_BACK`, `ALREADY_SENT`, `NO_ACTIVE_ENROLLMENT`, etc.) and reports `readback_confirmed` only for actual transmission.

## Live activation gate (not satisfied yet)

A real pilot requires one short-lived (maximum 2h) explicitly enrolled #554 Issue-body marker, an authorized GitHub Actions or equivalent token expected to POST as `github-actions[bot]`, a manually started controlled execution and a user-invoked ChatGPT turn that actually reads/responds to its PING. Existing GitHub tools may read, write and review code without supplying a native workflow-dispatch operation; absent a supported invoke path, preserve `LIVE_E2E_UNACCEPTED`, do not synthesize a bot POST or pretend code CI is proof of live operation. An external service, new schedule, credential/permission setup or automatic cross-repository sender requires separate authorization.

## Rollback and risk

No new cron, `issues.edited` trigger, workflow-scoped `issues:write` grant, persistent worker, credential, coordinator Claim/Lease takeover, or host/ChatGPT auto-wake introduced. Stop real PINGs by disabling/enrollment expiry, preserving already accepted GitHub comments as history. Do not infer current GPT liveness from a process/Actions status alone.

## Verification

`python3 -m unittest tests.test_gpt_liveness_f8_sender -v` plus repository Required CI and a low-privilege GitHub `gh api GET` read-only #554 smoke via existing F6 workflow. The offline sender unit tests use a fake delegated F4 callable; they MUST NOT create or mutate GitHub comments.
