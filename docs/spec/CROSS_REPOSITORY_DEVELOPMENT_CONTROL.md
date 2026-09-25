# KiNoTch. Cross-Repository Development Control

Status: Canonical specification
Approved: 2026-09-25
Owner repository: `kinoko34077/devflow-test` (planned operational name: `devflow`)
Project setup history: `devflow-test#35`
Project synchronization work: `devflow-test#39`

## 1. Purpose and authority

This specification defines a low-overhead GitHub-native control plane for cross-repository development. Repository state, active work, priority, risk, audit SHA, and next action must be discoverable without relying on chat history.

Canonical authority is split by responsibility:

- devflow owns Repository Control Issues, cross-repository work Issues, workflow definitions, and cross-repository control specifications;
- each individual repository owns its implementation, repository-local Issues/PRs, and detailed current technical state;
- GitHub Project `KiNoTch. Development Control` is a derived display / overview layer only.

Authority direction is one-way:

```text
individual repository state
  -> devflow canonical operational state
  -> Project synchronization
  -> GitHub Project display
```

Project edits must not become a source of truth for canonical Issues or repository state. Project-to-Issue reverse synchronization is prohibited in normal operation.

## 2. Repository Control Issues

Each managed repository has one open Repository Control Issue in devflow unless the repository is intentionally retired.

Canonical content:

- Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Active Work
- Next Action
- Detailed Current State

The Control Issue is an index/current-state summary and must not duplicate detailed repository specifications or implementation history.

Managed scope excludes:

- `pc-files`
- `pc-files2`

New development/documentation repositories are managed by default unless explicitly excluded.

## 3. State vocabulary

### 3.1 Work Status

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

### 3.2 Repository State

- `ACTIVE`
- `PARKED`
- `MAINTENANCE`
- `DEPRECATED`
- `CANCELLED`

`BLOCKED` is a Work Status, not a Repository State.

### 3.3 Priority

- `P0`
- `P1`
- `P2`
- `P3`

### 3.4 Risk

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

### 3.5 Type

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

## 4. Project field mapping

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

## 5. GitHub Project configuration

Project:

- Title: `KiNoTch. Development Control`
- URL: `https://github.com/users/kinoko34077/projects/1`
- Visibility: Private
- Role: display/overview only

### 5.1 Views

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

### 5.2 Built-in Project workflows

Enabled:

1. Auto-add: repository `kinoko34077/devflow-test`, filter `is:issue is:open`.
2. Item closed / Issue closed -> built-in `Status = DONE`.

Disabled unless a later specification explicitly changes this:

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

## 6. Automated Project synchronization

Implementation:

- `.github/workflows/project-sync.yml`
- `scripts/project_sync.py`
- `docs/project/PROJECT_SYNC.md`
- tests in `tests/test_project_sync.py`

The synchronizer is implemented under Work Order `#39`. Live Project access requires repository secret `PROJECTS_TOKEN`; until that credential is configured, implementation is present but live synchronization/verification reports `NOT_CONFIGURED`.

### 6.1 Event sync

Issue events trigger synchronization for the affected devflow Issue:

- opened
- edited
- reopened
- closed

The dedicated Sync Health Issue is excluded before Project access to prevent recursive runs.

### 6.2 Manual verification and reconciliation

`workflow_dispatch` supports:

- `verify`: Project comparison only; no Project mutation;
- `reconcile`: repair supported drift from canonical devflow state and then verify again;
- optional Issue number to limit scope.

No periodic schedule exists in v1.

### 6.3 Runtime discovery

Do not commit GraphQL node IDs for Project, fields, options, or items.

Stable configuration is:

- owner: `kinoko34077`
- Project number: `1`
- exact canonical field/option names

IDs are resolved dynamically through GitHub GraphQL. Missing/duplicated/wrong-type fields or select options are blocking configuration errors.

### 6.4 Mutation boundary

The synchronizer may:

- add canonical devflow Issues to the display Project when missing;
- update supported Project field values when canonical state differs;
- remove the machine-maintained Sync Health Issue from the display Project if it was accidentally auto-added.

The synchronizer must not:

- close/reopen canonical Issues because of Project values;
- rewrite Issue bodies from Project data;
- infer values absent from canonical state;
- expose credential values.

## 7. Sync Health and indirect verification

One machine-maintained Issue has exact title:

`[SYSTEM] GitHub Project Sync Health`

It is Current State evidence, not an append-only history log.

Result values:

- `PASS`: all implemented API-verifiable synchronization requirements match;
- `DEGRADED`: synchronization works but a non-blocking check is unavailable;
- `FAIL`: API-verifiable drift/error remains;
- `NOT_CONFIGURED`: `PROJECTS_TOKEN` is absent or Project access is unavailable before live activation.

It records:

- last verification time;
- mode;
- Project identity;
- coverage/counts;
- drift/errors;
- Actions run reference;
- whether direct Project verification is required.

After live acceptance, normal ChatGPT sessions that cannot directly read the private Project should use Sync Health + relevant devflow Issues + Actions evidence as the normal verification path.

## 8. Direct Project verification escalation

Direct inspection by Codex or another Project-capable agent is required when:

- initial live rollout is accepted;
- Project fields/views/workflows are structurally changed;
- API coverage cannot verify a required UI property;
- Sync Health requests `CODEX_REQUIRED`;
- API result and observed UI disagree;
- owner/project number/field names migrate;
- user explicitly requests direct Project verification.

The direct verifier must compare live Project state against this specification and record exact observations/discrepancies in the active Work Order/verification Issue. GitHub UI limitations must not silently rewrite canonical requirements.

## 9. Authentication boundary

Project access uses repository Actions secret:

`PROJECTS_TOKEN`

Credential creation, permission grants, and secret registration are user-admin/security-sensitive actions.

Token values must never appear in repository files, Issue bodies, comments, logs, or health output.

Repository `GITHUB_TOKEN` is used only for repository-scoped Issue reads/health updates and is not treated as the Project credential.

## 10. Operating lifecycle

Normal repository work:

`audit -> Work Order -> dedicated branch -> implementation -> verification -> PR -> re-audit -> merge`

Update devflow only when cross-repository summary state changes. Project display follows built-in workflows and the synchronizer.

Agent confirmation remains required for release/deploy/publication/destructive operations/security-sensitive permission changes. Low-risk merge may proceed when already authorized by the user and rollback remains available through a revert PR.

## 11. Verification after Project/control changes

For synchronization implementation changes:

```text
unit tests
-> compile/workflow validation
-> PR diff review
-> merge
-> live reconcile/verify after credential availability
-> one direct Project acceptance on initial rollout
```

For Project structural changes, direct Project inspection is required in addition to machine verification.

Work Order #39 is complete only after code/docs are merged, `PROJECTS_TOKEN` is configured by the user/admin, live reconcile/verify succeeds, Sync Health reaches accepted state, and initial direct Project acceptance confirms no material API/UI mismatch.
