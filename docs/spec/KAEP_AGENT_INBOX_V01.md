# Agent Inbox v0.1 — bounded read-only devflow + KAEP per repository

Owner: [devflow #531](https://github.com/kinoko34077/devflow/issues/531). KAEP protocol: #503; M1.5: #524; M3 source authority: #326/#452/#477.

## Purpose
Agent Inbox is a derived read model. It is NOT a second task database, not Project UI scraping, not a Claude wake event, and never authorizes execution, assignment, provider dispatch, Claim/Lease, Review or Merge.
GitHub Issue/PR and v0.2 stored KAEP comments remain canonical. Existing `get_repository_work_view` provides the trusted M3 all-status TASK classification; the new consumer does not classify Issues itself. It only reads the comments of selected known TASK Issues, using the existing v0.2 codec.

## Native MCP call
On a running Claude/Codex MCP client, after reading `AGENTS.md` and bootstrapping the target repository:

```text
get_agent_inbox(repository="kinoko34077/devflow", recipient="claude-code",
                limit=20, offset=0, work_status="AWAITING_REVIEW")
```

Only one repository per call. `recipient` is explicit and must match v0.2 recipients; `work_status` optionally narrows the already verified TASKs. `limit` is 1–20; `offset` allows continuation. `next_offset`, `truncated`, and `task_count_filtered` describe selected TASK candidates, not final task authorization.

## Response
- `source_status`, `source_freshness`, `coverage_status`, `observed_task_status`, `known_task_count`, `unresolved_open_issue_count`, `source_error`, `manual_control` preserve exact source/incomplete/fallback diagnostics. UNAVAILABLE/STALE means known count is unknown, **not zero work**.
- `issues` are verified known TASKs only: title/ref/status and their explicitly addressed KAEP READ_ONLY root messages when safely read. Each root yields message/exchange ID, source comment URL, stored expected HEAD and correlated reply kinds. Request prose/response text are not copied into the projection. `recipient_assignment_inferred=false` even if a task is READY; only the explicit KAEP recipient distinguishes a message addressed to the consumer.
- `requests=null` and `source_state=UNAVAILABLE` for unreadable/too-large/malformed comment history. `requests=[]` only if the selected Issue's stored comments were actually fetched and parsed but no matching READ_ONLY request was observed.
- `has_unknown_work=true` on partial/unavailable/stale Projection or comment/actor errors. No consumer may conclude no work exists in this case.
- `can_authorize_execution=false`, `can_replace_manual_active_work=false`, `is_authoritative_assignment=false`, and `is_live_agent_delivery=false` remain invariant.
- GitHub comment author matching the configured expected account is transport actor checking only, not independent model/session authentication. A stored ANSWER is evidence to recheck, not formal PR Review or a completed task.

## Initial bounded limitations and subsequent B2/B3
- The first slice is **per repository** and scans **at most 20 selected machine TASKs** per call, one at a time; each scanned Issue comment history is limited to 500 entries and failures are exposed as unknown. Legacy/unclassified Issues and KAEP roots living on them are NOT included; the accepted #503 KAEP pointer-only mechanism remains a fallback for those.
- This is an API/prototype; there is no claim that a user-managed Claude check-in has been updated or can automatically call a new MCP tool without its global instructions/configuration. B3 must demonstrate native automatic invocation/actual correlated answer on a genuine new task before accepting the replacement of #503 pointers.
- The Project remains a **display** of canonical issue state; do not treat its filtered columns or labels as independent assignment or source truth.
- Existing Claude idle policy is uncapped 5→10→20→40→80→... min, resets on genuine work. The GPT-issued override (<=60min single deferral and lifetime) is separate/deferred, not implemented here.

## Further acceptance before more rollout
Claude #532–#535 independent technical consultation, real source/actor failures, negative tests, PR Required CI and read-only MCP entry verification, followed by one genuine check-in B3. No new scheduler, credentials, deployment or Claim authority.