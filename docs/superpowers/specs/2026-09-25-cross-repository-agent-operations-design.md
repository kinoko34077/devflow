# Cross-Repository Agent Operations Design

Status: Approved by user request 2026-09-25
Tracking: Work Order #46

## 1. Goal

Make the cross-repository control plane usable by a new GPT/agent without chat history and without requiring every managed repository to adopt the same filesystem structure.

A worker given only a repository name must be able to answer, in order:

1. Is this repository managed by devflow?
2. What is its current cross-repository state and next action?
3. Which repository-local documents are authoritative for this task?
4. Which Issue owns the work details?
5. What branch/PR/verification path is required?
6. When must devflow be updated after the repository changes?

## 2. Authority model

Authority remains split rather than duplicated.

```text
repository-local specifications / code / Issues / PRs
        ↓ summary/handoff
open Repository Control Issue in devflow
        ↓ synchronization
GitHub Project display
```

- devflow owns cross-repository workflow rules, one Repository Control Issue per managed repository, cross-repository Work Orders, synchronization rules, and the agent bootstrap contract.
- each managed repository owns its detailed specifications, implementation, repository-local Issues/Work Orders, PRs, tests and detailed technical Current State.
- GitHub Project is display-only.
- Repository Base owns only the Base-to-devflow integration boundary.

No layer may silently overwrite a more specific canonical layer merely because it is easier to access.

## 3. Agent bootstrap contract

The discoverable root entry point is `AGENTS.md` in devflow.

For work on any managed repository, the required bootstrap is:

1. Read devflow `AGENTS.md`.
2. Read the repository's open `[REPO] <name>` Repository Control Issue.
3. Follow the repository-local entry points recorded by that Control Issue.
4. Read only task-relevant repository-local specifications, Current State, Issues, PRs, code and tests.
5. Read `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md` / `.devflow/WORKFLOW.yaml` only when workflow semantics, state vocabulary, operation boundaries or cross-repository behavior are needed.

For a Base-adopted repository, step 3 enters that repository through its `AGENTS.md`, then `project/project.json`, `project/docs/INDEX.md`, `project/docs/CURRENT_STATE.md`, and task-relevant material.

For a non-Base repository, the Control Issue records the actual existing entry points. Missing `.kinotch/`, `AGENTS.md`, or `CURRENT_STATE.md` is not itself a reason to restructure the repository.

## 4. Issue authority

### Repository Control Issue — devflow

One long-lived open Issue per managed repository. It is an index/current-state summary only. It records Audit SHA, Repository State, Work Status, Priority, Risk, Active Work, Next Action and repository-local entry points.

It does not contain full implementation specs, task logs, code-level findings that belong to a local Issue, or duplicated Current State prose.

### Cross-repository Work Order — devflow

Use when work changes the control plane itself, spans multiple repositories as one coordinated operation, changes shared cross-repository rules, or requires one acceptance decision across repositories.

### Repository-local Issue / Work Order — owning repository

Use for implementation or investigation whose detailed scope belongs to one repository. The local Issue is the detailed task record and should contain objective/problem, scope, acceptance criteria, non-goals where useful, verification, related specs/decisions, and implementation/PR references.

A repository does not need to copy devflow's exact template if it already has a suitable local convention, but the same decision information must remain discoverable.

### Pull Request — owning repository

PR is the review boundary for normal changes. It records the actual diff, verification evidence, linked local Issue/Work Order and re-audit result where applicable.

## 5. Operating lifecycle

Normal repository-local work:

```text
bootstrap
→ confirm audit/current SHA and local canon
→ create/reuse repository-local Issue when durable tracking is warranted
→ dedicated branch
→ implement in small verifiable changes
→ tests / regression / real-entry verification as applicable
→ PR
→ re-audit changed scope
→ low-risk merge when authorized and rollback is available
→ update local Current State/specs only where their owned information changed
→ update devflow Control Issue only when its summary fields changed
→ Project follows devflow synchronization
```

A repo-local Issue is not mandatory for a truly trivial change when the PR itself provides sufficient durable scope and verification, unless repository rules require an Issue. P0/P1 findings remain Issue-tracked by default.

## 6. Control Issue update triggers

Update the devflow Repository Control Issue when at least one of these changes:

- Audit SHA / accepted default-branch SHA;
- Work Status;
- Repository State;
- Priority or Risk at cross-repository level;
- Active Work reference;
- Next Action;
- repository-local canonical entry points;
- a P0/P1 finding materially changes cross-repository readiness;
- the repository becomes managed, parked, deprecated, cancelled or excluded.

Do not update it for every commit, comment, test run or minor implementation detail.

## 7. Restart / handoff contract

A new agent must not rely on previous chat summaries as canonical state.

To resume:

1. locate the Repository Control Issue;
2. read its Audit SHA, Active Work, Next Action and local entry points;
3. open referenced local Issue/PR;
4. compare the current default branch / PR head to the recorded audit base;
5. re-audit if the relevant code/spec changed after the recorded evidence;
6. continue from the first unverified acceptance condition.

If devflow and the owning repository disagree, the more specific repository canon governs detailed technical truth; devflow must then be reconciled as the cross-repository summary. If two repository-local canonical sources conflict, do not guess which is current—resolve the local source conflict first.

## 8. Safety / merge / rollback

- normal changes use dedicated branches and PRs;
- already-authorized LOW/MEDIUM changes with low catastrophic potential may merge after verification when a revert PR can safely restore the prior state;
- if a merged change is later found faulty, use a dedicated rollback branch and revert PR; do not rewrite shared `main`;
- release, deploy, publication, destructive deletion, history rewrite, credentials/permissions and other security-sensitive or difficult-to-reverse actions require explicit user confirmation before execution.

## 9. Repository rename migration

Operational repository name is `kinoko34077/devflow`.

Migration is two-phase because repository rename is an admin mutation separate from code/document changes:

### Phase A — rename-ready

- make human/agent documentation refer to logical name `devflow` while clearly recording the current GitHub repository identity until the rename occurs;
- remove unnecessary runtime dependence on the literal old repository name;
- enumerate Project/Actions/links requiring post-rename verification.

### Phase B — admin rename

- rename GitHub repository `devflow-test` → `devflow`;
- verify repository redirect/current identity, Actions, Issues/PRs, branch protection and secrets as observable;
- verify Project Auto-add configuration still targets the renamed repository identity;
- run full Project `reconcile` then `verify`;
- update remaining canonical old-name references and Control Issue audit SHA.

The repository must not claim Phase B complete before the admin rename is actually observed.

## 10. Base integration

Repository Base must not copy this design's state vocabulary or Project configuration. Its responsibility is limited to:

- tell Base-aware agents that cross-repository work starts with the relevant devflow Control Issue;
- retain the Base repository-local read sequence after that handoff;
- point to devflow for Issue/Work Order/audit/merge semantics;
- preserve Base-managed vs Project-owned boundaries.

## 11. Acceptance

The design is accepted when a fresh agent can begin from a managed repository name, identify the Control Issue, enter the correct repository-local canon, determine the durable task record, perform branch/PR verification, and know exactly whether/when to write state back to devflow without using chat history as canon.