# devflow — Agent Start Here

This is the required entry point for GPT/agent work that uses KiNoTch. cross-repository development control.

Do not use chat history, GitHub Project fields, or an old summary as the source of truth when the current GitHub state is available.

## 1. Start from the target repository name

Given `kinoko34077/<repo>`:

1. Find the open devflow Issue titled exactly `[REPO] <repo>`.
2. Read its `Work Status`, `Repository State`, `Audit SHA`, `Active Work`, `Next Action`, `Detailed Current State`, and `Control Notes`.
3. Follow the repository-local canonical entry points recorded there.
4. Open the referenced repository-local Issue / Work Order / PR when `Active Work` points to one.
5. Read only the local specifications, Current State, code, tests and history needed for the current task.

If no Repository Control Issue exists, do not invent managed state. Treat onboarding as required and follow `docs/operations/AGENT_OPERATING_MANUAL.md`.

## 2. What owns what

| Information | Canonical owner |
| --- | --- |
| Cross-repository workflow/state vocabulary | devflow canonical spec + `.devflow/WORKFLOW.yaml` |
| One repository's cross-repo summary | its open devflow `[REPO]` Control Issue |
| Cross-repository coordinated work | devflow Work Order |
| Repository-specific requirements/specs/current technical detail | owning repository |
| Repository-specific implementation task/finding | owning repository Issue / Work Order |
| Code diff and verification evidence | owning repository PR / Actions / tests |
| Display/overview | GitHub Project; never canonical |

## 3. Read order

### Normal work on a managed repository

1. This file: `devflow/AGENTS.md`.
2. The target `[REPO] <repo>` Control Issue.
3. The target repository's own agent/readme/current-state entry point.
4. Active repository-local Issue/Work Order and PR, if any.
5. Task-relevant specs/code/tests.
6. `docs/operations/REPOSITORY_ISSUE_MANUAL.md` when deciding Issue ownership/lifecycle.
7. `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md` and `.devflow/WORKFLOW.yaml` only when workflow semantics or boundaries are needed.

### Work on devflow itself or cross-repository rules

1. This file.
2. `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`.
3. `.devflow/WORKFLOW.yaml`.
4. Relevant devflow Work Order / Repository Control Issues.
5. `docs/project/PROJECT_SYNC.md` if synchronization/Project behavior is involved.
6. Implementation/tests only for the touched control-plane component.

## 4. Repository-local entry

If the repository uses KiNoTch. Repository Base, after the Control Issue read its local `AGENTS.md`, then follow its Base-defined sequence (`project/project.json`, docs index, Current State, task-relevant material).

If it does not use Repository Base, use the existing repository structure recorded in its Control Issue. Do not add `.kinotch/`, `AGENTS.md`, `CURRENT_STATE.md`, templates, or other structure merely to make it look like another repository.

## 5. Normal lifecycle

```text
Control Issue / local canon read
→ audit current relevant SHA
→ create or reuse repository-local Issue when durable task tracking is warranted
→ dedicated branch
→ implementation
→ tests + regression + real-entry verification as applicable
→ Pull Request
→ re-audit changed scope
→ merge if authorized, low-risk, and safely revertible
→ update repository-local canon/current state where owned information changed
→ update devflow Control Issue only when cross-repository summary changed
→ Project display follows synchronization
```

Do not write directly to the default branch for normal changes.

## 6. When devflow must be updated

Update the target Repository Control Issue when any of these changes:

- accepted Audit SHA;
- Work Status or Repository State;
- cross-repository Priority/Risk;
- Active Work reference;
- Next Action;
- repository-local canonical entry points;
- P0/P1 finding that changes readiness;
- managed/parked/deprecated/cancelled/excluded state.

Do not copy every commit, test log, implementation note, or detailed specification into devflow.

## 7. Safety boundary

Already-authorized changes with low catastrophic potential may be merged after verification when a revert PR can safely restore the previous state.

Before executing any of these, obtain explicit user confirmation:

- release or deploy;
- publication with external effect;
- destructive deletion;
- shared-history rewrite;
- credential/session/permission change;
- other security-sensitive or difficult-to-reverse operation.

If a merged change is wrong, use a dedicated rollback branch + revert PR. Do not rewrite shared `main`.

## 8. Resume / handoff

A new worker resumes from GitHub evidence, not from the previous worker's prose:

1. Control Issue;
2. referenced local Issue/PR;
3. recorded Audit SHA versus current branch/PR head;
4. first acceptance condition without current verification evidence.

If devflow summary and repository-local canon disagree, the owning repository governs detailed technical truth and devflow must be reconciled as the summary.

## 9. Detailed manuals

- Agent operations: `docs/operations/AGENT_OPERATING_MANUAL.md`
- Repository-local Issue usage: `docs/operations/REPOSITORY_ISSUE_MANUAL.md`
- Canonical control-plane spec: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
- Machine-readable workflow: `.devflow/WORKFLOW.yaml`
- Project synchronization: `docs/project/PROJECT_SYNC.md`
