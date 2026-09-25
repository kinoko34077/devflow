# GitHub Project Setup Handoff

Status: User-admin setup guide
Project role: Derived display / overview layer
Canonical spec: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`

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

This is required so GitHub Projects built-in workflows such as item-added, Issue-closed and PR-merged can update the same status field used by this control system.

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

Do not add a manually maintained `Last Audit` field unless a later requirement cannot derive the date from Audit SHA commit metadata.

## 3. Views

### Repository Overview

Table view for Repository Control Issues.

Show at least:

- Repository
- Repository State
- Priority
- Risk
- Audit SHA
- Next Action

### Work Queue

Table or board view for active cross-repository work.

Show at least:

- Status
- Priority
- Type
- Repository
- Risk
- Next Action

## 4. Items to display

Primary Project items are:

- `[REPO] ...` Repository Control Issues from devflow;
- cross-repository operational Issues from devflow.

Do not require every Issue / PR from every managed repository to be copied into this Project. Repository-local work remains canonical in the repository and is linked from its Control Issue when it materially affects the cross-repository state.

## 5. Built-in Project workflows

GitHub Projects currently provides built-in workflows that update the built-in `Status` field for common events. Prefer these before adding custom Actions.

Configure as applicable:

1. Item added to Project -> set built-in Status to the desired initial state.
2. Issue closed -> set built-in Status to DONE.
3. Pull request merged -> set built-in Status to DONE when PR items are used.
4. Auto-archive completed items only when old completed work becomes visual noise.
5. Auto-add devflow items if it reduces manual Project maintenance.

Auto-add only affects matching items when they are created or updated after the workflow is enabled; existing matching items may need an initial manual add/import.

## 6. Auto-add strategy

Use devflow as the primary Project feeder rather than configuring one workflow per managed repository.

Preferred target:

- Repository: the operational devflow repository (`devflow-test` until renamed)
- Items: Repository Control Issues and cross-repository operational Issues

If filtering is needed, introduce a stable machine-readable convention such as labels only after the label vocabulary is explicitly defined. Do not make Project correctness depend on labels that do not yet exist.

## 7. Custom-field synchronization

Built-in workflows do not infer arbitrary custom fields such as Risk, Repository State, Audit SHA or free-text Next Action from repository semantics.

If manual Project field maintenance becomes burdensome, add a GitHub Actions synchronization workflow that:

1. reads the canonical devflow Issue state;
2. resolves the target Project and field IDs through the GitHub GraphQL API;
3. updates the corresponding Project item fields;
4. runs only from canonical state toward the Project.

Required authentication must be configured by the user/admin. Do not store tokens, secrets or credential values in repository files.

The exact synchronization workflow is a later implementation phase after the Project exists and its field names are confirmed.

## 8. Normal operating rule

Normal operation:

```text
individual repository change
    -> repository Issue / PR / CURRENT_STATE as appropriate
    -> update devflow Control Issue only if cross-repository state changed
    -> Project updates through built-in workflow / future Action
```

Do not normally edit Project fields first and then attempt to back-propagate them into canonical state.

## 9. Validation after manual setup

After setup, verify:

- Project title is exactly `KiNoTch. Development Control`;
- visibility is Private;
- the built-in `Status` field has the 10 approved Work Status options;
- no duplicate custom `Work Status` field exists;
- all other required fields and options exist;
- `Repository Overview` exists;
- `Work Queue` exists;
- `pc-files` and `pc-files2` are not represented by Repository Control Issues;
- Project workflows do not create a second source of truth;
- no credentials are stored in repository files.
