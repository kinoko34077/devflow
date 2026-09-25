# GitHub Project Setup Handoff

Status: User-admin setup guide
Project role: Derived display / overview layer
Canonical spec: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
Tracking Issue: `#35`

## 1. Project

Create a user-owned GitHub Project with:

- Title: `KiNoTch. Development Control`
- Visibility: Private

The Project is a display layer, not an operational source of truth. Canonical state remains in devflow and the individual repositories. Do not add a custom field sync Action in v0.1.

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

## 5. Initial items and scope

Add `devflow-test` Issues `#5` through `#35` as initial Project items. Exclude `pc-files` and `pc-files2`; they are outside managed scope.

## 6. v0.1 workflows

Only the following workflows are enabled:

1. Auto-add to project: repository `kinoko34077/devflow-test`, filter `is:issue is:open`.
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

## 7. Validation and handoff

After setup, directly re-check the Project name, Private visibility, all Status options, custom fields and options, both views, initial items, workflow states, Auto-add repository/filter, and Issue-closed-to-DONE behavior. Record the Project URL, final configuration, canonical-document PR, merge commit, and verification result in `devflow-test#35`. Close `#35` only after all requirements pass; otherwise record the GitHub constraint and leave it open.
