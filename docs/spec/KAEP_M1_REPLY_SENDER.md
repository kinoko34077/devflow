# KAEP M1 — guarded reply composer and explicit GitHub Issue sender

**Owner:** [devflow #503](https://github.com/kinoko34077/devflow/issues/503). **Status: preparation / Claude E2E NOT VERIFIED**. This is an opt-in ordinary Issue-comment sender, **not a Claude agent, auto-responder, relay server, claim controller or identity attestation**.

## Why this exists

User can invoke Claude Code manually or via a user-managed launcher. GPT participates while a user-initiated ChatGPT conversation is active. KAEP Issue comments remain the shared, durable transport, even if future optional Channels/CPL/Codex wake becomes available. This file provides the reusable Claude-side reply step without requiring Claude to implement the GitHub POST, collision, timeout or readback logic.

## Bootstrapping Claude once quota is available

1. Read devflow AGENTS.md, #503, and the accepted spec `docs/spec/KAEP_V0_2.md`, plus the active owning Issue's current authority.
2. Confirm a supported existing `gh` CLI GitHub session and authorized ordinary Issue-comment writing access. **Do not generate, reveal, rotate or change credentials/permissions.** Read actual provider session provenance independently; a shared GitHub login proves transport actor only, never the Claude process/model.
3. Use the accepted reader and obtain the existing read-only PING, **without creating a new one**:

```sh
python -m tools.kaep_inbox_reader --repository kinoko34077/devflow --issue 503 --recipient claude-code --after-id 0 --include-text
```

4. Verify original [PING comment #6146522783](https://github.com/kinoko34077/devflow/issues/503#issuecomment-6146522783), ID `msg_claudem1ping20261013`, expected GitHub author `kinoko34077` (independent authorization check still required), `scope.effect=READ_ONLY`. Decide whether to ACK and answer; do not invent a response on Claude's behalf.

## Dry run (does NOT post anything)

```sh
python -m tools.kaep_reply_sender --repository kinoko34077/devflow --issue 503 --parent-message-id msg_claudem1ping20261013 --kind ACK --expect-actor kinoko34077
```

For `ANSWER` or `BLOCKED`, prepare a **non-secret**, bounded UTF-8 text file, for example `reply.txt`, that explicitly states what actually occurred:

```sh
python -m tools.kaep_reply_sender --repository kinoko34077/devflow --issue 503 --parent-message-id msg_claudem1ping20261013 --kind ANSWER --expect-actor kinoko34077 --text-file reply.txt
```

The dry-run result gives deterministic message identity and `PREPARED`; it is **not** a posted response or evidence of Claude action.

## Explicitly send after verifying authorization

Append `--send` to the same command for `ACK`, then `ANSWER` (or `BLOCKED`) **only from a genuinely running and authorized Claude environment**. The implementation makes a single GitHub REST Issue-comment POST using existing `gh` auth, then GETs the entire mailbox again and requires an exact stored ID/content readback. No new permissions, token acquisition, GitHub Actions invocation or task Claim is introduced.

The tool checks complete paginated history and strictly correlates an existing parent message, exchange/task, expected GitHub author and READ_ONLY intent. It deterministically keys the reply by parent+kind and refuses conflicting alternate content. If it finds the identical durable comment, it returns `ALREADY_SENT` with the original comment ID and does not repost. If GitHub POST is ambiguous, timeout occurs or readback cannot confirm, output is a fixed `BLOCKED` reason: **inspect GitHub and read again before retrying**. Avoid two senders concurrently on the same parent: GitHub create-comment has no atomic compare-and-swap, so this is at-least-once, not physically exactly-once.

## Integration and safety

- `--send` is an explicit opt-in, never the default. `--offline-pages` may only dry-run, cannot send. No background tasks/schedules are created.
- `ACK` confirms receipt only. `ANSWER`/ `BLOCKED` reports the real sender's observation; no message may assert a fabricated Claude run.
- M1 deliberately handles responses to READ_ONLY `REQUEST` or `QUESTION` with `PING/ANALYZE/TEST/REPORT` intent only. `WRITE_INTENT`, IMPLEMENT, REVISE, privileged provider launch/credentials, repository code mutation and PR Formal Review are **not** authorized by these messages. Extend them later only through an explicit task/Claim/Review-bound adapter.
- Sender does not echo `gh` stderr nor output untrusted payload text; `--text-file` avoids placing response text in process argv. No separate queue, execution authority or model identity is manufactured.
- Completion of tests or sender code is NOT a completed Claude M1 ACK; acceptance requires Claude itself to use its own supported environment and present actual Issue-comment URLs, which GPT independently validates.

## Next verified frontier

Original PING remains pending until real Claude arrives. On successful actual ACK/ANSWER, the active GPT conversation examines #503 and validates matching `exchange_id`, `in_reply_to`, message IDs, full history and external worker/session provenance. Only then should M1 connectivity be marked accepted; #87/#135 provider E2E remains separate.
