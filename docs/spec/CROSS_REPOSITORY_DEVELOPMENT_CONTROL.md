# KiNoTch. Cross-Repository Development Control

Status: Canonical specification
Approved: 2026-09-25
Owner repository: `kinoko34077/devflow-test` (planned operational name: `devflow`)
Tracking issue: `devflow-test#35`

## 1. Purpose and authority

This specification defines a low-overhead GitHub-native control plane for cross-repository development. It must make repository state, active work, priority, risk, audit SHA, and next action discoverable without relying on chat history.

The canonical source of truth is devflow and the individual repositories:

- devflow owns Repository Control Issues, cross-repository work Issues, workflow definitions, and this specification.
- Each individual repository owns its implementation, repository-local Issues/PRs, and detailed current state.
- The GitHub Project `KiNoTch. Development Control` is a display and overview layer only.

Project changes must not be treated as a second operational source of truth. No Project-to-Issue reverse synchronization or custom-field synchronization Action is part of v0.1. Project custom-field values may remain empty until a later, separately approved work order.

## 2. Repository Control Issues

Use one open Repository Control Issue per managed repository. Its canonical content includes:

- Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Active Work
- Next Action
- Detailed Current State

The managed-repository scope excludes `pc-files` and `pc-files2`. They must not be added as Project items or represented as managed repositories in this v0.1 setup.

## 3. Work and repository state vocabulary

### 3.1 Work Status

The work-status concept is represented by the GitHub Project built-in single-select field `Status`. Do not create a custom `Work Status` field. The exact ten options are:

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

### 3.2 Repository State

Custom single-select options:

- ACTIVE
- PARKED
- MAINTENANCE
- DEPRECATED
- CANCELLED

### 3.3 Priority and Risk

Custom single-select options:

- Priority: P0, P1, P2, P3
- Risk: LOW, MEDIUM, HIGH, CRITICAL

### 3.4 Work Type

The devflow concept `Type` is displayed in the Project as the custom single-select field `Work Type`. Its exact options are:

- FEATURE
- BUG
- SPEC
- AUDIT
- REFACTOR
- MAINTENANCE
- RESEARCH
- INFRA
- DOCS

### 3.5 Project field mapping

| devflow concept | Project field | Kind |
| --- | --- | --- |
| Work Status | Status | GitHub built-in single-select |
| Type | Work Type | Custom single-select |
| Repository | Managed Repository | Custom text |

The GitHub built-in `Repository` field identifies the Issue's owning repository. It may remain visible, but it is not the managed-repository field and must not be used as a substitute for `Managed Repository`.

Custom text fields required by v0.1 are:

- Managed Repository
- Next Action
- Audit SHA

Do not retain `Type` or `Repository` as the current names of custom Project fields for these concepts.

## 4. GitHub Project configuration

Create a user-owned, Private Project:

- Title: `KiNoTch. Development Control`
- URL: `https://github.com/users/kinoko34077/projects/1`
- Project is display-only; devflow and repository files remain authoritative.

### 4.1 Views

Create and maintain these views:

#### Repository Overview

A table view for Repository Control Issues. It must show at least:

- Managed Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Next Action

The built-in Repository column may remain for Issue ownership.

#### Work Queue

A table or board view for active cross-repository work. It must show at least:

- Status
- Priority
- Work Type
- Managed Repository
- Risk
- Next Action

### 4.2 Initial items

Add devflow Issues #5 through #35 as the initial Project items. Existing matching Issues are added manually because Auto-add is not a retroactive import mechanism. Do not add pc-files or pc-files2.

## 5. v0.1 Project workflows

Only the following workflows are enabled:

1. Auto-add: repository `kinoko34077/devflow-test`, filter `is:issue is:open`.
2. Item closed / Issue closed: set the built-in `Status` field to `DONE`.

The following workflows remain disabled:

- Auto-close issue
- Auto-add sub-issues
- Pull request linked to issue
- Item added
- Pull request merged
- Auto-archive
- Code changes requested
- Code review approved
- Item reopened

Auto-archive is intentionally not enabled in v0.1. Project automation must not close, edit, or otherwise mutate canonical devflow Issues in the reverse direction.

## 6. Operating lifecycle

The normal boundary is:

1. Audit the repository and record the audit SHA in the Repository Control Issue.
2. Prepare a work order with objective, scope, acceptance criteria, non-goals, verification, audit base, and related specifications.
3. Implement on a dedicated branch in the affected repository.
4. Verify the change, open a PR, and perform a re-audit before merge.
5. Update canonical repository/devflow state and let the Project reflect only its display role.

A document or operating-definition change follows Issue -> dedicated branch -> verification -> PR -> re-audit -> merge. If a GitHub limitation prevents a required setting, record the requirement, actual limitation, and alternative in tracking Issue #35 and leave it open.

## 7. Validation and handoff

After any Project setup change, directly re-check the live Project rather than relying on prior reports:

- title and Private visibility;
- exactly the ten built-in Status options and no custom Work Status;
- all custom fields and exact select options;
- both view names and required columns;
- initial items #5-#35 and absence of pc-files/pc-files2;
- enabled/disabled workflows, Auto-add repository/filter, and Issue-closed -> DONE;
- absence of Project-to-Issue reverse synchronization and custom-field sync Actions.

Record the Project URL, final fields, views, workflow states, canonical-document PR, merge commit, and verification result in devflow-test#35. Close #35 only after every requirement passes; otherwise document the GitHub constraint and keep it open.
