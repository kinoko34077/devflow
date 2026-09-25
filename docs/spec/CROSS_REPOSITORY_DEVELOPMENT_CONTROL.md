# KiNoTch. Cross-Repository Development Control

Status: Canonical specification
Approved: 2026-09-25
Owner repository: `kinoko34077/devflow-test` (planned operational name: `devflow`)

## 1. Purpose

Provide a GitHub-native cross-repository development-control system that makes it possible to determine, without relying on chat history:

- what repositories and cross-repository initiatives exist;
- which repositories are active, parked, maintenance-only, deprecated, or cancelled;
- which work is currently active;
- the current priority and risk;
- the latest audited commit;
- the next action and where detailed state lives.

Management overhead must remain low. Existing GitHub state should drive display state automatically wherever practical.

## 2. Three-layer architecture

### 2.1 GitHub Project — display / overview layer

GitHub Project is a derived dashboard. It is not the operational source of truth.

Normal operation does not require ChatGPT or the user to edit Project custom fields directly. Built-in Project workflows and, where needed, GitHub Actions synchronize canonical state into the Project.

The primary Project items are:

- one Repository Control Issue per managed repository;
- cross-repository operational Issues maintained in devflow.

Individual repositories may expose links to their active Issues / PRs through their Repository Control Issue. Adding every repository-local Issue / PR to the Project is optional, not required for correctness.

### 2.2 devflow — cross-repository Current State source of truth

`devflow` is the cross-repository Current State Hub.

It owns:

- Repository Control Issues;
- cross-repository operational Issues;
- workflow definitions;
- cross-repository development-control specifications;
- references to repository-local current state and active work.

It does not duplicate repository-specific technical specifications or detailed implementation state.

### 2.3 Individual repositories — repository-specific source of truth

Each repository owns its own:

- README / AGENTS entry guidance;
- specifications;
- CURRENT_STATE or equivalent current technical state;
- repository-local Issues and Pull Requests;
- ADR / decisions;
- tests and source code.

Repository-local Issue / PR state remains canonical for individual work items.

## 3. Managed repository scope

Manage all development and documentation repositories owned by `kinoko34077`, except explicit backup repositories:

- `pc-files`
- `pc-files2`

Current initial managed set:

1. `.ai-guidelines`
2. `2bit-cell-automaton`
3. `Structured-Cell-Automaton`
4. `Gomoku-5D`
5. `IDS-Composit`
6. `Mapience-prototype`
7. `Micro-Chordbot`
8. `SynTrail-LM`
9. `colony-ai`
10. `cora_engine`
11. `dev_agent`
12. `devflow-test`
13. `jev-audit`
14. `kinotch-api`
15. `kinotch-default-canary`
16. `kinotch-repository-base`
17. `kinotch-runtime`
18. `kotonomani`
19. `line-style-viewer`
20. `lyric_reader_page`
21. `memory-game`
22. `microtone-piano`
23. `obsidian-related-notes-view`
24. `refil-viewer`
25. `srt2subtitle`
26. `stackedit.io`
27. `standby-display`
28. `testapp`
29. `txt-auto-replace`
30. `weather-widget`

New development / documentation repositories are managed by default unless explicitly excluded.

## 4. Work Status

Allowed work states:

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

Work Status describes a work item, not the repository lifecycle.

## 5. Repository State

Allowed repository states:

- `ACTIVE`
- `PARKED`
- `MAINTENANCE`
- `DEPRECATED`
- `CANCELLED`

`BLOCKED` is not a Repository State. A repository may be ACTIVE while its current work item is BLOCKED.

## 6. Priority

- `P0` — urgent
- `P1` — high
- `P2` — normal
- `P3` — low

## 7. Risk

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

## 8. Type

- `FEATURE`
- `BUG`
- `SPEC`
- `AUDIT`
- `REFACTOR`
- `MAINTENANCE`
- `RESEARCH`
- `INFRA`
- `DOCS`

## 9. Repository Control Issue

Each managed repository has exactly one open Repository Control Issue in devflow unless the repository is permanently retired and its control record is intentionally closed.

Required information:

- Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Active Work
- Next Action
- Detailed Current State reference

The Control Issue is an index and current-state summary. It must not copy detailed repository specifications or implementation history.

## 10. Next Action

`Next Action` is free text ending with a searchable category tag.

Example:

`Trainer差分をSTANDARD監査 [AUDIT]`

Initial tags:

- `[AUDIT]`
- `[SPECIFY]`
- `[IMPLEMENT]`
- `[VERIFY]`
- `[REVIEW]`
- `[MERGE]`
- `[RELEASE]`
- `[USER_DECISION]`
- `[WAIT]`
- `[NONE]`

## 11. Audit SHA and Last Audit

Store the audited commit as `Audit SHA`.

Do not manually duplicate `Last Audit` when the date can be derived from commit metadata for the Audit SHA.

## 12. Project fields

The display Project should expose at least:

- Work Status
- Repository State
- Priority
- Type
- Repository
- Next Action
- Risk
- Audit SHA

Project fields are derived display state whenever automation can provide them.

## 13. Project views

### Repository Overview

Primary fields:

- Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Next Action

### Work Queue

Primary fields:

- Work Status
- Priority
- Type
- Repository
- Risk
- Next Action

## 14. Project automation

Prefer GitHub Projects built-in workflows for simple GitHub-native events such as:

- automatic item addition;
- initial status on item addition;
- Issue close -> DONE;
- PR merge -> DONE where PR items are used;
- archive of completed items.

Use GitHub Actions only when built-in workflows cannot express required synchronization, such as custom Project fields derived from Repository Control Issue state.

Synchronization direction is normally:

`canonical GitHub state -> GitHub Project`

Do not make Project-field edits the normal source of changes back into devflow or repository state.

## 15. Cross-repository work

Work affecting multiple repositories belongs in devflow.

Examples:

- GitHub Project construction;
- cross-repository branch-protection audits;
- Repository Base adoption policy;
- shared workflow changes;
- development-control specification changes.

Work contained to one repository remains in that repository.

## 16. Read order

### Cross-repository request

1. GitHub Project, when the current execution environment can read it.
2. devflow Repository Control / cross-repository Issues.
3. Target repository.
4. Repository CURRENT_STATE or equivalent.
5. Active repository Issue / PR.
6. Relevant specification, code and tests.

### Environment cannot read GitHub Project

Start at devflow and continue. Project access must not become a single point of failure for development work.

## 17. Update order

Normal direct updates target:

1. the affected individual repository;
2. devflow, only when the cross-repository state changes.

The Project is updated by automation rather than routine direct editing.

Update devflow when there is a meaningful cross-repository state change, including:

- Repository State change;
- Priority or Risk change;
- active main work change;
- Next Action change;
- BLOCKED / PARKED transition;
- audit completion;
- Audit SHA change.

Do not update devflow for repository-local changes that do not alter the cross-repository summary.

## 18. Audit levels

### QUICK

Narrow targeted check for a known issue or small diff.

### STANDARD

Normal development audit of relevant Current State, specs, code, tests, interfaces, Issues and PRs.

### FULL

Repository-wide audit only when explicitly justified. Never run periodic repository-wide FULL audits by default.

## 19. Finding escalation

- `P0` / `P1`: create an Issue automatically unless an existing Issue already tracks the finding.
- `P2` / `P3`: report in audit results by default; create an Issue only when tracking, dependency or explicit request requires it.

## 20. PR policy

All repository changes normally follow:

`Issue / Work Order -> dedicated branch -> implementation -> verification -> Pull Request -> re-audit -> merge`

Direct default-branch changes are outside the normal workflow.

## 21. Agent confirmation boundary

When requirements are sufficiently defined, an agent may proceed automatically through:

- inspection;
- audit;
- Issue creation;
- Work Order creation;
- branch creation;
- implementation;
- tests / verification;
- PR creation;
- PR re-audit.

Require user confirmation before:

- merge;
- release;
- deploy;
- publication;
- destructive deletion;
- difficult-to-reverse operations;
- security-sensitive permission or credential changes.

## 22. Information-boundary rule

Do not duplicate the same live state without need across:

- GitHub Project;
- devflow;
- repository CURRENT_STATE;
- Issues;
- Pull Requests;
- specifications.

Each layer stores only the information required by its responsibility. The Project should display derived state wherever practical.

## 23. Migration from devflow-test

The proven `devflow-test` principles remain valid:

- GitHub Issues / PRs are the canonical live operational state for work items;
- chat history is not canonical;
- implementation actor is unrestricted;
- workflow definition is separate from individual task state.

The repository is promoted operationally first. Renaming `devflow-test` to `devflow` or another permanent name is a separate GitHub administration step and does not block the initial construction.
