# GPT turn-scoped heartbeat routing v0.1 — CURRENT (2026-10-16)

Authority: [devflow #634](https://github.com/kinoko34077/devflow/issues/634), parent [#516](https://github.com/kinoko34077/devflow/issues/516), F8 pilot [#555](https://github.com/kinoko34077/devflow/issues/555).
The user clarified **「各ターン中で各者が識別出来ればいい」**. The accepted older [PR #637](https://github.com/kinoko34077/devflow/pull/637) added an optional *persistent per-chat* registry. That persistence is **not required** for the current user goal. Do not enable, provision or rely on it for this route.

## Minimal identities

- **participant_id = existing F4 turn_id**. On each active GPT turn, allocate \`turn_\` + 16 bytes of CSPRNG hex once, then use that ID for the full turn only. No second random token or platform ChatGPT conversation UUID.
- **session_id** is a separate bounded F4 enrollment identifier, generated via 128-bit CSPRNG for new starts. A new turn need not inherit the prior turn's ID.
- **mailbox_ref** is the current approved owning GitHub Issue: a separately scoped address for each *simultaneously active* participant. Using the same GitHub account does not mean two GPT turns share an inbox. The F4 parser intentionally allows exactly one active registration marker per Issue, so simultaneous turn mailboxes must be distinct. Reuse an old Issue only after strict close/disable and boundary review.
- **nonce/message_id/exchange_id** identify one particular PING/ANSWER chain under that turn. A correct ANSWER must come from the corresponding active turn and mailbox, with valid GitHub REST actor/timestamps. The external \`turn_id\` is an opaque routing identifier, *not* cryptographic proof of an actual ChatGPT process or model identity.
- When the turn ends, expire/disable its enrollment, and do **not** require carrying \`participant_id\` into another turn. Current checkpoint/Claim are separate systems.

## Read-only implementation now available

\`tools/gpt_liveness_turn_router.py\`: \`new_turn_id\`, \`new_session_id\`, \`format_manifest\`, \`plan\`, \`route\`, \`verify_pair\`.

1. \`plan\` accepts only an explicit F6 target allowlist and live Issue snapshots; validates F4 current finite enrollment and detects duplicate turn IDs across all admitted Issues. No read-only plan is a send permission.
2. \`route\` returns the unique current inbox/outbox Issue for a participant. \`UNOBSERVED\`, \`ISSUE_CLOSED\`, disabled, expired and ambiguous participants cannot route.
3. \`verify_pair\` demands exact mailbox/turn/session, KAEP READ_ONLY PING/reply chain, fresh nonce and REST-attributed actor/server times. It proves only \`MODEL_TOOL_RESPONSE_OBSERVED\` **at that observed timestamp**. Another chat's same-account ANSWER is not accepted merely because the actor name matches.
4. Offline multi-turn tests simulate two concurrent actors with separate target Issues, deliberately crossed nonce/session/turn/Issue, duplicate participant IDs, closed/expired/disabled targets, corrupted KAEP chains, late replies, and no write API.
5. Existing [F8 manual workflow](../..//.github/workflows/gpt-liveness-f8-manual.yml) is **still pinned to #554**. It is NOT a multi-target sender and must not be generalized by code-only tests or speculative authority.

## Remaining actual-runtime lifecycle / gate

**Code-only staged in #634:** the pure router and synthetic multi-turn tests. No new Issue, enrollment or PING has been created by this work.

**Real multi-GPT enablement is NOT yet demonstrated**. For a live two-chat pilot, the operator must have two simultaneously open, independently addressed GPT turns that can each explicitly register their own unique \`turn_id\` and designated mailbox. The controlling job must verify two distinct active registrations and the real source/chat context; then an approved, bounded multi-target sender must be implemented, reviewed and explicitly authorized. Only then run real PING→ANSWER on both turns, swap payloads as a negative test, disable both registrations and verify no further posts. Actual availability of two simultaneous ChatGPT tool sessions is a runtime capability to test, not assume.

**Do not activate without separate authorization:** new Issue provisioning, changing \`issues:write\` scope, workflow scheduling, automatic context injection, persistent host/agent wake, PING POST for other Issues, or runtime Claim changes. Since a ChatGPT tool session may end before a PING is delivered, absence of response is \`UNOBSERVED\` rather than positive proof that the model stopped.
