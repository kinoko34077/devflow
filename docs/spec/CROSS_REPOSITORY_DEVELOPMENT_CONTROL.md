# KiNoTch. Cross-Repository Development Control

Status: Canonical specification
Approved: 2026-09-25
Operational name: `devflow`
Current GitHub identity: `kinoko34077/devflow`
Former GitHub identity: `kinoko34077/devflow-test` (historical only)
Project setup history: `#35`
Project synchronization work: `#39`
Agent-operation hardening / rename migration: `#46` (completed)
Standing Issue-first operations: `#49`

## 1. Purpose and authority

This specification defines a low-overhead GitHub-native control plane for cross-repository development. Repository state, active work, priority, risk, audit SHA, next action and repository-local entry points must be discoverable without relying on chat history.

Canonical authority is split by responsibility:

- devflow owns Repository Control Issues, cross-repository Work Orders, workflow definitions, agent bootstrap rules and cross-repository control specifications;
- each individual repository owns its implementation, repository-local Issues/Work Orders/PRs, detailed specifications and detailed current technical state;
- Repository Base owns only its integration boundary and does not duplicate devflow rules;
- GitHub Project `KiNoTch. Development Control` is a derived display / overview layer only.

Authority direction is one-way:

```text
individual repository canonical state
  -> devflow canonical cross-repository summary
  -> Project synchronization
  -> GitHub Project display
```

Project edits must not become a source of truth for canonical Issues or repository state. Project-to-Issue reverse synchronization is prohibited in normal operation.

## 2. Agent bootstrap and read contract

The root `AGENTS.md` in devflow is the required discoverable entry point for GPT/agent cross-repository work.

Given only a managed repository name, a new worker must use this sequence:

1. read devflow `AGENTS.md`;
2. locate exactly one open devflow Issue titled `[REPO] <repository>`;
3. read its Work Status, Repository State, Audit SHA, Active Work, Next Action and repository-local entry references;
4. follow the Canonical Entry Points section when present, or equivalent verified repository-local entry references recorded in Detailed Current State / Control Notes for legacy Controls;
5. open referenced repository-local Issue/Work Order/PR before creating duplicates;
6. read only the repository-local specs, Current State, code and tests needed for the current work;
7. read this specification / `.devflow/WORKFLOW.yaml` when workflow semantics, cross-repository authority or operation boundaries are relevant.

Chat history, Memory and GitHub Project fields are never substitutes for this read path when current GitHub canonical state is available.

If no Control Issue exists for a repository that should be managed, onboarding is required before normal implementation. If duplicate open Control Issues exist for one repository, reconcile the duplicate control records before mutating managed state.

## 3. Repository Control Issues

Each managed repository has one open Repository Control Issue in devflow unless the repository is intentionally retired.

Canonical content:

- Repository
- Work Status
- Type
- Repository State
- Priority
- Risk
- Audit SHA
- Active Work
- Next Action
- Detailed Current State
- Canonical Entry Points, or an equivalent explicitly identified repository-local entry reference in a legacy Control pending normalization
- Control Notes

New Controls must use the current template and include an explicit `Canonical Entry Points` section. Legacy Controls remain usable when their equivalent entry references are unambiguous; normalize them when the Control is materially updated rather than rewriting unrelated repository state only for formatting.

The Control Issue is an index/current-state summary and must not duplicate detailed repository specifications, full task logs or implementation history.

Update the Control Issue when at least one of these changes:

- accepted Audit SHA;
- Work Status or Repository State;
- cross-repository Priority/Risk;
- Active Work reference;
- Next Action;
- repository-local canonical entry points;
- a P0/P1 finding materially changes readiness;
- managed/parked/deprecated/cancelled/excluded state.

Do not update it merely for every commit, test run, comment or implementation detail.

Managed scope excludes:

- `pc-files`
- `pc-files2`

New development/documentation repositories are managed by default unless explicitly excluded.

## 4. Issue and Work Order authority

### 4.1 Cross-repository Work Order — devflow

Use a devflow Work Order when the operation:

- intentionally spans multiple repositories as one coordinated change;
- changes devflow/control-plane workflow semantics;
- changes Project/synchronization/shared audit or merge rules;
- requires one final acceptance decision across repositories.

The devflow Work Order owns the shared objective, ordering, cross-repository constraints and final acceptance. It does not own repository-specific implementation detail that belongs in a child repository.

### 4.2 Repository-local Issue / Work Order — owning repository

Use the owning repository for detailed implementation/investigation whose scope belongs to one repository.

A durable local Issue is expected when work spans sessions/commits, has persistent acceptance criteria, is P0/P1, is blocked/awaits user decision, affects several local components, has dependencies, or needs lasting verification/decision history.

A truly trivial low-risk one-PR change may use the PR itself as the durable record when repository policy permits and scope/verification remain unambiguous.

Minimum durable local task information is defined in `docs/operations/REPOSITORY_ISSUE_MANUAL.md`. Repositories may keep their own template/naming convention; identical structure is not required.

### 4.3 Pull Request — owning repository

Normal repository change review boundary is the Pull Request. PR owns the actual diff and should expose linked task context, verification evidence, material limitations and rollback information when relevant.

## 5. State vocabulary

### 5.1 Work Status

Allowed states:

- `NEEDS_AUDIT`
- `AUDITED`
- `WORK_ORDER_READY`
- `READY_FOR_IMPLEMENTATION`
- `IMPLEMENTING`
- `AWAITING_REVIEW`
- `BLOCKED`
- `NEEDS_REAUDIT`
- `PARKED`
- `DONE`

In GitHub Project this concept is represented by the built-in `Status` field. Do not create a duplicate custom `Work Status` field.

Long-lived Repository Control Issues normally remain open and return to a repository-level state such as `AUDITED`, `BLOCKED` or `PARKED`; `DONE` is primarily the terminal state of finite Work Orders/operations.

### 5.2 Repository State

- `ACTIVE`
- `PARKED`
- `MAINTENANCE`
- `DEPRECATED`
- `CANCELLED`

`BLOCKED` is a Work Status, not a Repository State.

### 5.3 Priority

- `P0`
- `P1`
- `P2`
- `P3`

### 5.4 Risk

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

### 5.5 Type

Canonical devflow values:

- `FEATURE`
- `BUG`
- `SPEC`
- `AUDIT`
- `REFACTOR`
- `MAINTENANCE`
- `RESEARCH`
- `INFRA`
- `DOCS`

The Project displays this concept through custom single-select `Work Type` because `Type` is reserved by GitHub.

## 6. Audit and finding rules

Audit levels:

- `QUICK`: narrow known change / low uncertainty;
- `STANDARD`: normal new work, onboarding, or materially stale state;
- `FULL`: broad/unknown-impact audit only when explicitly requested or concretely justified.

FULL audits are not periodic by default.

Every meaningful audit records a concrete SHA or an explicit reason a SHA does not exist.

Finding escalation:

- P0/P1: create/retain a durable owning-repository Issue unless already equivalently tracked;
- P2/P3: summarize by default unless dependency, explicit deferral, handoff or longevity requires a separate Issue.

## 7. Project field mapping

| devflow concept | Project field | Kind |
| --- | --- | --- |
| Work Status | Status | GitHub built-in single-select |
| Repository State | Repository State | custom single-select |
| Priority | Priority | custom single-select |
| Risk | Risk | custom single-select |
| Type | Work Type | custom single-select |
| Repository | Managed Repository | custom text |
| Next Action | Next Action | custom text |
| Audit SHA | Audit SHA | custom text |

A closed canonical Issue projects `Status = DONE`.

GitHub built-in `Repository` identifies the repository containing the Issue. Because Repository Control Issues live in devflow, it is not a substitute for `Managed Repository`.

Missing canonical sections are not guessed. Unsupported/unknown select values are errors rather than approximate matches.

## 8. GitHub Project configuration

Project:

- Title: `KiNoTch. Development Control`
- URL: `https://github.com/users/kinoko34077/projects/1`
- Visibility: Private
- Role: display/overview only

### 8.1 Views

#### Repository Overview

Show at least:

- Managed Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Next Action

#### Work Queue

Show at least:

- Status
- Priority
- Work Type
- Managed Repository
- Risk
- Next Action

### 8.2 Built-in Project workflows

Current accepted configuration:

1. Auto-add: repository `kinoko34077/devflow`, filter `is:issue is:open`.
2. Item closed / Issue closed -> built-in `Status = DONE`.

The following remain disabled unless a later specification explicitly changes them:

- Auto-close issue
- Auto-add sub-issues
- Pull request linked to issue
- Item added
- Pull request merged
- Auto-archive
- Code changes requested
- Code review approved
- Item reopened

Built-in automation must not create a Project-to-Issue reverse authority path.

Direct verification of this configuration was completed during rename acceptance Work Order #46. API-invisible Project workflow properties must be rechecked directly when structurally changed or when a repository identity migration affects them.

## 9. Automated Project synchronization

Implementation:

- `.github/workflows/project-sync.yml`
- `scripts/project_sync.py`
- `docs/project/PROJECT_SYNC.md`
- tests in `tests/test_project_sync.py`

The synchronizer is operational. Project access uses repository secret `PROJECTS_TOKEN`.

### 9.1 Event sync

Issue events trigger synchronization for the affected devflow Issue:

- opened
- edited
- reopened
- closed

The dedicated Sync Health Issue is excluded before Project access to prevent recursive runs.

### 9.2 Manual verification and reconciliation

`workflow_dispatch` supports:

- `verify`: Project comparison only; no Project mutation;
- `reconcile`: repair supported drift from canonical devflow state and then verify again;
- optional Issue number to limit scope.

No periodic schedule exists in v1.

### 9.3 Runtime discovery

Do not commit GraphQL node IDs for Project, fields, options or items.

Stable configuration is:

- owner: `kinoko34077`
- Project number: `1`
- exact canonical field/option names

IDs are resolved dynamically through GitHub GraphQL. Missing/duplicated/wrong-type fields or select options are blocking configuration errors.

### 9.4 Mutation boundary

The synchronizer may:

- add canonical devflow Issues to the display Project when missing;
- update supported Project field values when canonical state differs;
- remove the machine-maintained Sync Health Issue from the display Project if accidentally auto-added.

The synchronizer must not:

- close/reopen canonical Issues because of Project values;
- rewrite Issue bodies from Project data;
- infer values absent from canonical state;
- expose credential values.

## 10. Sync Health and direct verification

One machine-maintained Issue has exact title:

`[SYSTEM] GitHub Project Sync Health`

It is Current State evidence, not an append-only history log.

Result values:

- `PASS`: all implemented API-verifiable synchronization requirements match;
- `DEGRADED`: synchronization works but a non-blocking check is unavailable;
- `FAIL`: API-verifiable drift/error remains;
- `NOT_CONFIGURED`: required Project access is unavailable.

It records last verification time, mode, Project identity, coverage/counts, drift/errors, Actions run and whether direct Project verification is required.

Normal sessions that cannot directly read the private Project use Sync Health + relevant devflow Issues + Actions evidence.

Direct inspection by a Project-capable agent is required when:

- Project fields/views/workflows are structurally changed;
- API coverage cannot verify a required UI property;
- Sync Health requests `CODEX_REQUIRED`;
- API result and observed UI disagree;
- owner/project number/field names or repository identity migration affects configuration;
- user explicitly requests direct Project verification.

The direct verifier compares live Project state against this specification and records exact discrepancies in the active Work Order/verification Issue.

## 11. Authentication boundary

Project access uses repository Actions secret:

`PROJECTS_TOKEN`

Credential creation, permission grants, rotation and secret registration are user-admin/security-sensitive actions.

Token values must never appear in repository files, Issue bodies, comments, logs or health output.

Repository `GITHUB_TOKEN` is used only for repository-scoped Issue reads/health updates and is not treated as the Project credential.

## 12. Operating lifecycle

Normal repository work:

```text
read devflow Control + local canon
-> audit relevant current SHA
-> repository-local Issue/Work Order when durable tracking is warranted
-> dedicated branch
-> implementation
-> tests/regression/real-entry verification as applicable
-> PR
-> re-audit changed scope
-> merge under current safety policy
-> local canon/current-state reconciliation
-> devflow Control reconciliation when summary changed
```

A devflow cross-repository Work Order may parent multiple repository-local child Issues/PRs.

Update devflow only when cross-repository summary state changes. Project display follows canonical devflow state.

Already-authorized LOW/MEDIUM changes with low catastrophic potential may merge after current verification when safely reversible by revert PR. Release/deploy/publication/destructive deletion/history rewrite/security-sensitive credential or permission changes and other difficult-to-reverse operations require explicit user confirmation before execution.

If a merged change proves faulty, use a dedicated rollback branch + revert PR. Do not rewrite shared `main`.

## 13. Restart and handoff contract

A new worker resumes from durable GitHub evidence, not previous chat narrative:

1. Repository Control Issue;
2. referenced local Issue/Work Order/PR;
3. recorded Audit SHA versus current default branch/PR head;
4. local canonical specs/Current State referenced by those records;
5. the first acceptance condition lacking current verification evidence.

If devflow summary disagrees with repository-local technical canon, the owning repository governs detailed technical truth and devflow must be reconciled as the summary.

If two repository-local canonical sources conflict, do not guess. Resolve the local source conflict before using it as a basis for implementation.

## 14. Repository Base boundary

Being devflow-managed does not imply Repository Base adoption.

For Base-adopted repositories, after reading the devflow Control Issue, agents enter the repository through its local `AGENTS.md` and Base-defined local read order. Base may point to devflow rules but must not duplicate state vocabulary, Project configuration or detailed cross-repository lifecycle as a second canon.

For non-Base repositories, Control Issues record their actual existing entry points. Absence of `.kinotch/`, `AGENTS.md` or Base layout is not a defect by itself.

## 15. Repository rename history

The GitHub repository was renamed from `kinoko34077/devflow-test` to `kinoko34077/devflow` on 2026-09-25. Work Order #46 completed and accepted the migration.

Accepted evidence is recorded in #46, `[REPO] devflow` #16 and `docs/project/PROJECT_SYNC.md`, including:

- repository identity resolves as `kinoko34077/devflow`;
- Issues/PRs/Actions/default branch remained usable and `main` remained protected;
- Project Auto-add was directly verified for `kinoko34077/devflow` with `is:issue is:open`;
- full Project reconcile and verify succeeded;
- Sync Health recorded zero accepted drift/errors and no unresolved direct-verification requirement.

Historical Issue/PR/commit references may retain `devflow-test` when they identify past events. The former name must not be used as a current runtime/default identity.

## 16. Detailed operations manuals

- Root start contract: `AGENTS.md`
- Agent lifecycle/manual: `docs/operations/AGENT_OPERATING_MANUAL.md`
- Repository-local Issue/Work Order manual: `docs/operations/REPOSITORY_ISSUE_MANUAL.md`
- Project synchronization: `docs/project/PROJECT_SYNC.md`
- Standing Issue-first reporting: Issue #49

These manuals explain this specification; they must not establish conflicting authority.
