# Cross-Repository Current State Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `devflow-test` into the operational cross-repository Current State Hub while keeping GitHub Project as a derived display layer and repository-local details in each repository.

**Architecture:** `devflow` owns Repository Control Issues and cross-repository operational Issues. Individual repositories remain canonical for repository-specific technical state. GitHub Project consumes devflow state as a display layer through built-in workflows first and GitHub Actions later where custom-field synchronization is required.

**Tech Stack:** GitHub Issues, Pull Requests, repository Markdown/YAML, GitHub Projects built-in workflows, future GitHub Actions + GraphQL synchronization.

**Spec:** `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`

## Global Constraints

- GitHub Project is a display layer, not the operational source of truth.
- devflow is the cross-repository Current State source of truth.
- Individual repositories remain canonical for repository-specific specs, current technical state, Issues, PRs and code.
- Do not duplicate per-Issue live state into repository files.
- Do not duplicate detailed repository CURRENT_STATE into devflow.
- Exclude `pc-files` and `pc-files2` from managed repositories.
- Do not introduce periodic FULL audits, bulk Repository Base adoption or bulk Base synchronization.
- All repository file changes use a dedicated branch and Pull Request.
- Project administration / credential setup remains a user-controlled follow-up.

## Review Focus

1. Existing `devflow-test` E2E semantics must remain compatible with the new cross-repository workflow.
2. Repository State and Work Status must stay separate and unambiguous.
3. Repository Control Issues must remain indexes, not become duplicated repository specifications.
4. Exactly 30 managed repositories must receive one Control Issue; backup repositories must remain absent.
5. GitHub Project must remain optional for execution environments that cannot read Projects.

---

### Task 1: Make the repository self-describing as the cross-repository hub

**Files:**
- Modify: `README.md`
- Modify: `.devflow/WORKFLOW.yaml`
- Create: `.github/ISSUE_TEMPLATE/repository-control.md`
- Create: `docs/project/GITHUB_PROJECT_SETUP.md`

**Interfaces:**
- Consumes: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
- Produces: agent read order, machine-readable workflow vocabulary, Repository Control Issue shape, and the user-facing Project setup contract.

- [ ] **Step 1: Update README entry guidance**

Required README structure:

```markdown
## Cross-repository role

This repository is the cross-repository Current State Hub.

Read order:
1. `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
2. `.devflow/WORKFLOW.yaml`
3. relevant open Repository Control / cross-repository Issues
4. target repository CURRENT_STATE / Issues / PRs / specs

GitHub Project is a derived display layer. If Project access is unavailable, start from this repository and continue.
```

Preserve the existing GitHub-native / implementer-agnostic explanation and existing E2E history.

- [ ] **Step 2: Extend `.devflow/WORKFLOW.yaml`**

The file must define at least:

```yaml
schema_version: 2
repository: kinoko34077/devflow-test

canonical_operational_state:
  issues: true
  pull_requests: true
  repository_control_issues: true
  github_project_is_display_only: true
  repository_files_duplicate_issue_state: false

workflow:
  work_states:
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
  repository_states:
    - ACTIVE
    - PARKED
    - MAINTENANCE
    - DEPRECATED
    - CANCELLED
  priorities: [P0, P1, P2, P3]
  risks: [LOW, MEDIUM, HIGH, CRITICAL]
  types:
    - FEATURE
    - BUG
    - SPEC
    - AUDIT
    - REFACTOR
    - MAINTENANCE
    - RESEARCH
    - INFRA
    - DOCS
  next_action_tags:
    - AUDIT
    - SPECIFY
    - IMPLEMENT
    - VERIFY
    - REVIEW
    - MERGE
    - RELEASE
    - USER_DECISION
    - WAIT
    - NONE

repository_control:
  one_open_issue_per_managed_repository: true
  excluded_repositories:
    - pc-files
    - pc-files2
  required_fields:
    - repository
    - repository_state
    - priority
    - risk
    - audit_sha
    - active_work
    - next_action
    - detailed_current_state

review_boundary: pull_request
implementation_actor: unrestricted
```

Retain the existing required Work Order fields.

- [ ] **Step 3: Add Repository Control Issue template**

Create `.github/ISSUE_TEMPLATE/repository-control.md` with this body shape:

```markdown
---
name: Repository Control
about: Cross-repository current-state record for one managed repository
title: "[REPO] "
---

## Repository

`kinoko34077/<repository>`

## Repository State

`ACTIVE`

## Priority

`P2`

## Risk

`LOW`

## Audit SHA

`UNSET`

## Active Work

None.

## Next Action

`Initial STANDARD audit [AUDIT]`

## Detailed Current State

`<repository CURRENT_STATE / equivalent reference>`

## Control Notes

Keep this Issue as a cross-repository index. Do not copy detailed repository specifications or implementation history here.
```

- [ ] **Step 4: Add Project setup handoff document**

Create `docs/project/GITHUB_PROJECT_SETUP.md` containing:

- exact Project title: `KiNoTch. Development Control`;
- visibility: Private;
- Project fields and option sets from the spec;
- `Repository Overview` and `Work Queue` views;
- built-in workflow recommendations;
- rule that Project is display-only;
- note that future custom-field sync may use GitHub Actions after user configures required Project permissions/credentials;
- no credential values in repository files.

- [ ] **Step 5: Verify Task 1**

Checks:

```text
README references the spec and devflow-first fallback.
WORKFLOW contains all 10 Work Status values and all 5 Repository State values.
WORKFLOW excludes pc-files and pc-files2.
Repository Control template contains all 8 required fields.
Project setup document names both required views and says Project is display-only.
```

Expected: all checks pass by direct file re-read.

- [ ] **Step 6: Commit Task 1**

Commit message:

```text
feat: establish cross-repository devflow hub
```

---

### Task 2: Initialize Repository Control Issues

**Files:**
- No repository file changes.
- GitHub Issues in `kinoko34077/devflow-test`.

**Interfaces:**
- Consumes: Repository Control schema from Task 1.
- Produces: exactly one open Control Issue for each of the 30 managed repositories.

- [ ] **Step 1: Create the 30 Control Issues**

Create `[REPO] <name>` Issues for:

```text
.ai-guidelines
2bit-cell-automaton
Structured-Cell-Automaton
Gomoku-5D
IDS-Composit
Mapience-prototype
Micro-Chordbot
SynTrail-LM
colony-ai
cora_engine
dev_agent
devflow-test
jev-audit
kinotch-api
kinotch-default-canary
kinotch-repository-base
kinotch-runtime
kotonomani
line-style-viewer
lyric_reader_page
memory-game
microtone-piano
obsidian-related-notes-view
refil-viewer
srt2subtitle
stackedit.io
standby-display
testapp
txt-auto-replace
weather-widget
```

Initial values unless a currently verified state justifies something more specific:

```text
Repository State: ACTIVE
Priority: P2
Risk: LOW
Audit SHA: UNSET
Active Work: None
Next Action: Initial STANDARD audit [AUDIT]
```

Do not invent repository-specific technical state during initialization.

- [ ] **Step 2: Verify issue cardinality and exclusions**

Search open Issues in devflow.

Expected:

```text
30 titles beginning with [REPO]
0 [REPO] pc-files
0 [REPO] pc-files2
no duplicate repository names
```

- [ ] **Step 3: Correct only verified initialization mistakes**

If duplicates or omissions exist, close/correct the mistaken Control Issue and re-run the cardinality check. Do not infer more detailed state merely to fill fields.

---

### Task 3: Re-home cross-repository operational tracking

**Files:**
- No mandatory repository file changes.
- GitHub Issues in devflow and existing source repositories.

**Interfaces:**
- Consumes: cross-repository issue ownership rule from the spec.
- Produces: devflow tracking Issues for active cross-repository work while preserving historical source Issues.

- [ ] **Step 1: Create a devflow tracking Issue for GitHub Project construction**

Reference, but do not delete or rewrite, the existing historical Issue in `kinotch-repository-base`.

Required current state:

```text
Type: INFRA
Work Status: BLOCKED or READY_FOR_IMPLEMENTATION according to remaining user-side Project setup
Next Action: user performs Project setup from docs/project/GITHUB_PROJECT_SETUP.md [USER_DECISION]
```

- [ ] **Step 2: Create a devflow tracking Issue for PR-only protection audit**

Reference the existing historical `kinotch-repository-base` Issue.

Required current state:

```text
Type: AUDIT / INFRA
Priority: P1
Next Action: continue read-only protection inventory, then apply supported settings only through an authorized administration path [AUDIT]
```

- [ ] **Step 3: Verify history preservation**

Expected:

- old source Issues remain available as history;
- new devflow Issues link back to them;
- future cross-repository progress is updated in devflow rather than split across unrelated repositories.

---

### Task 4: Review, PR, and handoff

**Files:**
- All branch changes from Tasks 1 and the already-approved specification.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: reviewable implementation PR and a clear post-merge next action.

- [ ] **Step 1: Compare branch against main**

Expected changed repository files:

```text
docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md
docs/superpowers/plans/2026-09-25-cross-repository-current-state-hub.md
README.md
.devflow/WORKFLOW.yaml
.github/ISSUE_TEMPLATE/repository-control.md
docs/project/GITHUB_PROJECT_SETUP.md
```

No unrelated code changes.

- [ ] **Step 2: Re-read all changed files against Work Order #4**

Expected: every acceptance criterion is either satisfied or explicitly identified as post-merge/user-admin work.

- [ ] **Step 3: Open Pull Request**

Title:

```text
Promote devflow into cross-repository Current State Hub
```

PR body must reference `#4`, summarize the three-layer architecture, list verification results, and explicitly state that GitHub Project remains display-only.

- [ ] **Step 4: Re-audit PR**

Check:

- no duplicated live task table was added to repository files;
- Control Issues are indexes rather than repository specs;
- backup repositories remain excluded;
- Project administration remains separated from operational state;
- no credential or secret material is present.

- [ ] **Step 5: Stop before merge**

Set Work Order #4 to `AWAITING_REVIEW` / verified equivalent and set:

```text
Next Action: PRをmerge [MERGE]
```

Merge remains user-confirmed.
