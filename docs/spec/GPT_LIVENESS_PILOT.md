# GPT Liveness / KAEP opt-in pilot v0.1

**Owning implementation Issue:** [devflow #519](https://github.com/kinoko34077/devflow/issues/519). **Cross-repository contract:** [#516](https://github.com/kinoko34077/devflow/issues/516); **KAEP transport:** [#503](https://github.com/kinoko34077/devflow/issues/503).

## What exists / what does not

- The Python pilot uses existing KAEP v0.2 `send_request`, `fetch_gh_pages`, `read_mailbox`, `verify_reply_chain` and GitHub Issue comment readback. It does not define an independent messaging transport or Claim authority.
- Scheduled GitHub Actions tries every five minutes, but without an exact active opt-in enrollment in owning Issue #519 it exits `NO_ACTIVE_ENROLLMENT` without any POST. A queued/delayed Actions run is not a precise timer or model liveness.
- Only a GPT-initiated/authorized tool invocation consuming a PING and authoring an `ANSWER` can support the weaker label *model-mediated answer observed*. The comment actor proves GitHub transport identity, not which model authored the text. `ACK` and sidecar auto-PONG prove neither.
- This pilot does not autonomously start a ChatGPT turn, execute arbitrary text from comments, touch credentials, change Claims or shorten Manual 1-hour stale policy. The prototype only runs against #519; fleet rollout is out of scope.

## Opt-in enrollment: manual, time-bounded

On Issue #519 only, an authorized owner may add exactly one machine block **to the Issue body**, substituting an actual session/turn identity and UTC timestamps. Do not enroll users' other repository tasks without separate scoping/authorization.

```text
<!-- gpt-liveness:enrollment:v0.1 {"schema":"gpt.liveness.v0.1","session_id":"session_example123","turn_id":"turn_example123","started_at":"2026-10-14T04:30:00Z","expires_at":"2026-10-14T05:00:00Z","expected_actor":"kinoko34077","enabled":true} -->
```

The lifetime is at most 2 hours. Before a long blocking operation the worker may edit the same enrollment to include `"long_running_until":"<UTC ISO deadline>"` (must not exceed `expires_at`); the scheduled job then records `LONG_RUNNING` without issuing more PINGs until the deadline. Remove/set null on return. This is a declaration only, not runtime Lease renewal. Deleting the block, setting `enabled:false`, or allowing it to expire disables further PINGs. The action's `GH_TOKEN` uses the GitHub-provided token; no new PAT required. Because the enrollment is made in the Issue body, comments cannot enroll arbitrary sessions.

## Processing / proof

1. The scheduled runner reads live Issue #519; fail closed for a missing, malformed, expired, disabled or wrong-identity enrollment.
2. It reads the complete KAEP mailbox. A unique 5-minute bucket key suppresses ordinary duplicate runs. Up to 3 unacknowledged challenges are allowed, after which it reports `SUSPECT_NO_REPLY` without more POST or runtime change.
3. A new `REQUEST/PING` addressed to `chatgpt` is posted using the **existing KAEP sender**; the payload contains bounded JSON `schema, session_id, turn_id, nonce, issued_at, expires_at, purpose`. A random 128-bit nonce is generated only for a new message. The server GitHub comment time is trusted for reply timing only after verified readback.
4. The GPT worker in a user-started live turn reads the mailbox using the existing connected GitHub tools or `python -m tools.kaep_inbox_reader --repository kinoko34077/devflow --issue 519 --recipient chatgpt --include-text` in a supported authorized CLI environment.
5. If the GPT has actually read/processed that PING, it may compose a matching `ANSWER` to the parent `message_id` using the existing KAEP reply path (`parent-recipient=chatgpt, reply-recipient=coordinator`), including a JSON payload:
   `{"schema":"gpt.liveness.v0.1","session_id":"...","turn_id":"...","nonce":"...","mode":"ACTIVE","checkpoint":"...","expected_until":null}`
6. Before waiting on a long operation, the GPT may return `mode=LONG_RUNNING` with a finite UTC `expected_until`. This is a self-reported reason to defer suspicion, **not** renewal of execution-coordinator's Lease. Latest-authority checks still apply.
7. The pilot checks KAEP correlation, actor, exact session/turn/nonce and reply comment timestamp. A transport ACK does not count. `GPT_ANSWERED` is an *observed model-mediated reply claim*, **not** a cryptographic model identity attestation.
8. Expiry, missing monitoring, or failure yields `UNOBSERVED/SUSPECT` evidence, never an automatic Claim mutation or takeover. The Manual 1-hour rule remains in force.

## GPT tool-side mailbox commands (explicit invocation only)

The worker can open/read the inbox at the start of an active ChatGPT turn and again at meaningful tool checkpoints using an authorized environment with the existing `gh` session:

```sh
python3 -m tools.gpt_liveness_mailbox --repository kinoko34077/devflow --issue 519
```

This is a **read** operation; it does not keep ChatGPT awake or send any automatic PONG. Once the GPT worker has personally processed a listed PING, it can explicitly submit a correlated answer:

```sh
python3 -m tools.gpt_liveness_mailbox --repository kinoko34077/devflow --issue 519 --respond --checkpoint F1-checked --mode ACTIVE --send
```

For blocking operations, declare `long_running_until` in the enrollment before starting; for an existing PING, `--mode LONG_RUNNING --expected-until <UTC-ISO>` provides the same bounded notification. To stop at the end of the current turn, use an explicit `FINISHED` / `IDLE` / `NEED_USER` answer when a valid PING exists, or disable/expire the enrollment. The receiver/answer tool cannot prove model identity from GitHub credentials and cannot run without an active GPT-invoked tool operation.

## Verification

`python3 -m unittest tests.test_gpt_liveness_pilot -v`

Regression covers: absence/expiry opt-in, registration strictness, KAEP envelope interoperability, 5-min bucket idempotency, three unanswered bound, delivery ACK exclusion, nonce/turn/expiry matching, long-running deadline, GitHub actor mismatch, offline/no-POST behavior.

**Live E2E limitation:** PR CI runs offline tests. A real five-minute cron cannot fire from an unmerged PR; a real interactive ChatGPT reply requires a live GPT tool call and explicit opt-in. Do not equate offline fixture passage or an Actions tick to observed GPT liveness. Production adoption, runner credentials and cross-repo rollout require separate evidence and appropriate approval.
