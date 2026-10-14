# KAEP M1.5 A2 — pointer-only discovery on existing mailbox

**Authority:** [devflow #503](https://github.com/kinoko34077/devflow/issues/503) owns KAEP v0.2 semantics; [M1.5 work order #524](https://github.com/kinoko34077/devflow/issues/524) owns this limited discovery extension. **Status:** opt-in tooling / source+index validation; actual unattended Claude pickup of new notices NOT established by merely merging code. This is not an agent wake or task assignment system.

## Why this exists

In the [real UniverseGenome #336 peer consultation](https://github.com/kinoko34077/UniverseGenome/issues/336#issuecomment-6161734905), the authentic KAEP REQUEST/ACK/ANSWER lived on the actual owning Issue, but a separate human-authored notice to #503 informed an existing Claude check-in where to look. KAEP cannot assume that an existing Claude session monitors every owning Issue. A2 automates the **pointer creation and validation**, not the user's already-managed check-in or model activation.

## Authority and format

One root READ_ONLY `REQUEST` (intent ANALYZE or REPORT, recipient claude-code) continues to live **only** on its actual owning Issue. After exact GitHub readback, a separate opt-in call may post one discovery pointer into the already-known #503 mailbox using the **unchanged KAEP v0.2** REQUEST/REPORT envelope, addressed to claude-code. Its `payload.text` contains a small canonical JSON object with exactly:

- `type: "kaep.discovery-pointer.v1"`
- `owning_issue`: the original GitHub Issue URL
- `message_id`: the original KAEP root ID
- `comment_id`: the actual root Issue comment ID

No source payload, workflow instructions, secrets, task status, Claim, review result or remote execution approval is copied. The hint has stable idempotency `kaep.discovery.<root-message-id>`; identical retries are deduplicated using the existing KAEP request sender, changed content with the same key fails closed. The #503 routing notice is *not* authority to open a new task or mark any task complete.

## Native sender (opt-in)

Use only after a legitimate **new** READ_ONLY request has already been created and read back on its own Issue. Example (the message ID must be taken from that real request):

```sh
python -m tools.kaep_route_notice \
  --repository kinoko34077/UniverseGenome --issue 336 \
  --message-id "$SOURCE_REQUEST_MESSAGE_ID" \
  --expect-source-actor kinoko34077 \
  --expect-notice-actor kinoko34077
```

The default is **preview/no post**. Append `--send` only when explicitly applying the ordinary authorized GitHub-comment transport to that existing root. **Before any public #503 pointer publication**, the sender fetches native GitHub repository metadata via read-only `gh api repos/<owner/repo>` and requires an exact repository name plus `private: false`; private or unverifiable sources fail closed, avoiding disclosure of private Issue locators on public #503. This does not prove individual Issue contents are safe to publicize; caller must ensure no secrets or sensitive metadata are exposed. The publisher fetches the full owning Issue mailbox, checks exact root ID, author, recipient, READ_ONLY scope and allowed intent, and refuses root loops or unsupported messages. It subsequently uses existing `kaep_request_sender` for #503. If the original write is ambiguous, read back before attempting a retry; the stable key prevents known duplicate notices.

## Native discovery reader (read-only)

An already-running, user-managed Claude Code check-in can invoke:

```sh
python -m tools.kaep_discovery_reader \
  --after-id "$LAST_VALIDATED_INDEX_COMMENT_ID" \
  --expect-notice-actor kinoko34077 \
  --expect-source-actor kinoko34077
```

This reads #503, selects strictly typed pointer-shaped READ_ONLY reports and verifies each against a fresh read of the original owning Issue (matching URL, original message ID and comment ID, actor, recipient and READ_ONLY scope). The output is **pointer metadata only**; the session must read the actual source with `tools.kaep_inbox_reader` and follow the owning Issue's current authority before sending any ACK/ANSWER.

**Resilient index scan (A3 corrective review):** a single index scan examines at most 20 Issue comments after `--after-id` in ascending order. The CLI returns `hints`, `rejected` (comment ID plus a fixed reason code), `truncated` and `next_after_id`. A malicious actor, malformed wrapper or invalid typed pointer is quarantined **per index comment**; it is never accepted as a task or allowed to hide a later valid pointer. A normal status report mentioning the pointer version is ignored. When `truncated=true` and there are no blocked sources, continue from `next_after_id`. When any source is blocked, continue the **current check-in's scan** from `next_scan_after_id` without durably committing beyond the first blocked pointer. The external session must **persist only the safe `next_after_id` cursor**, and only after all verified hints and rejected entries have been handled. It is not an automatic ack or execution claim.

**Source-blocked partial result (A3 follow-up):** a bad or unavailable *owning-Issue source* is never accepted as verified. Rather than discarding results for independent healthy sources, the batch returns `status: PARTIAL_BLOCKED`, `blocked: [{index_comment_id, reason_code}]`, any separately verified `hints`, and two different cursors: `next_after_id` is the **safe durable commit cursor**, pinned to the latest index comment strictly before the earliest source-blocked pointer; `next_scan_after_id` is the **transient scan continuation**, which may advance to process other candidate pointers in this same active check-in. Process any returned healthy hints idempotently; do not persist `next_scan_after_id` as the durable cursor, silently skip an unresolved blocked pointer, or claim that its source was delivered. Fix or explicitly resolve the blocked source before the durable cursor can advance. The old `discover()` list-only interface still raises `DISCOVERY_SOURCE_BLOCKED` on any partial blocked batch, so legacy callers cannot unknowingly drop blocked/cursor metadata. All GitHub **index** pagination/order failure remains global/fatal; corrupt or unavailable source does not grant any verified hint from that source. No shared KAEP codec permissiveness was changed.

**Replay behavior:** identical index message/key bytes in one batch produce a single hint; changed payload under the same identity is rejected as `CONFLICTING_INDEX_REPLAY`. Across *different batches* and historical cursor resets, recipients MUST treat `(owning_issue, source_message_id)` as an idempotent identity because there is no new global discovery ledger. Do not interpret repeated hints as separate tasks.

Successful hint records include the *source request's stored* `expected_head` and `observed_reply_kinds` from stored correlated same-GitHub-actor messages; these fields are observations only, **not** proof of current PR head, independent Claude model identity, work acceptance, CI, or formal Review.

The reader does **not** prove that Claude has been awakened, is alive, or performed the pointed-to work. A GitHub actor proves only the host comment login, not the underlying AI model identity. In particular, the actual PR head must still be rechecked at the time of work: stored `expected_head` can become stale.

## Scheduling constraints

The existing user-managed Claude normal idle cadence is unbounded 5, 10, 20, 40, 80, 160... minutes and resets to 5 minutes on genuine work. No new background schedule is created by these tools; adding a hint does **not** advance an already-delayed next check-in. GPT-issued temporary schedule override is separately gated (at most one hour in duration and deferral), and is **not implemented here**. There is no unattended GPT wake, new provider, permission, secret or deployment.

## Acceptance / limitations

A2 code is acceptable when strict source validation, actor/pointer spoof resistance, dedupe, malformed/replay fail-closed and native CI succeed. **Live routing acceptance** additionally requires observing an existing Claude session actually discover a *new legitimate task* through the index and respond on the source Issue; no prior completed UG #336 request should be resent just to manufacture that evidence. Treat no live session as PENDING, not PASS.
