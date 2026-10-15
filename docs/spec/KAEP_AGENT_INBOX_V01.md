# Agent Inbox v0.1 — bounded read-only devflow + KAEP per repository

Owner: [devflow #531](https://github.com/kinoko34077/devflow/issues/531). KAEP protocol: #503; M1.5: #524; M3 source authority: #326/#452/#477.

## Current accepted status (2026-10-15 JST)

- **B0–B2 accepted**: shared M3 all-state read-only TASK+KAEP inbox, native CLI, security/coverage/error hardening and real independent Claude findings; [PR #536](https://github.com/kinoko34077/devflow/pull/536), [#538](https://github.com/kinoko34077/devflow/pull/538), [#539](https://github.com/kinoko34077/devflow/pull/539), [#540](https://github.com/kinoko34077/devflow/pull/540). These are implemented on main, not hypothetical interfaces.
- **B3 functional end-to-end accepted**: actual GitHub-stored [#553 original READ_ONLY REQUEST](https://github.com/kinoko34077/devflow/issues/553#issuecomment-6175925357), [ACK](https://github.com/kinoko34077/devflow/issues/553#issuecomment-6176152072), [ANSWER](https://github.com/kinoko34077/devflow/issues/553#issuecomment-6176156906) share exact KAEP parent/exchange/task/intent/scope/head. Existing Claude Code session reported that its normal idle check-in called the read-only Agent Inbox CLI **before** any direct Issue fetch or #503 pointer read, saw #553 PENDING_REPLY, then replied; no pointer for #553 was found. **Actual trigger/session provenance and absence of a user prompt are Claude self-report, not independently authenticated by GitHub.** Its recurring prompt had already been revised after earlier user interaction to include the generic Inbox command; this is not proof of an unchanged third-party wake.
- **B4 read-contract accepted, live Codex pickup not established**: existing CLI/MCP accept `recipient=codex`; positive isolation/correlation regression [PR #556](https://github.com/kinoko34077/devflow/pull/556) merged, Required CI and Review Readiness passed. Synthetic tests do not prove a Codex client has been configured, scheduled or has communicated.
- **B5 HOLD**: legacy/unclassified Issue mailboxes are absent from machine TASK results, and #553 reported `coverage_status=INCOMPLETE` / `has_unknown_work=true`. Continue the accepted #503 pointer mailbox/reader fallback. Do not infer no work from an empty filtered view, retire old routing, create a daemon or change any schedules/credentials/Claims.
- Current operational state and evidence precedence: [Work Order #531](https://github.com/kinoko34077/devflow/issues/531), [protocol owner #503](https://github.com/kinoko34077/devflow/issues/503). The historical planning text below describes the first implementation slice; where a former “pending” statement differs, this dated accepted status supersedes it.

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
- `issues` are verified known TASKs only: **bounded single-line title hint (<=120 chars, title_is_untrusted=true)**, ref/status and their explicitly addressed KAEP READ_ONLY root messages when safely read. Issue title is user-editable untrusted *display* text, never a command or basis for assignment. Each root yields message/exchange ID, source comment URL, stored expected HEAD and correlated reply kinds. Request prose/response text are not copied into the projection. `recipient_assignment_inferred=false` even if a task is READY; only the explicit KAEP recipient distinguishes a message addressed to the consumer.
- `requests=null` and `source_state=UNAVAILABLE` for unreadable/too-large/malformed comment history. `requests=[]` only if the selected Issue's stored comments were actually fetched and parsed but no matching READ_ONLY request was observed.
- `has_unknown_work=true` on partial/unavailable/stale Projection, unexamined truncated TASK pages, **any work_status filter or offset**, or comment/actor errors. A filtered empty result or second page never constitutes full inventory. `is_full_work_inventory` is true only for an actually COMPLETE underlying M3 view with unfiltered, offset-zero, non-truncated known TASK records; even then it does not prove unexamined KAEP roots on legacy/non-TASK Issues are absent. No consumer may conclude no work exists from a partial/filtered page.
- `can_authorize_execution=false`, `can_replace_manual_active_work=false`, `is_authoritative_assignment=false`, and `is_live_agent_delivery=false` remain invariant.
- GitHub comment author matching the configured expected account is transport actor checking only, not independent model/session authentication. Outsider KAEP marker comments are excluded **before** strict v0.2 mailbox collision/parsing, reported as `UNTRUSTED_MARKER_COMMENT` and cannot starve genuine owner-authored requests. Trusted malformed messages still fail closed. A stored ANSWER to a claude-code request counts only when reply recipient is **chatgpt** and parent/exchange/task/intent/scope/author match. This recipient is a current v0.1 GPT→Claude request convention, not a general multi-party routing claim. A stored ANSWER is evidence to recheck, not formal PR Review or a completed task.

## Boundaries and historical first-slice acceptance
- The first slice is **per repository** and scans **at most 20 selected machine TASKs** per call, one at a time; each scanned Issue comment history is limited to 500 entries and failures are exposed as unknown. Legacy/unclassified Issues and KAEP roots living on them are NOT included; the accepted #503 KAEP pointer-only mechanism remains a fallback for those.
- A user-managed Claude check-in has now **self-reported** use of the native CLI and produced a genuine source-correlated #553 ACK/ANSWER. That is stronger than a manual-only prototype but does not establish independently authenticated trigger identity, prove the Claude check-in automatically loads MCP/AGENTS.md, or justify replacing #503 pointers while source coverage remains partial.
- The Project remains a **display** of canonical issue state; do not treat its filtered columns or labels as independent assignment or source truth.
- Existing Claude idle policy is uncapped 5→10→20→40→80→... min, resets on genuine work. The GPT-issued override (<=60min single deferral and lifetime) is separate/deferred, not implemented here.

## Remaining acceptance before broader rollout
Completed Claude #532–#535 independent READ_ONLY consultation, negative tests, B3 source-correlated #553 and B4 Codex synthetic read parity are linked above. Remaining separate requirements: independent user-managed check-in trigger provenance if claimed as fully unattended; genuine Codex client integration if authorized; and M3 missing/legacy coverage or equivalent proven fallback before B5 retirement. No new scheduler, credentials, deployment or Claim authority.
## CLI fallback for an existing Claude check-in without Devflow MCP registration

Claude #533 verified that its current session could read devflow via native Python/GitHub CLI but had no Devflow MCP tool registered. The following GET-only command therefore requires no new MCP registration or timer changes, and can be called **as one step inside** the user-managed check-in:

```sh
python -m tools.kaep_agent_inbox_cli --repository kinoko34077/devflow --recipient claude-code --work-status AWAITING_REVIEW --pending-only
```

The CLI calls the accepted DevflowService.get_agent_inbox in a **single already-authorized local process**, prints redacted/bounded JSON and exits. Add up to five explicit `--repository owner/name` flags, `--limit 1..20` and `--offset` to page; it does not scan all managed repositories by default. The report always includes an explicit false `can_authorize_execution` and `can_modify_checkin_schedule`. `--pending-only` filters out already answered records, but keeps unreadable Issue records as unknown diagnostics; partial/incomplete means NOT empty success. Even a pending request is an instruction to READ THE SOURCE and verify current authority, not a Claim or permission to write.

Manual CLI use alone establishes only native read capability. In B3, an actual stored ACK/ANSWER from a Claude session that reported ordinary check-in CLI-first discovery was additionally observed; that report does **not** independently prove trigger provenance or an unmodified automatic user-managed instruction source. #503 pointer-only routing remains a required fallback while the TASK projection is incomplete. Existing idle 5→10→20→40→80→... cadence is unchanged by this implementation.

## Evidence
Initial native MCP API [PR #536](https://github.com/kinoko34077/devflow/pull/536); truncated page safety [PR #538](https://github.com/kinoko34077/devflow/pull/538); native CLI [PR #539](https://github.com/kinoko34077/devflow/pull/539); security/correlation hardening [PR #540](https://github.com/kinoko34077/devflow/pull/540); check-in entrypoint documentation [PR #548](https://github.com/kinoko34077/devflow/pull/548); Codex test parity [PR #556](https://github.com/kinoko34077/devflow/pull/556); E2E source Issue [#553](https://github.com/kinoko34077/devflow/issues/553).