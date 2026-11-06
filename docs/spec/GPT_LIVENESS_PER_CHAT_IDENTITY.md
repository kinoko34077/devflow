# Per-chat GPT heartbeat identity and isolated routing (code-only contract v0.1)

Authority: [devflow #634](https://github.com/kinoko34077/devflow/issues/634) under [#516](https://github.com/kinoko34077/devflow/issues/516). Existing single-target proof [#555](https://github.com/kinoko34077/devflow/issues/555) / [#554](https://github.com/kinoko34077/devflow/issues/554) **does not change**.

## Current gap and identity model

The F4/F8 liveness pilot verifies \`session_id\` / \`turn_id\` / nonce in one mailbox but cannot distinguish *independent ChatGPT conversations* when they share a single target. The GitHub actor \`kinoko34077\` is a transport login, not a ChatGPT conversation UUID nor evidence of which model produced a response.

Use three separately scoped opaque IDs:
- \`chat_id\`: create once per ChatGPT conversation by \`secrets.token_hex(16)\` (128-bit CSPRNG) as \`chat_<32 hex>\`; fixed over multiple turns and sessions, not secret nor platform-attested.
- \`session_id\`: new per bounded enrollment / run (same existing F4 schema, ID-compatible \`session_<32 hex>\`).
- \`turn_id\`: new per actual execution turn / checkpoint (same existing F4 schema, ID-compatible \`turn_<32 hex>\`).
- \`exchange_id\` / \`message_id\` / \`nonce\`: fresh per PING and exact parent/ANSWER chain as KAEP/F4 already requires.

Do NOT derive IDs from timestamps, user-visible chat titles, GitHub actor, repo, deterministic PR number, or a weak/reused random seed. Per-chat stable identity requires a durable **binding** from \`chat_id\` to one canonical owning Issue mailbox; generating a random ID on each turn would create new identities and lose continuity.

## Durable binding and one mailbox per chat

Use an independently owned, approved GitHub Issue mailbox per chat (never the old shared #554 pilot reused as a fleet). Each owning Issue body has exactly one additional marker:

\`<!-- gpt-liveness:chat-binding:v0.1 {"chat_id":"chat_<32hex>","mailbox_ref":"kinoko34077/devflow#NNN","schema":"gpt.liveness.chat-binding.v0.1"} -->\`

This is **additional metadata**, not a change to the strict existing F4 \`gpt-liveness:enrollment:v0.1\` marker or KAEP message schema. Current F4 accepts extra unrelated Issue body prose and preserves its single enrollment. One Issue → one chat binding → one active F4 enrollment (per bounded session+turn), with the prior F6 strict **explicit** target allowlist. Bound target Issue/number must be fetched live; never accept a client-supplied unverified Issue body as durable truth.

A chat ID must be globally unique among the current admitted target snapshot. Duplicate chat IDs, reusing one mailbox, a wrong/missing binding, disabled/expired enrollment, cross-chat PING, old session/turn, crossed reply parent, mismatched nonce, actor or server time **fail closed**.

## Implemented pure read-only functions

- \`tools/gpt_liveness_chat_registry.py\`: \`new_chat_id\`, \`new_session_id\`, \`new_turn_id\`, \`binding_marker\`, \`parse_binding\`, \`read_only_plan\` and \`validate_heartbeat_pair\`.
- \`read_only_plan\`: uses F6 canonical explicit allowlist and Issue snapshot validation plus F4 enrollment; never posts or confers permissions. If no active enrollment, report \`NO_ACTIVE_ENROLLMENT\`, never \`ALIVE\`. Every entry returns its own \`chat_id\`, \`mailbox_ref\` and, when active, session/turn.
- \`validate_heartbeat_pair\`: strict KAEP envelope + reply chain, F4 challenge and answer, exact per-chat Issue ID, same session/turn and nonce, verified GitHub actor and server timestamps. Returns only \`MODEL_TOOL_RESPONSE_OBSERVED\`, not current liveness or cryptographic ChatGPT identity.
- This PR uses *synthetic* multi-chat fixtures and negative tests. It has **no Issue write, automatic provisioning, dispatch, schedule, credential, Claim/Lease or sender changes**.

## Independent per-chat heartbeat lifecycle — FUTURE / NOT ACTIVE

1. On first explicit enrollment of a chat, create one unique \`chat_id\`, **persist it to an approved owning Issue**, and associate it with the authenticated user's real current chat context. If ChatGPT runtime cannot expose a durable conversation ID, bind it via an explicit per-chat enrollment step and reuse the registered reference on subsequent turns. Do not claim auto-detection of all existing chats.
2. For each active turn, separately enroll \`session_id\` + \`turn_id\` into **that chat's Issue** with finite window. The Issue body binding remains stable while session/turn change. Enrollment remains an explicit action under existing safety approval.
3. Dispatcher uses only admitted, authorized mailbox references. PING is issued to one Issue; the receiving GPT must read **its bound Issue only**, correlate nonce and answer. Same GitHub login does not allow routing one chat's ANSWER to another.
4. Independent observer records each \`chat_id\` heartbeat state and last evidence time. Chat A success must never turn Chat B green. \`UNOBSERVED\` or no response never implies ChatGPT stopped. Sending PING does **not** awaken a suspended ChatGPT conversation.
5. On finish, expiry, change of scope or conflict: disable per-chat enrollment; retain a narrowly scoped durable audit log and no runtime Claim action. Not a new agent process.
6. **Before activating two live chats**: define the authenticated per-chat context binding, owner-only Issue admission and creation policy, issue namespace and privacy constraints, cross-chat reply surface, error/replay and concurrent update/turn rollover, bounded target limit, safe dispatcher worker security, and explicit user approval. The current F8 sender and GitHub workflow are hardcoded to #554; they **must not be generalized without a separate reviewed release**.

## Verification and explicit non-goals

\`python -m unittest tests.test_gpt_liveness_chat_registry\`

No actual multiple-chat GitHub send is accepted by this PR. Nothing auto-generates a \`chat_id\` in every existing ChatGPT conversation without a known invocation/identity surface, and a user-supplied random ID cannot authenticate the underlying ChatGPT session by itself. There is no automatic GPT wake, automatic provider response, account-wide issue creation, cross-repo deployment or Claim takeover.
