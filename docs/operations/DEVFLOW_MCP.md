# Devflow MCP

`tools/devflow_mcp.py` exposes live `kinoko34077/devflow` operational state to Codex, Claude Code and other MCP clients through a read-only stdio server.

This MCP is an access layer, not a second source of truth. Canonical authority remains:

- devflow Repository Control / Work Order Issues for cross-repository operational state;
- the owning repository for detailed technical truth;
- GitHub Project as display-only.

## Read-only boundary

The server exposes only read operations:

- `bootstrap_repository(repository)`
- `get_repository_control(repository)`
- `list_managed_repositories()`
- `get_repository_projection(repository)`
- `get_repository_work_view(repository)`
- `get_agent_inbox(repository, recipient="claude-code", limit=20, offset=0, work_status=None)`
- `get_portfolio_projection()`
- `get_human_portfolio(repository)`
- `get_issue(repository, issue_number)`
- `get_issue_goal_context(repository, issue_number)`
- `assess_issue_plan(repository, issue_number, plan)`
- `get_sync_health()`

This list reflects the **currently exported** twelve functions in `tools/devflow_mcp.py`, not only the original bootstrap-only toolset. All remain read-only. `get_repository_work_view` projects trusted all-state TASKs and incomplete-source diagnostics; `get_agent_inbox` additionally inspects validated KAEP READ_ONLY roots on bounded machine TASKs for an **explicit recipient**. Neither conveys task assignment, claim/lease, permission to execute, source completeness or successful agent delivery. Native check-in CLI usage is documented in [Agent Inbox](../spec/KAEP_AGENT_INBOX_V01.md).

The underlying GitHub client implements GET-only REST access. It has no Issue update, PR mutation, merge, branch, credential, release or deployment tool.

## Codex Cloud fallback when MCP tools are not registered

Codex Cloud tasks may have a usable devflow checkout and GitHub read access without
exposing any `kinotch_devflow` tool in the task's MCP registry. An empty
`codex mcp list --json` is a **tool-registration** observation, not evidence
that the underlying Devflow read methods are unavailable. Do not recreate
the MCP server just for this client gap.

From the existing devflow checkout, use the read-only CLI that delegates to
exactly the same `tools.devflow_mcp_core.default_service()` as the stdio MCP:

```sh
python -m tools.devflow_read_cli bootstrap --repository kinoko34077/devflow
python -m tools.devflow_read_cli work-view --repository kinoko34077/devflow
python -m tools.devflow_read_cli inbox --repository kinoko34077/devflow --recipient codex --work-status AWAITING_REVIEW
```

For one Issue's source-linked effective Goal Context, both client paths call the
same `DevflowService.get_issue_goal_context` method and return the same structured
projection:

```sh
python -m tools.devflow_read_cli issue-goal-context --repository kinoko34077/<repo> --issue-number <N>
```

The MCP equivalent is `get_issue_goal_context(repository, issue_number)`. It
preserves source contexts, citations, proposals, effective specifications and
unknowns. It does not prove citation truth. If neither shared entry is available,
read the exact Issue and explicit parents directly from GitHub; inaccessible or
malformed sources remain unknown, not empty.

For a candidate plan that explicitly lists typed effects, use the shared
read-only comparison. Only an exact `key` + `scope` match against a complete,
adopted Goal Context claim can produce `CONFLICTS_DETECTED`; inferred, proposed,
removed, inaccessible, or unrepresented conditions remain unknown or unchecked.
The result covers declared effects only, never claims the plan is complete,
does not authenticate Issue authorship or authority labels, evaluate prose
meaning or citation truth, or authorize work.
Source authority in this contract is a declared Issue assertion; the checker
does not authenticate its author.

```sh
python -m tools.devflow_read_cli assess-issue-plan \
  --repository kinoko34077/<repo> --issue-number <N> --plan-file plan.json
```

The MCP equivalent is `assess_issue_plan(repository, issue_number, plan)`. The
optional `Declared goal plan assessment pilot` workflow runs the comparator
from the event-pinned base commit, not PR-supplied code, for a single
machine-readable plan packet embedded between
`DEVFLOW_GOAL_PLAN_V1_BEGIN` / `_END` markers in a PR description. It reads
public Issues anonymously and has no repository token scope; inaccessible or
private source ancestry returns `NEEDS_EVIDENCE`. The workflow fails for a
direct deterministic conflict in the declared packet, but is not a required
branch-protection check. No packet is reported as skipped; neither this pilot
nor an omitted packet proves that all PR plans were assessed.

If the event-pinned base does not yet contain the comparator (as on its
introduction PR), the pilot reports `SKIPPED_EVALUATOR_NOT_ON_BASE` and exits
successfully without evaluating the packet. This is an explicit non-evaluation;
the workflow never runs PR-supplied evaluator code. A later PR based on the
merged comparator is required for hosted comparison evidence.

The packet is deliberately limited to intended typed effects; it is not a
second Issue/specification record. A set effect must include `value` (including
`false`, `0`, or `null`); a removal omits it. For example:

```json
{
  "schema_version": 1,
  "task_ref": "kinoko34077/<repo>#<issue>",
  "steps": [{
    "id": "change-runtime-path",
    "intent": "Use the existing realtime settings path",
    "declared_effects": [{
      "key": "runtime.path",
      "scope": "playback",
      "state": "set",
      "value": "existing-realtime"
    }]
  }]
}
```

To compare a claimed user-facing outcome with the required surface and target
artifact, use the read-only outcome observation adapter. It binds the packet's
Issue body hash to a fresh read of that exact Issue, then compares declared
surface and target strings. It does **not** parse the Issue to establish that
the declarations are requirements, fetch or authenticate evidence links,
verify authorship, or prove the runtime result. Its `DECLARED_ALIGNED` status
means only that the packet's declarations agree; source verification remains
`NOT_PERFORMED`, and task acceptance stays false.

```sh
python -m tools.devflow_read_cli assess-outcome-observation \
  --repository kinoko34077/<repo> --issue-number <N> --outcome-file outcome.json
```

The packet schema is deliberately explicit. `issue_body_sha256` must be the
current owning Issue body hash; `required_surface` and `required_target` are
declarations supplied by the caller, not values inferred by this comparator.

```json
{
  "task_ref": "kinoko34077/<repo>#<issue>",
  "issue_body_sha256": "<64 lowercase hex characters>",
  "required_surface": "PUBLIC_BROWSER",
  "required_target": "git:<full-commit-sha>",
  "observed_surface": "PUBLIC_BROWSER",
  "observed_target": "git:<full-commit-sha>",
  "observed_result": "SUCCESS",
  "evidence_refs": [
    "https://github.com/kinoko34077/<repo>/issues/<issue>#issuecomment-<id>"
  ]
}
```

The MCP equivalent is
`assess_outcome_observation(repository, issue_number, evidence)`. Outcome values
preserve `SUCCESS`, `FAILURE`, `VALID_NEGATIVE`, `UNKNOWN`, and `NOT_RUN`.
Surface or target mismatches are reported separately; absent target identity
remains `UNKNOWN`; missing or malformed references remain `NEEDS_EVIDENCE`.
The result never authorizes work, merge, release, deployment, permission
changes, or task-wide acceptance.

The existing unprivileged trusted-base pilot also reads one optional JSON
packet from a PR body between `DEVFLOW_OUTCOME_OBSERVATION_V1_BEGIN` /
`DEVFLOW_OUTCOME_OBSERVATION_V1_END`. A detected surface/target mismatch,
missing evidence, or declared runtime failure fails this optional check. A
valid negative, `UNKNOWN`, or `NOT_RUN` remains distinct. No packet or an
evaluator absent from the event-pinned base produces an explicit skip. The
workflow has `permissions: {}`: it validates declarations within the packet,
does not read the cited source, and does not verify whether the claimed Issue
hash is current. This GitHub result is contract-consistency evidence only, not
proof of public-browser, physical-runtime, or end-user success.

### Historical example: japanese-orthography #310 S310-A

Use this only as a narrowly accepted, historical public-browser case. The owner
receipt records the deployed source target and a bounded set of browser checks:
[#310 comment #6106750343](https://github.com/kinoko34077/japanese-orthography/issues/310#issuecomment-6106750343).
The packet below binds the comparison to the #839 Issue-body revision observed
on 2026-10-31. Any later edit to that body requires a new hash.

```json
{
  "task_ref": "kinoko34077/devflow#839",
  "issue_body_sha256": "d08d84941f2db9de48b0cac19d2a709ff12d85034bd9bbd20f19c13166479f74",
  "required_surface": "PUBLIC_BROWSER",
  "required_target": "git:f38d562edfda0bbaefaa3e1b6d71ccb078c26364",
  "observed_surface": "PUBLIC_BROWSER",
  "observed_target": "git:f38d562edfda0bbaefaa3e1b6d71ccb078c26364",
  "observed_result": "SUCCESS",
  "evidence_refs": [
    "https://github.com/kinoko34077/japanese-orthography/issues/310#issuecomment-6106750343"
  ]
}
```

That receipt is a past limited observation, not a fresh check of today's Pages
content or proof that every #310 scenario works. The separate tokenWindow
fixture witness in [#310 comment #6106079188](https://github.com/kinoko34077/japanese-orthography/issues/310#issuecomment-6106079188)
is `FIXTURE_PARITY`, so treating it as `PUBLIC_BROWSER` must produce a surface
mismatch; it is a false-positive control, not a second browser success.
Gesture IME [#203 comment #6116020441](https://github.com/kinoko34077/gesture-ime/issues/203#issuecomment-6116020441)
preserves the reported physical failure while installed IPA identity remains
unknown. These examples test declaration handling; the comparator does not
fetch or authenticate the linked comments.

A follow-up PR based on a commit that already contains this evaluator can carry
the #310 packet between the pilot markers. Its hosted Actions output should be
recorded as declaration-consistency evidence only. The introduction [PR #840](https://github.com/kinoko34077/devflow/pull/840)
explicitly reported `OUTCOME_PILOT=SKIPPED_EVALUATOR_NOT_ON_BASE` in its
[hosted run #41236135413](https://github.com/kinoko34077/devflow/actions/runs/41236135413),
because the event-pinned base did not yet include this evaluator.

A zero-result Codex/AWAITING_REVIEW query with `coverage_status=INCOMPLETE`
or `has_unknown_work=true` is *not* the end of a recipient message check:
non-TASK original Issues can contain authentic KAEP roots. For an
**already-running, authorized** Codex Cloud task that needs those messages,
reuse the existing B6 read-only bounded original-Issue union, not another
classifier or MCP server:

```sh
python -m tools.kaep_live_union_cli --recipient codex --response-format agent-api
```

This is a separate B6 candidate-discovery path (#680), not an MCP call or an
Agent Inbox authority upgrade. It combines the current public candidate
index and a bounded updated-comment window, then re-fetches original Issues
with the canonical actor/KAEP/recipient validator (up to 40 source Issues).
The public index and updated-comment window cannot prove that every new,
old, or private root was found. `BOUNDED_UNION_READ` does not authorize
execution or prove pickup; `PARTIAL_UNKNOWN`, `BLOCKED`, an empty response,
or an unverified current HEAD require direct source/Control and #503 fallback.
No timer, credentials, network settings or MCP registration are installed by
this workflow. Existing B5 (#531) remains incomplete until genuinely trusted
full-source coverage and recipient/Consumer parity are proved.

`inbox` also accepts `--limit` (1–20, with the same canonical limit
as the MCP Agent Inbox), `--offset` (nonnegative), `--recipient` and
`--work-status`; honor its `next_offset`, `truncated` and source/coverage
fields. Invalid Inbox parameters fail locally with exit code 2 and a
non-secret, fixed `reason_code` **before GitHub Control or Issue GETs**;
`--limit 21` and higher cannot be used to bypass the MCP's bounded read
contract. Agent Inbox's per-Issue source mailbox is bounded to 500 stored
comments: the GitHub reader stops after observing the 501st comment, returns
an overflow sentinel to the unchanged strict parser, and retains
`ISSUE_COMMENTS_LIMIT` / `has_unknown_work=true` rather than presenting an
empty or complete source. This bound is **only** used by the MCP Inbox
consumer; other callers such as bootstrap provenance verification continue
to read their full required histories. For an existing scheduled Claude
check-in, keep using the established `tools.kaep_agent_inbox_cli` and its
`--pending-only` behavior; this CLI does not start a check-in or manage timers.

### Approved #789 public pointer discovery (already-running Claude only)

Physical successor [devflow #789](https://github.com/kinoko34077/devflow/issues/789) is an approved, publicly readable KAEP pointer index; old #503 remains read-only fallback. The machine-TASK `get_agent_inbox`/native Inbox and default `kaep_live_union_cli` do **not** by themselves consume new #789 index comments. If an **already-active Claude recipient** sees `INCOMPLETE`/unknown machine coverage or needs new public Claude pointers, use the accepted read-only, canonical A3 two-index CLI:

```sh
python -m tools.kaep_discovery_reader --dual-shadow --expect-notice-actor kinoko34077 --expect-source-actor kinoko34077
```

This reuses the strict original source verifier against bounded #503 + #789 inputs, not a second Inbox. The malformed old #503 may produce `PARTIAL_UNKNOWN` with **exit code 2** even when verified `source_verified_roots` are present; parse and inspect the returned JSON instead of discarding those candidates based solely on the exit status. `index_diagnostics`/`index_status` preserve rejected/blocked/unknown information. Empty #789 does not prove no work; no pointer proves model pickup or current HEAD. Re-read candidate original Issue/actor/recipient/current HEAD and owning Control before any work. This is **not** a scheduled check-in, CLI/agent launch, token setup, permission grant or automatic ACK/ANSWER. No live Claude runtime invocation of #789 has been verified yet. Protocol owner #503, producer #771, recipient/B6 #680.
Exit code 0 means the read method returned structured data; it does **not**
mean that every Issue was classified or that any agent was assigned work.
`INCOMPLETE`, `has_unknown_work=true`, `UNAVAILABLE` and empty filtered
`issues` must retain the canonical manual Repository Control and KAEP
[#503 fallback](https://github.com/kinoko34077/devflow/issues/503).
Exit code 2 with `{"status":"BLOCKED",...}` means a failed read, not an
empty work inventory. This CLI cannot authorize a Claim, write an Issue or
prove the Codex MCP registry / GitHub token identity is functional.

### Three-read troubleshooting (bootstrap / work-view / inbox)

Do the comparison **inside the failing client runtime** and for the **same
repository**. Distinguish missing registration from a tool invocation failure:
first inspect the MCP tool catalog / stdio `initialize` + `tools/list` for
`bootstrap_repository`, `get_repository_work_view` and `get_agent_inbox`.
If tools are not registered, GitHub code/CLI success does not repair client
discovery. Machine-local historical startup grace fix [#113](https://github.com/kinoko34077/devflow/issues/113)
must not be presumed current without a fresh handshake failure measurement.

When a current checkout and GitHub GET access exist, run the three CLI commands
above for the **same target** and compare their return codes. All three route
to the same core service; Inbox depends on Work View, and Work View depends on
bootstrap's verified Control read. A shared failure may cascade from an
earlier GitHub read or Control validation; it does not establish three
independent defects.

For a blocked CLI read, `reason_code` is a fixed, redacted diagnostic:

| Code | Meaning / next check |
| --- | --- |
| `GITHUB_HTTP_401` | GitHub rejected authentication; inspect that runtime's read-capable credentials without printing them. |
| `GITHUB_HTTP_403` | Access policy, authentication scope **or** rate limits; inspect the runtime's safe response metadata. Do not assume a missing token. |
| `GITHUB_HTTP_404` | Resource absent **or** inaccessible (including hidden Private repositories); confirm exact repo identity and access independently. |
| `GITHUB_HTTP_429` / `GITHUB_HTTP_OTHER` | API throttling or another HTTP failure; check GitHub availability and retry only after the cause is understood. |
| `GITHUB_NETWORK_UNAVAILABLE` / `GITHUB_INVALID_JSON` / `GITHUB_REDIRECTED_READ` | Network, invalid API body or changed observed identity; keep reads fail-closed. |
| `CONTROL_NOT_FOUND_OR_UNTRUSTED` / `CONTROL_AMBIGUOUS` | No single accepted open Control; inspect its author/provenance and exact title through canonical GitHub reads. |
| `CONTROL_SCHEMA_INVALID` / `CONTROL_REPOSITORY_MISMATCH` | The Control failed required sections or repository identity checks; do not bypass validation. |
| `INVALID_ISSUE_NUMBER` | An Issue-scoped operation needs one positive Issue number; check the command arguments. |
| `ISSUE_NUMBER_ON_NON_ISSUE_OPERATION` | `--issue-number` is valid only for Issue-scoped operations (`issue-goal-context`, `assess-issue-plan`, `assess-outcome-observation`); remove it for other operations. |
| `PLAN_ON_NON_ASSESSMENT_OPERATION` | `--plan-file` is valid only for `assess-issue-plan`. |
| `OUTCOME_ON_NON_ASSESSMENT_OPERATION` | `--outcome-file` is valid only for `assess-outcome-observation`. |
| `DEVFLOW_READ_UNAVAILABLE` | Unclassified core failure; preserve manual Control and exact original Issue reads rather than infer no work. |

Codes are not proof of the underlying cause (for example, 403 and 404 remain
ambiguous). The CLI never emits the original exception text, secrets, raw URLs
or response headers. Successful output remains unchanged; partial/unknown
coverage still requires manual Control and KAEP #503 fallback. Do not change
tokens, client registration or system timers as an implicit read workaround.

Cloud evidence on #531 separately establishes existing Agent Inbox CLI and
public GitHub GET execution. It does not independently prove a fresh Cloud task
has run each read-only adapter operation; real-task execution remains a
separate acceptance check. Authentication verification and Cloud tool
registration are independent of this read-only fallback.

For Cloud **Issue writeback and credentials**, see [Codex Cloud GitHub access](CODEX_CLOUD_GITHUB_ACCESS.md): repository reads, PR publishing and Issue comments require distinct evidence; do not put a write-capable token in source or presume the Cloud client inherits ChatGPT GitHub auth. The supported CLI above remains GET-only.

## Control Issue trust boundary

devflow is a public repository, so anyone can open an Issue with a canonical-looking title. Repository Control discovery (`get_repository_control`, `bootstrap_repository`, `list_managed_repositories`) accepts directly authored `[REPO] <repo>` Issues only when their `author_association` is `OWNER`, `MEMBER` or `COLLABORATOR`. A bootstrap-generated Control may be bot-authored, but only through the dedicated derived-trust verifier: the Control must point to the exact devflow `[REPO CREATE]` request, the request must be either open or closed with `state_reason=completed`, must be trusted-authored and contain one valid `repository-bootstrap.v1` payload for the target, the request must have a successful terminal `DONE` comment from the GitHub Actions bootstrap executor naming the same Control, and the target repository's `.github/repository-bootstrap.json` must exactly match the request reference, canonical URL and repository identity. The verifier also requires one exact open Control title and the canonical devflow repository identity.

This is provenance-derived trust, not a bot allowlist. Arbitrary bot Issues, missing or malformed provenance, untrusted requests, mismatched targets, closed requests with `not_planned` or missing/unknown reasons, requests without authenticated terminal `DONE`, and collisions are rejected fail closed. Controls generated before the machine-readable `repository-bootstrap-control.v1` block was introduced remain eligible only when their canonical legacy provenance text passes the same chain validation.

The same policy applies to `get_sync_health`: only trusted-author `[SYSTEM] GitHub Project Sync Health` Issues are candidates. Untrusted candidates are ignored and listed in `ignored_untrusted_candidates`; if no trusted candidate exists the health surface is unavailable. When several trusted candidates exist, exactly one must be open.

## Exact Issue identity

`get_issue` validates the observed GitHub object, not the caller's request. The response `number` and `repository_url` must match the requested Issue (repository compared case-insensitively), pull requests are rejected, and any HTTP redirect (transfer, rename, misrouting) fails closed with a non-secret diagnostic. The caller-supplied identity is never used to fill in or relabel a response. A renamed repository must be requested by its current name.

`get_issue_goal_context` keeps the raw `get_issue` response contract unchanged.
It uses that same identity-checking reader for the requested Issue and every
explicit parent reference, with the R1 bounded resolver. Incomplete ancestry
returns explicit unknown values and bounded diagnostics; it does not expose a
failed reader's response body or treat absence of data as an adopted value. The
CLI uses the same service and emits only its fixed, redacted reason codes when
the top-level Issue read is blocked.

## Runtime

Requirements:

- Python 3.10+
- `pip install -r requirements-mcp.txt`

Start directly:

```powershell
py tools/devflow_mcp.py
```

The MCP uses stdio transport.

## GitHub authentication

Public devflow reads can work without a token. A token is recommended for rate limits and required when devflow or a target repository is private/access-controlled.

Token lookup order:

1. `DEVFLOW_GITHUB_TOKEN`
2. `GITHUB_TOKEN`
3. unauthenticated GitHub REST

Use a read-capable token only. Do not commit tokens to this repository, `.mcp.json`, `AGENTS.md`, `CLAUDE.md`, or other shared files.

## KAEP Agent Inbox operational status

As of 2026-10-15, the read-only MCP function `get_agent_inbox` and native CLI `python -m tools.kaep_agent_inbox_cli` are merged on main. A Claude Code session reported its existing idle check-in executed the CLI and discovered a new, non-pointer KAEP root before direct Issue lookup, then stored actual source-correlated [ACK/ANSWER on #553](https://github.com/kinoko34077/devflow/issues/553). This is **functional E2E evidence with a self-reported trigger path**, not an independently authenticated wake or automatic MCP registration. The recurring user-managed prompt had been modified earlier to add generic CLI invocation; connecting this MCP alone does not schedule or cause an agent to read it.

A client may call `get_agent_inbox` with `recipient="codex"` (positive read-contract/negative-routing regression [PR #556](https://github.com/kinoko34077/devflow/pull/556)). Actual Codex check-in pickup is **not** confirmed. With `coverage_status=INCOMPLETE` or `has_unknown_work=true`, preserve canonical manual Control and the KAEP [#503 pointer discovery fallback](https://github.com/kinoko34077/devflow/issues/503); do not treat a filtered empty list as zero work. No new user/agent schedules, session settings, GitHub credentials, provider launch, or Claim authority result from this interface.

## Required agent trigger

Connecting an MCP server does not guarantee that an agent will call it. Client instructions must explicitly state when live devflow is required.

Use this rule in Codex/Claude global instructions:

```text
For KiNoTch managed repositories, before answering or acting on current state, resume,
audit, implementation, review, Issue/PR/Work Order or cross-repository work, call the
KiNoTch Devflow MCP `bootstrap_repository` for the current repository. When resolving
local open work, use `get_repository_work_view` (if available) after bootstrap for
all-state TASK records and explicit manual fallback. Even MACHINE_COMPLETE_SHADOW is
read-only and cannot replace Control authority or create runtime claims. Follow the
returned Repository Control and Canonical Entry Points. Do not substitute chat history, static
.ai-guidelines content, or GitHub Project fields for live Current State. Use Issue-first
reporting for durable detail/evidence/handoff.
```

## Codex

Current Codex supports stdio MCP servers through `~/.codex/config.toml` and shares MCP configuration between CLI and IDE extension.

Example user-level configuration:

```toml
[mcp_servers.kinotchDevflow]
command = "py"
args = ["C:\\path\\to\\devflow\\tools\\devflow_mcp.py"]

[mcp_servers.kinotchGuidelines]
command = "py"
args = ["C:\\path\\to\\.ai-guidelines\\guidelines_mcp.py"]
```

Keep the token in the process environment rather than hard-coding it in the TOML. Verify with:

```powershell
codex mcp list
```

Add the required agent trigger above to user-level `~/.codex/AGENTS.md` (Windows: `%USERPROFILE%\.codex\AGENTS.md`) so Codex calls the MCP automatically when the task depends on live managed-repository state.

Official references:

- https://developers.openai.com/learn/docs-mcp
- https://developers.openai.com/docs/config-file/config-reference

## Claude Code

Claude Code supports local stdio MCP servers and user-scope MCP configuration.

Example:

```powershell
claude mcp add --scope user kinotch-devflow -- py C:\path\to\devflow\tools\devflow_mcp.py
claude mcp add --scope user kinotch-guidelines -- py C:\path\to\.ai-guidelines\guidelines_mcp.py
claude mcp list
```

Add the required agent trigger above to user-level `~/.claude/CLAUDE.md` (Windows: `%USERPROFILE%\.claude\CLAUDE.md`). Claude Code automatically loads this user instruction file for all projects.

Official references:

- https://docs.anthropic.com/docs/claude-code/mcp
- https://docs.anthropic.com/docs/claude-code/memory

## Expected bootstrap flow

For `kinoko34077/<repo>`:

1. call `bootstrap_repository("kinoko34077/<repo>")`;
2. read returned Work Status / Repository State / Audit SHA / Active Work / Next Action;
3. follow returned Canonical Entry Points in the local checkout;
4. read active owning-repository Issue / Work Order / PR as required;
5. inspect task-relevant specs / Current State / code / tests;
6. record durable progress and verification in the owning Issue; update devflow Control only when its cross-repository summary changes.

If the MCP cannot find exactly one open `[REPO] <repo>` Control Issue, it fails instead of guessing managed state.

## M3 local-work read view (operator shadow; no authority transfer)

`get_repository_work_view("kinoko34077/<repo>")` is an optional read-only
consumer of the existing live M1 Repository Projection. It returns **all**
trusted open machine TASKs, including `AWAITING_REVIEW` and `BLOCKED`, rather
than treating M2's first 20 READY/IMPLEMENTING summaries as a complete task list.

The additive `observed_task_view` describes **read-only observation**, independently
of the older `view_mode` (which still controls manual *authority* fallback).
For an AVAILABLE/CURRENT source: `COMPLETE_READ` means all open Issues are
classified, and `OBSERVED_PARTIAL` means only trusted known TASKs are shown
with `unresolved_open_issue_count` (legacy + unclassified + invalid + untrusted).
The full `task_records` list remains available in both cases; a partial list
must never be called all active work. On missing/stale sources the status is
`SOURCE_UNAVAILABLE` and counts are `null`, **not zero**. In every case
`can_replace_manual_active_work=false` and `can_authorize_execution=false`
inside this diagnostic. This is accepted approach C under
[the A–E operating model](REPOSITORY_PROJECTION_AE_OPERATING_MODEL.md), not M3.1
activation or a second task classifier.

### Parallel display / dual-read migration (A–E / #477)

`parallel_read` groups the *same* existing live manual Control fields and M1
machine TASK records into one read-only operator-friendly result. It is not
another persisted table or secondary classifier:

- `manual.active_work` and `manual.next_action` preserve the existing prose
  and cross-repository/Human semantics.
- `machine.tasks` lists all trusted open machine TASK URLs and work states on
  a current source, including review/blocked/open-DONE; it reports unresolved
  open Issue count. If source unavailable/noncurrent, `tasks=null` and
  unresolved count is `null`, **never empty or zero**.
- `link_crosscheck` compares *explicit same-repository Issue references* in
  manual `Active Work` (exact GitHub URLs and qualified `repo#123` or
  `owner/repo#123` shorthand) with current verified machine TASK URLs.
  `manual_refs_not_known_machine_tasks` and
  `known_machine_tasks_not_manually_referenced` are **navigation clues**,
  not automatically confirmed missing/extra work. The manual side may mention
  closed/history/parent Issues while the machine side may include TASKs absent
  from manual summary. Malformed partial URLs, cross-repository refs and
  unrelated prose are not used to fabricate matching tasks.
  A missing/noncurrent source yields `null` difference arrays, never a
  misleading zero or parity. This **does not prove semantic equivalence** and
  is **never a promotion gate**.

Every `parallel_read` result is `DUAL_READ_OBSERVATION`, with manual Control
authority retained, `can_replace_manual_active_work=false`, and
`can_authorize_execution=false`. Only a later explicit per-repository,
per-Consumer reviewed M3.1 cutover could alter operational read precedence;
this method does not do so. See [P0–P3 gradual plan](REPOSITORY_PROJECTION_AE_OPERATING_MODEL.md).

The response always includes a separately named `manual_control` fallback
(`active_work`, `next_action`, `canonical_entry_points`) from the verified
Control. `view_mode=MACHINE_COMPLETE_SHADOW` only when the live source is
AVAILABLE/CURRENT and has no unresolved legacy, unclassified, invalid or
untrusted open records. All other source states return
`view_mode=MANUAL_CONTROL_FALLBACK` with explicit `coverage_status` and
error/counts. A missing source must not be interpreted as zero work. Even when
all records are machine-classified, `can_replace_manual_active_work=false`
until separately admitted M3.1/M3.5/M3.6 authority migration with real
nonempty task lifecycle and consumer proof. The view does not create or
publish work, and cannot grant execution-coordinator claims or Human approval.

## Relationship to `.ai-guidelines`

The Guidelines MCP provides static shared coding/spec/UI/UX/usability policy. It must not mirror live Work Status, Audit SHA, Active Work, blockers or Sync Health.

The two MCPs are complementary:

```text
client instructions
  -> Devflow MCP       (live operational state)
  -> Guidelines MCP    (static shared policy)
  -> owning repository (technical canon + implementation)
```

<!-- R4 validation-only mismatch control: intentionally never merge this line. -->
