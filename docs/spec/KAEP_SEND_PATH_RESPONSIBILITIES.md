# KAEP two-phase REQUEST/REPLY send path: responsibility ownership

Implementation ownership map for devflow #847. The normative KAEP v0.2
protocol and the owner Issues #503, #524, and #771 remain authoritative.
This map does not establish runtime Claim, human approval or agent identity.

| Change reason | Implementation owner | Contract |
| --- | --- | --- |
| REQUEST envelope and stable identities | `kaep_request_sender.make_request` | Canonical mailbox checks full reserved identities and detects collisions |
| Single REQUEST opt-in source writer | `kaep_request_sender.send_request` | Read before post; full readback; no provider activation |
| REPLY envelope, parent, actor and route | `kaep_reply_sender.make_reply` | READ_ONLY parent and recipient checks; no claimed model identity |
| Shared ordinary Issue POST/readback | `kaep_reply_sender.post_comment`, `post_and_verify` | Ambiguous POST cannot be blindly repeated |
| Two-phase local target/policy validation | `kaep_send_with_discovery._validate_two_phase_options` | No I/O; validate target, chosen approved index, actor, intent, fixtures and opt-in |
| Public source and selected-index mailbox preflight | `kaep_send_with_discovery.publish_source_and_route`, `_discovery_read_preflight` | Both checks precede first original POST |
| Two-phase source then pointer and partial receipts | `kaep_send_with_discovery.publish_source_and_route` | Source readback precedes route POST; uncertain partial status never proves delivery |
| Pointer composition and source proof | `kaep_route_notice.route_request` | Only original verified source IDs, no raw request text published to index |

Flow: local option validation -> public visibility check on live send ->
strict selected index preflight -> source REQUEST preflight / opt-in post /
readback -> discovery pointer preflight / opt-in post / readback ->
phase-specific receipt. GitHub Issue comments across two Issues are not
atomic; retain stable request_key and read-before-retry.

Tests: `tests/test_kaep_send_with_discovery.py`,
`tests/test_kaep_send_option_responsibilities.py`,
`tests/test_kaep_request_sender.py` and `tests/test_kaep_reply_sender.py`.
