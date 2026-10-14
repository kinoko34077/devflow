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

This reads #503, selects strict pointer-shaped READ_ONLY reports and verifies each against a fresh read of the original owning Issue (matching URL, original message ID and comment ID, actor, recipient and READ_ONLY scope). The output is **pointer metadata only**; the session must read the actual source with `tools.kaep_inbox_reader` and follow the owning Issue's current authority before sending any ACK/ANSWER. The supplied `--after-id` is a checkpoint supplied by the external session, not a new stored task state. Advance it only after the entire read/verification step and subsequent acceptance path; missing pages/source, malformed or wrong-actor pointers fail closed.

The reader does **not** prove that Claude has been awakened, is alive, or performed the pointed-to work. A GitHub actor proves only the host comment login, not the underlying AI model identity. In particular, the actual PR head must still be rechecked at the time of work: stored `expected_head` can become stale.

## Scheduling constraints

The existing user-managed Claude normal idle cadence is unbounded 5, 10, 20, 40, 80, 160... minutes and resets to 5 minutes on genuine work. No new background schedule is created by these tools; adding a hint does **not** advance an already-delayed next check-in. GPT-issued temporary schedule override is separately gated (at most one hour in duration and deferral), and is **not implemented here**. There is no unattended GPT wake, new provider, permission, secret or deployment.

## Acceptance / limitations

A2 code is acceptable when strict source validation, actor/pointer spoof resistance, dedupe, malformed/replay fail-closed and native CI succeed. **Live routing acceptance** additionally requires observing an existing Claude session actually discover a *new legitimate task* through the index and respond on the source Issue; no prior completed UG #336 request should be resent just to manufacture that evidence. Treat no live session as PENDING, not PASS.
