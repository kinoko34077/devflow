# KAEP read path: responsibility ownership (bounded scope)

This map describes the current read-only path in `kinoko34077/devflow`. It
does not replace the normative [KAEP v0.2 protocol](KAEP_V0_2.md) or owners
[devflow #503](https://github.com/kinoko34077/devflow/issues/503),
[#531](https://github.com/kinoko34077/devflow/issues/531),
[#680](https://github.com/kinoko34077/devflow/issues/680).
Change rationale: [#847](https://github.com/kinoko34077/devflow/issues/847).

| Change reason | Implementation owner | Contract / forbidden shortcut |
| --- | --- | --- |
| Search data shape, error order, candidate deduplication, cap | `kaep_issue_search_view._search_candidate_locators` | Untrusted locations only; no queue/assignment authority; preserve pre-cap count and failures |
| Original Issue and full comment GET, bounded concurrency | `kaep_issue_search_view._read_candidate_original` and `build_search_list` orchestration | Validate Issue URL/type/state *before* its comments; never omit full history, skip an original, or introduce source trust caches |
| Complete mailbox/actor/reply-chain/limited quarantine | `kaep_issue_search_view._verify_candidate_mailbox`, canonical `kaep_inbox_reader.parse_pages`, `kaep_mailbox_codec` and `agent_inbox` | Only two presentation defects may be quarantined; identity/collision/parent failures remain source-blocking; do not reinterpret actor login as model identity |
| Non-authoritative recipient rows | `kaep_issue_search_view._project_candidate_roots` | Presentation only; no fetching, message decoding, authorization, or output status ownership |
| Candidate report aggregation, error status and unknown-work flags | `kaep_issue_search_view.build_search_list` | Candidate errors remain ordered; no complete-source-universe or execution-authority claim |
| B6 union across existing and recent source hints | `kaep_live_union_cli.read_union` | Uses strict original-source reader; source caps and origin labels preserved |
| Agent Inbox / reply observation for recipients | `agent_inbox._issue_messages_for_recipients` | Canonical mailbox validation stays upstream; no independent recipient/claim authority |

**Flow:** Search or bounded B6 hints → candidate validation → original Issue
and complete comments GET → canonical mailbox validation → recipient
projection → source/candidate report. Default Search uses one source-fetch
worker; B6 may overlap at most two original-source fetches, but validation
and display construction remain in candidate order.

**Non-goals:** This map does not claim that B5 covers all possible sources,
that recent-comment windows are exhaustive, that a model picked up a message,
or that either source reader can authorize execution. Writing/send and agent
runtime execution have independent owners and are not changed by this refactor.

**Verification:** `tests/test_kaep_read_responsibilities.py`,
`tests/test_kaep_issue_search_view.py`,
`tests/test_kaep_source_prefetch_parallel.py`,
`tests/test_kaep_live_union_cli.py`. Check exact-head Required CI before merge.
