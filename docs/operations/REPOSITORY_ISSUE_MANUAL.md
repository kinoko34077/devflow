# Repository-Local Issue / Work Order Manual

Status: Operational manual
Cross-repository authority: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`

This manual defines how Issues are used inside managed repositories and how those records relate to devflow.

## 1. Three different records

### A. devflow Repository Control Issue

Title: `[REPO] <repository>`

Purpose: long-lived cross-repository index/current-state summary.

Contains only information needed to answer:
- Is this repository active/blocked/parked/etc.?
- What accepted SHA was last audited?
- What important work is active?
- What is the next cross-repository action?
- Where are the repository-local canonical entry points?

Do not use it as a detailed bug/feature discussion thread.

### B. devflow cross-repository Work Order

Purpose: one coordinated operation whose acceptance spans multiple repositories or changes devflow/control-plane behavior.

Examples:
- changing shared audit/merge rules;
- changing Project synchronization;
- coordinated migration across several repositories;
- repository rename that requires devflow + Base + Project migration.

### C. repository-local Issue / Work Order

Purpose: detailed durable record for a task/finding owned by one repository.

Examples:
- bug or security finding;
- feature implementation;
- refactor with explicit acceptance criteria;
- repository-local specification change;
- build/deploy/tooling problem;
- investigation whose result changes local code/specs.

## 2. When to create a repository-local Issue

Create or reuse one when at least one applies:
- work is likely to span more than one commit/session;
- acceptance criteria need to survive agent/chat handoff;
- a P0/P1 finding exists;
- the task is blocked or awaits a user decision;
- multiple files/subsystems are affected and scope needs to remain fixed;
- another Issue/PR depends on the outcome;
- the decision or verification history will matter after merge.

A new Issue is optional for a truly trivial, low-risk, single-PR change when the PR itself can unambiguously contain scope, verification and rationale and local repository policy does not require an Issue.

Before creating a new Issue, search open Issues and current `Active Work` to avoid duplicates.

## 3. Minimum local Work Order content

Use the repository's own template when present. Otherwise include, at minimum:

- **Source / reason** — request, finding, prior Issue or decision;
- **Objective / problem** — outcome to achieve, not only implementation method;
- **Scope** — what is included;
- **Acceptance criteria** — observable completion conditions;
- **Non-goals** — when omission would otherwise be ambiguous;
- **Verification** — tests, regression, smoke/real-entry checks;
- **Audit/base SHA** — inspected base when code/spec change depends on it;
- **Related specs / decisions** — repository-local canonical references;
- **Implementation references** — branch/PR when created;
- **Current blocker / next action** — when unfinished.

Repository-local naming does not have to be exactly `Work Order:`. Information ownership matters more than identical labels.

## 4. Issue lifecycle

### Before implementation

- establish current base SHA;
- read relevant local canon/tests;
- create/reuse Issue if durable tracking criteria apply;
- fix Objective/Scope/Acceptance criteria before broad implementation;
- link cross-repository Work Order when the local task is a child of one.

### During implementation

Update the local Issue when:
- scope materially changes;
- a new blocker appears;
- an acceptance criterion changes;
- an important P0/P1 finding is discovered;
- branch/PR reference becomes available;
- user decision changes the task boundary.

Do not append every implementation step or command transcript. Commits/PR/CI own that evidence.

### At PR creation

The PR should identify:
- owning local Issue/Work Order;
- affected spec/current-state documents;
- verification commands/results;
- known limitations or explicitly deferred findings;
- rollback note when failure impact warrants it;
- implementer provenance when the PR is agent-produced or mixed-agent work.

Use the repository PR template when present. Keep the PR compact: do not copy the full Issue body or move long-term Current State into the PR. Implementer provenance belongs in the PR body; reviewer provenance does not.

### At formal review

For non-trivial PRs, submit a formal GitHub Pull Request Review according to the lifecycle and Review Provenance v1 defined in `AGENT_OPERATING_MANUAL.md`.

- `self-review` and `independent-review` are different evidence and must be labeled accurately.
- Review evidence is tied to the exact `Reviewed-Commit` SHA; a later push requires explicit re-review of the new head for merge-readiness.
- `REQUEST_CHANGES` findings stay blocking until addressed or explicitly dispositioned and followed by a fresh Review.
- Diff-local findings belong in inline review comments/threads; task-level blocker, acceptance change, deferral, or Current State belongs in the owning Issue.
- When multiple agent surfaces share one GitHub actor, native approval count does not prove agent independence; preserve system/model/role attribution in Review Provenance and use CI/status/provenance policy where enforcement is required.

At handoff, the owning Issue should let the next reviewer recover the current PR/head, latest formal Review, unresolved findings/threads, and current CI/check state without depending on chat history.

### At completion

Close the local Issue only when its own acceptance criteria are satisfied or it is explicitly cancelled/not planned.

Before closing:
- verify merged/default-branch outcome when merge is part of acceptance;
- record the accepted PR/commit;
- record unresolved follow-up as a separate Issue if it remains durable work;
- update local Current State/spec only where owned information changed;
- update devflow Control Issue if its cross-repository summary changed.

Do not leave a closed Issue as the only place containing a still-active next action.

## 5. Relationship to devflow Control

The Control Issue should reference active local work concisely, for example:

`Active Work: repo#123 — parser regression fix; PR #124 awaiting review`

When the local task finishes, replace stale active references with the actual current state and Next Action. Do not copy the entire Issue body into devflow.

Update the Control Issue when the local task changes:
- accepted Audit SHA;
- Work Status;
- Repository State;
- Priority/Risk;
- Active Work;
- Next Action;
- canonical entry points;
- cross-repository readiness.

No Control update is required solely because:
- a commit was added to the same active branch;
- a test was rerun with the same outcome;
- a minor implementation comment was added;
- an internal detail changed without changing cross-repository summary.

## 6. Findings and severity

- **P0/P1**: keep a durable owning-repository Issue unless already represented by an equivalent durable Issue.
- **P2/P3**: summarize in audit/PR by default. Create an Issue only when the finding needs dependency tracking, handoff, explicit deferral, or long-lived follow-up.

Security-sensitive findings must not paste secret values, tokens, session content or private credential material into Issues.

## 7. User-decision blockers

When user choice is genuinely required:
- keep the owning local Issue open;
- state exactly what decision is needed and what each outcome changes;
- put `[USER_DECISION]` in the devflow Control `Next Action` when it blocks repository-level next work;
- do not broaden the request into destructive/history/security actions without approval.

A repository may remain operational while one local Issue is blocked if the blocker is explicitly isolated; the Control Issue must describe that distinction.

## 8. Cross-repository parent / local child pattern

For coordinated work:

```text
devflow Work Order
├─ repo-A local Issue / PR
├─ repo-B local Issue / PR
└─ Base local Issue / PR (only when Base integration changes)
```

The devflow parent owns shared objective/order/final acceptance. Each local child owns its repository-specific scope, implementation and verification.

The parent closes only after every required child acceptance condition and cross-repository verification is complete. A child may close earlier.

## 9. Resume checklist for a fresh agent

When opening an existing local Issue:

1. read the related devflow `[REPO]` Control Issue;
2. read the local Issue body and latest material comments;
3. inspect linked PR/branch and current SHA;
4. read referenced local specs/current state;
5. verify which acceptance conditions have current evidence;
6. continue from the first unverified condition;
7. reconcile stale Issue/Control text before declaring completion.

## 10. Anti-patterns

Do not:
- keep the same detailed task state in both devflow and local Issue;
- create a devflow Work Order for every small repository-local change;
- treat GitHub Project field values as authority;
- mark a local Issue done because code exists without verification evidence;
- keep active work only in chat;
- force all repositories to share one template/directory structure;
- close a P0/P1 finding merely to make Project status look clean.
