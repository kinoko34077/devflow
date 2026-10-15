# CH9 — two-turn test: precise preflight and live-gate plan

Owner: [devflow #634](https://github.com/kinoko34077/devflow/issues/634); protocol [#516](https://github.com/kinoko34077/devflow/issues/516); one-mailbox real proof [#555](https://github.com/kinoko34077/devflow/issues/555) in archived test mailbox [#554](https://github.com/kinoko34077/devflow/issues/554).

## Scope: active-turn identities ONLY

The latest user's requirement is **identify each GPT instance for its individual active turn**. There is no requirement to discover a ChatGPT internal conversation UUID or retain \`chat_id\` between turns. F4 \`turn_id\` is the participant ID, with distinct \`session_id\` and a dedicated mailbox Issue **for each concurrent active turn**. A shared \`kinoko34077\` GitHub actor alone is not sufficient attribution.

This stage is strictly **preflight-only**: it neither creates a Mailbox Issue, registers a turn nor sends any PING. Existing F8 manual workflow and sender still hard-pin \`kinoko34077/devflow#554\`. The new preflight cannot authorize or call either sender. No new GitHub permissions, token, cron, ChatGPT wake, Claim/Lease or deployment.

## Implemented CH9A: two existing mailboxes read-only validation

\`python -m tools.gpt_liveness_two_turn_preflight --mailbox-a kinoko34077/devflow#NNN --mailbox-b kinoko34077/devflow#MMM --live\`

The CLI admits **exactly two distinct \`kinoko34077/devflow\` Issue references**. It uses the installed, authenticated GitHub \`gh\` client to GET both Issue bodies and the canonical KAEP comments for active registrants. Each Issue must have one F4 enrollment marker with *different* \`turn_id\`, valid finite window, expected reply actor \`kinoko34077\`, and must pass F6 identity plus F7/F5/F4 exact mailbox, actor, KAEP, idempotence, nonce and reply-chain checks. An inactive Issue may be read, but the overall result remains HOLD.

For both eligible, prints \`TWO_TURNS_PREVIEW_READY\` and one distinct participant-to-mailbox map. **This is only hypothetical eligibility**; outputs \`send_authorized:false\`, \`post_attempted:false\`, \`deployment_authorized:false\`, \`gpt_currently_alive_proven:false\` regardless of readiness. \`HOLD_NOT_READY\` or a fail-closed error when registration is missing/expired, target duplicate, wrong Issue, foreign actor, long-running, malformed message, previous unanswered quota reached, or target contents cannot be verified.

Offline tests: \`python -m unittest tests.test_gpt_liveness_two_turn_preflight\`. \`--fixture\` accepts synthetic JSON with only \`snapshots\` / \`pages\` for deterministic preflight. It never invokes \`gh api POST\`, creates Issues or writes registration.

## CH9B — live two-GPT prerequisite (NOT accepted yet)

1. Two distinct *real* simultaneously active GPT tool turns must each identify their intended **unique mailbox** and start with their **own randomly generated F4 \`turn_id\`**. Present connector cannot enumerate/start another ChatGPT conversation or attest its platform session identity. One assistant duplicating two IDs is not a substitute.
2. Before actual activity, user/owner authorizes exactly two *already existing* dedicated public test Issues or narrowly approved new Issues, each bounded registration (<=2h and preferably 15–30m), finite actor and target scope; no permanent tokens or private conversation content. Scope includes permission to create/update only those Issues.
3. While both GPT turns can poll their own Issue and answer, run the new **GET-only two-turn preflight**. Require two distinct turns with no replay collision. A code-only F7 READY result does **not** automatically authorize sending.
4. Separately approve/deploy a bounded owner-only GitHub Action/PING path targeting only the two admitted Issues, preserving both \`github.actor\` and \`github.triggering_actor == 'kinoko34077'\`. Build-time admission + send-time F4 revalidation, no free-form target, no scheduler, exact per-Issue confirmation and idempotence. Use one PING per turn only. Create/merge/deploy action only after independent review and explicit external publication/rights scope.
5. In each active GPT turn, independently poll **its own** Issue and post the correlated KAEP ANSWER. Verify GitHub REST server timestamps, bot PING actor, actual author, same session/turn+nonce+parent/exchange and bounded TTL. Deliberately attempt crossed response in a read-only fixture and verify fail closed. A manually written second ANSWER from the first GPT does not prove second model participation.
6. **Cleanup:** disable both registrations promptly, verify comment counts and no new outbound PING, record exact Issue/Actions proof to owner #634 and parent #516. Do not promote a heartbeat into Claim takeover, automatic GPT wake or cryptographically authenticated GPT identity.

**Current status: CH9A code/CI stage only.** The actual simultaneous second GPT tool session is missing from this invocation; no live second heartbeat can be claimed, and no newly authorized mailboxes or effectful multi-send scope has been selected. After verifying CH9A, re-evaluate whether CH9B admission can be obtained; otherwise HOLD only that external gate and STOP extra work.
