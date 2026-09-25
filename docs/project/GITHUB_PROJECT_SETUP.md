# GitHub Project Setup Handoff

Status: User-admin setup guide
Project role: Derived display / overview layer
Canonical spec: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
Tracking Issue: `#35`

## 1. Create the Project

Create a user-owned GitHub Project with:

- Title: `KiNoTch. Development Control`
- Visibility: Private

The Project is not the operational source of truth. Normal changes are made in devflow and individual repositories, then reflected into the Project.

## 2. Configure fields

### Status — built-in Project field

Use the existing built-in `Status` single-select field to represent the Work Status concept. Do **not** create a second custom `Work Status` field.

Configure the built-in Status options to:

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

### Repository State

Single select:

- ACTIVE
- PARKED
- MAINTENANCE
- DEPRECATED
- CANCELLED

### Priority

Single select:

- P0
- P1
- P2
- P3

### Risk

Single select:

- LOW
- MEDIUM
- HIGH
- CRITICAL

### Type

Single select:

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

- Repository
- Next Action
- Audit SHA

Do not add a manually maintained `Last Audit` field while its date can be derived from Audit SHA commit metadata.

## 3. Create views

### Repository Overview

Table view for Repository Control Issues.

Show at least:

- Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Next Action

Primary items are `[REPO] ...` Repository Control Issues.

### Work Queue

Table or board view for active cross-repository work.

Show at least:

- Status
- Priority
- Type
- Repository
- Risk
- Next Action

Primary items are non-Repository-Control cross-repository Issues in devflow.

Do not require every repository-local Issue / PR to appear in this Project. Repository-local work remains canonical in its own repository and is linked from the Repository Control Issue when it changes the cross-repository state.

## 4. Initial item import

At v0.1 setup time, manually add the currently open devflow Issues `#5` through `#35` to the Project.

Reason: enabling Auto-add does not retroactively add existing matching Issues. Auto-add only adds matching items after they are created or updated.

Expected initial population:

- `#5`–`#34`: 30 Repository Control Issues.
- `#35`: current cross-repository Project setup Issue.
- `pc-files` and `pc-files2`: absent because they intentionally have no Repository Control Issues.

## 5. Built-in workflows

Prefer GitHub Projects built-in workflows before custom Actions.

### Auto-add to project

GitHub Free supports one Auto-add workflow. Use that single workflow for devflow.

Configure:

- Repository: `kinoko34077/devflow-test` until the repository is renamed.
- Filter: `is:issue is:open`

This makes devflow the single Project feeder. New open Repository Control Issues and new open cross-repository Issues will enter the Project automatically without configuring every managed repository separately.

### Issue closed

Enable:

`Issue closed -> built-in Status = DONE`

This is safe because devflow Issue closure represents completion or an explicitly recorded terminal outcome. If an Issue is closed as not planned, preserve that reason in the Issue even if the Project display status is DONE.

### Pull request merged

Enable `PR merged -> Status = DONE` only if Pull Requests are later added as Project items. PR items are not required for v0.1.

### Item added

Do not rely on one universal `Item added -> Status = ...` rule for correctness in v0.1. Repository Control Issues and cross-repository Work Issues can require different current statuses, and devflow remains canonical.

### Auto-archive

Leave automatic archiving off initially. Add it later only if completed items become visual noise.

## 6. v0.1 synchronization boundary

Built-in workflows handle:

- Project membership for newly created/updated open devflow Issues;
- Issue close -> DONE;
- optional PR merge -> DONE.

Built-in workflows do **not** infer arbitrary custom fields such as:

- Repository State;
- Priority;
- Risk;
- Type;
- Repository;
- Next Action;
- Audit SHA.

Do not manually maintain these fields as a second source of truth merely to keep the dashboard perfect.

For v0.1, the Issue itself remains authoritative. Project custom fields may be populated manually where useful, but correctness must not depend on them.

After the Project exists and the actual field names/options have been verified, create a separate Work Order for a one-way GitHub Actions / GraphQL synchronizer if automatic custom-field projection is still useful.

Required Project credentials are configured by the user/admin. Never store credential values in repository files.

## 7. Normal operating rule

```text
individual repository change
    -> repository Issue / PR / CURRENT_STATE as appropriate
    -> update devflow Control Issue only if cross-repository state changed
    -> Project membership/lifecycle follows built-in workflows
    -> future Action may project custom fields from devflow into Project
```

Do not normally edit Project fields first and then back-propagate them into canonical state.

## 8. Validation after manual setup

Verify all of the following:

- Project title is exactly `KiNoTch. Development Control`.
- Visibility is Private.
- Built-in `Status` has the 10 approved Work Status options.
- No duplicate custom `Work Status` field exists.
- Repository State, Priority, Risk and Type option sets match the canonical spec.
- Repository, Next Action and Audit SHA text fields exist.
- `Repository Overview` exists.
- `Work Queue` exists.
- Initial Items include `#5`–`#35`.
- `pc-files` and `pc-files2` are absent.
- One Auto-add workflow targets `kinoko34077/devflow-test` with `is:issue is:open`.
- Issue-closed workflow sets built-in Status to DONE.
- Project remains display-only.
- No credential values are stored in repository files.

After validation, update devflow `#35` with the Project link and observed configuration, then close `#35` only when the Project is usable as the intended display layer.
