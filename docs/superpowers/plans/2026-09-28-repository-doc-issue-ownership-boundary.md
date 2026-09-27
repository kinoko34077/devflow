# Repository Document / Issue Ownership Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing devflow ownership model explicitly prohibit duplicate chronological implementation history in repository Current State/spec/design documents while preserving durable repository canon and Issue-first task history.

**Architecture:** Clarify the existing ownership boundaries rather than introducing a new tracking system. `REPOSITORY_ISSUE_MANUAL.md` remains the operational owner of surface responsibilities, `AGENTS.md` remains the bootstrap/entrypoint, and standing policy #49 receives only the compact policy statement needed for durable agent behavior.

**Tech Stack:** Markdown operational documentation, GitHub Issues/PRs, existing devflow verification workflow.

**Spec:** `docs/superpowers/specs/2026-09-28-repository-doc-issue-ownership-boundary-design.md`

## Global Constraints

- Do not replace durable repository specifications with Issues.
- Do not make `CURRENT_STATE` a second Issue tracker or chronological implementation diary.
- Git / PR / Review / Actions remain the owners of concrete implementation chronology and verification evidence.
- Issues / Work Orders remain the owners of bounded task scope, progress, findings, blockers, handoff and task-level rationale.
- Current State stores only concise currently accepted repository-level state plus compact evidence references.
- When current state advances, stale projections are replaced or retired rather than appended as historical checkpoints.
- ADR / CHANGELOG retain history only when that history has an independent durable responsibility.
- Do not rewrite historical repository documents in this policy change.
- Do not change runtime semantics, Gate state, credentials, permissions, deployment, release, Project authority direction or execution-coordinator behavior.

## Review Focus

- Wording must not imply that every commit/test result requires a Current State edit.
- Wording must not imply that Issues become the permanent source of desired behavior/specification.
- Current State must still allow durable repository-level limitations and current integration/environment facts.
- References/summaries across surfaces must not become full duplicated canonical copies.
- Existing manual/session/PR/Review ownership semantics must remain intact.

---

### Task 1: Clarify repository-local information ownership

**Files:**
- Modify: `docs/operations/REPOSITORY_ISSUE_MANUAL.md`

**Interfaces:**
- Consumes: ownership table and decision test already present in `REPOSITORY_ISSUE_MANUAL.md`.
- Produces: explicit chronological-history prohibition and promotion/retirement rules used by agents and later repository-local policies.

- [ ] **Step 1: Re-read the live manual before editing**

Confirm the ownership table still distinguishes specification/design, Current State, Issue/Work Order, Session Record, PR, Review, tests/CI, ADR and devflow Control.

- [ ] **Step 2: Add the chronological-history rule**

Add compact normative wording stating that:
- Git/PR/Review/Actions/Issues already preserve implementation chronology;
- `CURRENT_STATE`, specifications and design docs must not reconstruct a second chronological commit/test/PR log;
- Current State keeps only the currently accepted projection plus compact evidence references;
- stale projections are replaced/retired when accepted state advances.

- [ ] **Step 3: Add the promotion/retirement flow**

Document the task-result routing:
- task-only result -> remains Issue history;
- accepted repository-level current state -> update/replace Current State;
- durable requirement/design -> update specification/design;
- durable rationale -> ADR;
- release/user-facing history -> CHANGELOG when used;
- concrete diff/test/review evidence -> Git/PR/Review/Actions.

- [ ] **Step 4: Verify ownership invariants textually**

Check that the manual still states that `CURRENT_STATE` is not a second Issue tracker and that durable accepted requirements must not remain only in closed Issues.

- [ ] **Step 5: Commit Task 1**

Commit only the manual clarification with a docs-scoped message.

### Task 2: Tighten the devflow bootstrap rule

**Files:**
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: Task 1 ownership semantics.
- Produces: bootstrap guidance preventing agents from duplicating task chronology into Current State.

- [ ] **Step 1: Re-read the current `AGENTS.md` lifecycle and update rules**

Confirm the existing lifecycle still updates repository-local canon/current state only where owned information changed and keeps detailed session/commit/test data out of devflow Control.

- [ ] **Step 2: Add one compact Current State boundary rule**

State that repository Current State is updated when accepted repository-level current state changes, not for every implementation checkpoint. Task progress/chronology stays in the owning Issue/PR/Actions, and stale Current State projections are replaced rather than accumulated.

- [ ] **Step 3: Verify no workflow authority is changed**

Confirm the edit does not change session lifecycle, merge/review gates, safety boundaries, Project authority, or runtime coordination.

- [ ] **Step 4: Commit Task 2**

Commit the bootstrap clarification separately.

### Task 3: Update standing Issue-first policy

**Surface:**
- Update: devflow Issue #49 body

**Interfaces:**
- Consumes: accepted Task 1/2 wording after PR merge.
- Produces: compact durable policy reference for future agents.

- [ ] **Step 1: Re-read live Issue #49 before mutation**

Confirm it remains the standing Issue-first operational policy and has not been superseded.

- [ ] **Step 2: Add the compact ownership rule**

Add a short section stating:
- Issue/Work Order is the task-history/handoff surface;
- Current State is the current accepted repository-level projection, not an append-only implementation log;
- Git/PR/Review/Actions own implementation chronology and verification evidence;
- durable requirements/design decisions are promoted into repository canon when accepted.

- [ ] **Step 3: Do not copy the full manual into #49**

Link/reference `REPOSITORY_ISSUE_MANUAL.md` rather than duplicating its complete ownership table.

### Task 4: Verify, review and merge the devflow policy change

**Files/Surfaces:**
- `docs/operations/REPOSITORY_ISSUE_MANUAL.md`
- `AGENTS.md`
- design + plan documents on the branch
- Issue #49 after merge

- [ ] **Step 1: Run repository regression**

Run the existing devflow test suite used by current PRs:
`python -m unittest discover -s tests -v`

Expected: PASS with no policy/template/project-sync regression.

- [ ] **Step 2: Run diff hygiene**

Run `git diff --check` and inspect the branch diff to confirm no unrelated files, runtime code, candidate-source work, Project mutation or protected operation is bundled.

- [ ] **Step 3: Open/update PR with exact scope and provenance**

PR must reference #49 and #131, identify the design/plan, and state that historical cleanup is deferred.

- [ ] **Step 4: Formal Review and required CI on exact head**

Use the repository's normal formal review/readiness process and verify the required `verify` check on the exact PR head.

- [ ] **Step 5: Merge only after exact-head evidence is green**

Use a normal merge/revertible path; do not rewrite shared history.

- [ ] **Step 6: Update Issue #49 after merge**

Apply Task 3 only after the file-based policy is accepted so the Issue references accepted canon rather than proposed wording.

- [ ] **Step 7: Route local repository follow-ups separately**

Create/reuse bounded repository-local Issues for repositories whose local entrypoints conflict with the new common rule. `dev_agent/AGENTS.md` is the first known follow-up; historical Current State cleanup is a separate later task.
