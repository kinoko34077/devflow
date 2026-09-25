# GitHub Project Setup Handoff

Status: Operational reference; initial setup completed
Project role: Derived display / overview layer
Canonical spec: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
Initial tracking Issue: `#35` (completed)
Current repository identity: `kinoko34077/devflow`

## 1. Project

User-owned GitHub Project:

- Title: `KiNoTch. Development Control`
- Visibility: Private

The Project is a display layer, not an operational source of truth. Canonical state remains in devflow and the individual repositories.

## 2. Concept-to-Project mapping

| devflow concept | Project field | Kind |
| --- | --- | --- |
| Work Status | Status | built-in Project single-select |
| Type | Work Type | custom single-select |
| Repository | Managed Repository | custom text |

GitHub built-in `Repository` identifies the Issue's owning repository. It may remain visible, but it is not the managed-repository field. Do not use custom field names `Type` or `Repository` for this mapping.

## 3. Fields

### Status — built-in Project field

Use the existing built-in `Status` field for Work Status. Do not create a custom `Work Status` field. Configure exactly:

- NEEDS_AUDIT
- AUDITED
- WORK_ORDER_READY
- READY_FOR_IMPLEMENTATION
- IMPLEMENTING
- AWAITING_REVIEW
- BLOCKED
- NEEDS_REAUDIT
- PARKED
- DONE

### Repository State — custom single-select

- ACTIVE
- PARKED
- MAINTENANCE
- DEPRECATED
- CANCELLED

### Priority — custom single-select

- P0
- P1
- P2
- P3

### Risk — custom single-select

- LOW
- MEDIUM
- HIGH
- CRITICAL

### Work Type — custom single-select

- FEATURE
- BUG
- SPEC
- AUDIT
- REFACTOR
- MAINTENANCE
- RESEARCH
- INFRA
- DOCS

### Text fields

- Managed Repository
- Next Action
- Audit SHA

Do not add a manually maintained `Last Audit` field while its date can be derived from Audit SHA commit metadata.

## 4. Views

### Repository Overview

Table view for Repository Control Issues. Show at least:

- Managed Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Next Action

The built-in `Repository` column may remain visible for Issue ownership, but it is not the managed-repository source.

### Work Queue

Table or board view for active cross-repository work. Show at least:

- Status
- Priority
- Work Type
- Managed Repository
- Risk
- Next Action

## 5. Items and managed scope

The original setup imported devflow Issues `#5` through `#35`; subsequent open canonical devflow Issues are handled by Auto-add and Project synchronization. Exclude `pc-files` and `pc-files2`; they remain outside managed scope.

Historical references may mention the repository's former name `devflow-test`; current operational identity is `kinoko34077/devflow`.

## 6. Project workflows

Only the following workflows are enabled:

1. Auto-add to project: repository `kinoko34077/devflow`, filter `is:issue is:open`.
2. Item closed / Issue closed: set built-in `Status` to `DONE`.

The following remain disabled:

- Auto-close issue
- Auto-add sub-issues
- Pull request linked to issue
- Item added
- Pull request merged
- Auto-archive
- Code changes requested
- Code review approved
- Item reopened

There is no normal Project-to-Issue reverse synchronization. Project automation must not close or otherwise mutate canonical devflow Issues.

## 7. Validation

After any structural Project or repository-identity change, directly re-check the Project name, Private visibility, Status options, custom fields/options, views, workflow states, Auto-add repository/filter, and Issue-closed-to-DONE behavior.

For normal machine-verifiable operation, use `docs/project/PROJECT_SYNC.md`, full `reconcile` / `verify`, and `[SYSTEM] GitHub Project Sync Health`. Repository identity migrations require direct Project-capable verification of Auto-add before acceptance.
