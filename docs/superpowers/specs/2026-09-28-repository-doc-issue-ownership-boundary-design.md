# Repository Document / Issue Ownership Boundary Design

**Status:** Design for review

**Source:** User decision on 2026-09-28 to re-evaluate repository-local documents versus GitHub Issues now that Issue-based development is available.

**Related authority:**
- standing Issue-first policy: #49
- drift audit / finding J: #131
- `AGENTS.md`
- `docs/operations/REPOSITORY_ISSUE_MANUAL.md`

## Goal

Prevent repository documents from becoming a second chronological task/history database while preserving durable repository canon.

The intended model is:

- repository documents own durable desired behavior, architecture, accepted constraints, and concise current repository-level state;
- Issues / Work Orders own bounded task scope, progress, findings, blockers, acceptance, handoff, and task-level decision history;
- Git / PR / Review / Actions own concrete implementation chronology and verification evidence;
- ADR / CHANGELOG are used only when durable rationale or release-facing history has independent long-term value.

## Problem

Managed repositories historically placed most development information directly into repository files because Issue-based workflow was not yet part of the operating model.

That produces mixed-layer documents containing current state, task progress, commit/test chronology, old checkpoints, and durable specification in one place. Once Issues, PRs and Actions also record the same work, those repository files become a second manually maintained history database.

Observed failure mode:

```text
implementation advances
-> Issue / PR / Git becomes current
-> CURRENT_STATE or another repository document still contains prior checkpoint
-> several summaries now disagree
-> resume/audit must reconcile duplicated chronology before work can continue
```

Audit #131 already records this as `mixed-layer history accumulation` and recommends concise accepted state plus durable references while Issues/PRs/Actions own detailed history.

## Ownership model

### Repository specification / design documents

Own:
- durable desired behavior;
- contracts and invariants;
- architecture and accepted constraints;
- currently applicable design semantics.

Do not own:
- task progress;
- per-commit chronology;
- temporary blockers;
- copied CI logs;
- session handoff history.

Question: **What should the repository permanently do?**

### Repository Current State

Own:
- concise currently accepted repository-level technical state;
- supported environment/integration facts;
- durable active limitations useful beyond one task;
- compact references to the Issue/PR/evidence that established the accepted state.

Do not own:
- chronological implementation diary;
- every commit SHA ever accepted;
- every test rerun;
- `3/5 items complete` task progress;
- temporary branch/reviewer/session state.

Question: **What is currently true of the repository independent of one bounded task?**

When accepted state advances, stale projections are replaced rather than preserved as another appended historical checkpoint.

### Repository-local Issue / Work Order

Own:
- one bounded objective/problem;
- scope / non-goals / acceptance criteria;
- durable task findings and dispositions;
- blocker / next action;
- implementation/review handoff;
- task-level rationale that matters until and after completion;
- references to branch, PR, commits, checks and follow-up Issues.

Question: **What belongs to this one finite change, defect, investigation, blocker or follow-up?**

### Execution Session Record

Own only short-lived worker/session execution coordination:
- scope;
- latest checkpoint;
- next action;
- blocker;
- branch/PR;
- handoff/release state.

It is not durable task truth and not a command transcript.

### Git / Pull Request / Review / Actions

Own:
- actual code/document diff chronology;
- exact commit history;
- one concrete change boundary;
- exact-SHA review evidence;
- test / CI execution evidence.

Repository documents must not reconstruct a second chronological commit/test/PR log from these systems.

### ADR

Own durable architectural/design rationale only when the reason remains useful after the original task is closed.

Routine progress history is not an ADR.

### CHANGELOG

Own release/user-facing changes when the repository actually needs a release history surface.

It is not a development task log.

### devflow Repository Control

Own only cross-repository summary/index state: accepted Audit SHA, Work Status, Repository State, Active Work, Next Action, entry points and readiness.

It must not copy repository-local implementation chronology.

## Chronological history rule

Git, PRs, Reviews, Actions and Issues already preserve implementation chronology. Therefore:

1. `CURRENT_STATE`, specifications and design documents must not maintain a second chronological commit/test/PR history.
2. Current-state documents store only the currently accepted projection plus compact evidence references.
3. When current state changes, stale projections are replaced or retired instead of accumulating as an append-only timeline.
4. Historical implementation evidence remains available through Git, closed Issues, PRs, Reviews and Actions.
5. ADR or CHANGELOG retains history only where that history has a distinct durable responsibility.
6. Full canonical content is not copied across surfaces; link or compactly summarize instead.

## Promotion / retirement flow

A task begins in an Issue / Work Order.

At completion:

```text
Issue result
├─ temporary/task-only result -> stays in Issue history
├─ accepted repository-level current state changed -> replace/update CURRENT_STATE
├─ durable requirement/design changed -> update repository specification/design
├─ durable architectural rationale matters -> add/update ADR
├─ release/user-facing change matters -> CHANGELOG if used
└─ concrete diff/test/review evidence -> remains Git/PR/Review/Actions
```

A closed Issue must not remain the only owner of a still-active permanent requirement. Conversely, a repository specification must not retain obsolete task-progress text merely because it was historically true.

## Proposed devflow changes

After this design is accepted:

1. Update `docs/operations/REPOSITORY_ISSUE_MANUAL.md` to make the chronological-history rule explicit and add the promotion/retirement rule where it is not already explicit.
2. Tighten `AGENTS.md` wording so Current State updates occur when accepted repository-level state changes, not for every implementation checkpoint.
3. Update standing policy #49 with a compact reference/rule stating that Issues are the task-history surface and repository Current State is not an append-only implementation log.
4. Add focused documentation regression checks only if existing tests already validate these manuals/entrypoint semantics; do not invent a new test framework solely for prose.
5. Do not rewrite historical repository documents in the same change. Cleanup of existing mixed-history documents is separate bounded work after the policy is accepted.

## dev_agent follow-up

`dev_agent/AGENTS.md` currently says:

> Update the owning Current State/traceability document when implementation evidence changes.

That wording can be read as requiring Current State mutation for every checkpoint. A repository-local follow-up should change the intent to:

- update Current State when accepted repository-level state changes;
- keep task progress and implementation chronology in the owning Issue / PR / Actions;
- replace stale Current State projections and reference evidence compactly;
- do not duplicate a running chronological history.

This is a separate repository-local change linked from the devflow policy Work Order/Issue so cross-repository authority and local entrypoint changes remain independently reviewable.

## Non-goals

- no deletion of Git history, Issues, PRs, Reviews or Actions;
- no migration of every historical document in one pass;
- no replacement of durable specifications with Issues;
- no requirement that every trivial change have a separate Issue when repository policy permits PR-only handling;
- no change to protected Gate, credentials, permissions, deployment or release behavior;
- no change to execution-coordinator runtime semantics;
- no duplication of #125/#132 durable-candidate work.

## Acceptance criteria

- one clear decision test distinguishes repository canon/current state from task history;
- chronological commit/test/PR history is explicitly prohibited from accumulating in Current State/spec/design docs;
- Issue/PR/Git/CI responsibilities remain distinct;
- promotion from task result to durable spec/current state/ADR is explicit;
- existing devflow ownership model is clarified rather than replaced;
- dev_agent ambiguous Delivery wording is routed to a separate local change;
- existing historical cleanup remains follow-up work rather than being bundled into the policy change.
