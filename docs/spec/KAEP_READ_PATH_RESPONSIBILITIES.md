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
| B6 updated-window pagination/marker hints | `kaep_live_union_cli._collect_recent_source_hints` | Bounded comments only; overlap/truncation signal uncertainty, not source completeness |
| B6 source provenance precedence | `kaep_live_union_cli._source_origin` | One label selector for both verified rows and untrusted candidates; never grants work authority |
| B6 verified recipient root projection and two-baseline change observation | `kaep_live_union_cli._project_verified_union_rows` | Preserve distinct snapshot optional-field and previous-report strict comparisons; no source I/O or work authority |
| B6 candidate visibility and source-error ledger | `kaep_live_union_cli._build_source_candidate_ledger` | Every bounded source locator remains visible even with no recipient root; per-source/global uncertainty is descriptive and never work authority |
| B6 union of indexed/recent/previous sources | `kaep_live_union_cli.read_union` | Strict original-source verification, cap and cross-snapshot change reporting remain the orchestration owner |
| Discovery verified source proof and scan-local memoization | `kaep_discovery_reader._verified_source_pointer`, canonical `kaep_route_notice._verify_source_request_from_snapshot` | Full owning-Issue validation precedes caching; each pointer including cache hits must match the exact source comment ID; failure cannot advance durable cursor |
| Discovery read-only hint projection | `kaep_discovery_reader._verified_pointer_hint` | Emits only source-verified pointer metadata; never source message text, recipient pickup or execution authority |
| Discovery index-notice idempotence and replay identity | `kaep_discovery_reader._record_index_notice_identity` | Reject conflicting same/cross-batch message IDs and idempotency keys; same-batch identical notice skipped; cross-batch identical pointer rechecked for duplicate source accounting |
| Discovery batching, notice actor and safe cursor | `kaep_discovery_reader._discover_batch`, `discover_index_shadow` | Index actor checks, bounded scan, untrusted notice rejection and source fail-closed cursor remain in the ordered scanner |
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
