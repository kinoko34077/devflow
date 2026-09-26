# Cross-Repository Agent Operating Manual

Status: Operational manual
Canonical rules: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
Machine-readable contract: `.devflow/WORKFLOW.yaml`
Start point: `/AGENTS.md`

This document explains how a GPT/agent performs ordinary work across managed repositories. It does not replace repository-local specifications.

## 1. Bootstrap by repository name

Input: `kinoko34077/<repo>`.

### Step 1 — Locate cross-repository state

Search devflow Issues for the exact open title:

`[REPO] <repo>`

If exactly one exists, use it as the cross-repository entry record.

If none exists:
- do not infer Work Status, Risk, Priority or Audit SHA;
- confirm whether the repository is intentionally excluded;
- otherwise create/onboard a Repository Control Issue and perform at least the audit level required by the canonical spec before implementation.

If more than one open Control Issue exists, stop state mutation and reconcile the duplicate control records before continuing.

### Step 2 — Read the Control Issue

Always inspect:
- `Repository`
- `Work Status`
- `Repository State`
- `Priority`
- `Risk`
- `Audit SHA`
- `Active Work`
- `Next Action`
- `Detailed Current State`
- `Control Notes`

The Control Issue tells the agent where to enter the repository. It is not a substitute for local specifications.

### Step 3 — Enter repository-local canon

Follow the actual entry points listed in `Detailed Current State` / `Control Notes`.

Base-adopted repository default:
1. local `AGENTS.md`
2. `project/project.json`
3. `project/docs/INDEX.md`
4. `project/docs/CURRENT_STATE.md`
5. task-relevant local specs/code/tests

Non-Base repository:
- use its existing README/spec/current-state/config/test entry points;
- do not manufacture Base files or a standard directory structure;
- if the Control Issue entry points are stale, update the Control Issue after verifying the correct replacements.

### Step 4 — Resolve active work

If `Active Work` references a local Issue, Work Order or PR, open it before creating a duplicate.

If a durable task exists but no local record exists, decide whether a repository-local Issue is warranted using `REPOSITORY_ISSUE_MANUAL.md`.

## 2. Decide where the task belongs

Use devflow Work Order when any of the following is true:
- one operation intentionally spans multiple repositories;
- devflow/control-plane rules change;
- GitHub Project/synchronization/control vocabulary changes;
- one acceptance decision must cover coordinated changes in multiple repositories.

Use the owning repository Issue/Work Order when:
- the implementation/investigation is repository-specific;
- detailed acceptance criteria depend on that repository's code/specs;
- findings and discussion should remain with the code they affect.

A devflow Control Issue is never the detailed implementation ticket.

## 3. Pre-implementation audit

Before changing code or durable specs:

1. Record the current relevant default-branch SHA.
2. Compare it with `Audit SHA` and any local Work Order audit base.
3. Read changed specs/code since the recorded audit if the task depends on them.
4. Select audit depth:
   - QUICK: narrow known change / low uncertainty;
   - STANDARD: normal new work or stale state;
   - FULL: only when explicitly required or justified by broad/unknown impact.
5. Escalate findings:
   - P0/P1: Issue-track unless already tracked;
   - P2/P3: summarize by default unless dependency/longevity requires an Issue.

Do not schedule periodic FULL audits.

## 4. Implementation path

For normal changes:

1. make or reuse a durable local Issue when required;
2. create a dedicated branch from the verified base;
3. update Work Status/Active Work if the cross-repository summary materially changes;
4. implement in small independently verifiable changes;
5. run target tests and appropriate regression tests;
6. verify external/user entry path when API/CLI/UI/file behavior changed;
7. update local specs/current-state documents only for information they own;
8. open a PR with scope, linked Issue, verification evidence and rollback notes when relevant;
9. re-audit the changed scope and PR diff;
10. merge only when the current policy permits it.

### 4.1 Formal Pull Request Review lifecycle

For every non-trivial PR, use a submitted GitHub Pull Request Review as the durable review artifact. The PR body owns implementation scope, verification and implementer provenance; reviewer identity/provenance belongs in the Review object.

Independent Review is required when any of the following applies:
- P0/P1 finding or task;
- MEDIUM/HIGH risk change;
- `devflow`, Repository Base, Runtime or another shared control-plane change;
- shared API/contract change;
- auth/security/privacy/credential/deploy/release boundary change;
- cross-repository Work Order that changes more than one repository;
- the owning Issue explicitly requires independent review.

A PR may omit independent review only when it is genuinely trivial: LOW risk, small and safely reversible, limited to docs/hygiene or deterministic generated metadata, changes no shared contract/security/deploy boundary, and the owning Issue does not require independent review. A formal self-review may still be used, but it must be labeled as self-review.

Allowed submitted Review outcomes are `COMMENT`, `REQUEST_CHANGES`, and `APPROVE`. When native actor identity prevents an independent agent from using `APPROVE`, an independent `COMMENT` Review may carry the review result, but its body must state whether blocking findings remain. Native approval count must not be treated as proof of agent independence when multiple agent surfaces authenticate as the same GitHub actor.

Every agent-produced formal Review uses Review Provenance v1:

```markdown
### Review Provenance
- Reviewer-System: ChatGPT | Codex | Claude Code | Human
- Reviewer-Model: <model/version or unknown>
- Review-Role: independent-review | self-review | security-review | spec-review
- Implementer-System: ChatGPT | Codex | Claude Code | Human | mixed | unknown
- Reviewed-Commit: <full SHA>
- Review-Scope: <changed scope / owning Issue acceptance / file subset>
- Independence: DIFFERENT_AGENT | DIFFERENT_MODEL | SAME_AGENT_SELF_REVIEW | HUMAN
- Decision: APPROVE | REQUEST_CHANGES | COMMENT
- Review-Provenance-Version: 1
```

This block is attribution/provenance, not cryptographic signing. `self-review` and `independent-review` are distinct evidence and must never be represented as equivalent.

Review freshness is commit-specific. `Reviewed-Commit` must equal the PR head used for merge-readiness. Any later push makes prior review evidence stale for merge-readiness until a reviewer explicitly examines the new diff and submits a fresh Review against the new head.

A `REQUEST_CHANGES` Review remains blocking evidence until the finding is addressed or explicitly dispositioned and a fresh Review is submitted. Resolving an inline thread alone does not create fresh review evidence.

Reviewer handoff/resume starts from the owning Issue, current PR head SHA, latest formal Review(s), unresolved review findings/threads, and current CI/check evidence. Long-term Current State remains in the owning Issue/repository canon, not in Review text.

## 5. Merge policy

Low/medium operational risk is not equivalent to automatic merge. All of the following must hold for merge without a new user confirmation:

- the user has already granted broad authorization for this class of change;
- verification evidence is current;
- when independent review is required, a current-head formal Review from a different agent exists with no unresolved blocking finding;
- no unresolved REQUEST_CHANGES Review remains;
- there is no unresolved Critical/High-risk security or destructive boundary;
- catastrophic failure likelihood is low;
- the change can be restored through a normal revert PR.

If these conditions do not hold, leave the PR unmerged and set the correct Next Action / `[USER_DECISION]` boundary.

## 6. Post-merge reconciliation

After merge:

1. read the actual merged default-branch SHA;
2. verify required post-merge checks/workflows;
3. update repository-local Current State/specs if needed;
4. update the devflow Control Issue only when its summary changed;
5. set `Audit SHA` to an accepted current SHA only when the relevant state has actually been rechecked;
6. ensure `Active Work` and `Next Action` point to current reality;
7. allow Project event-sync to update the display layer;
8. inspect Sync Health when Project synchronization is part of acceptance.

Closing a local Issue does not automatically mean the repository is `DONE`; the Control Issue describes repository-level operational state.

## 7. State transitions

Typical task progression:

`AUDITED → WORK_ORDER_READY → READY_FOR_IMPLEMENTATION → IMPLEMENTING → AWAITING_REVIEW → AUDITED`

`DONE` is appropriate for a finite devflow Work Order/cross-repository operation. Long-lived Repository Control Issues normally remain open and return to `AUDITED`, `PARKED`, `BLOCKED`, or another current repository-level state.

Use `NEEDS_REAUDIT` when previous verification no longer supports current state. Use `BLOCKED` only when a concrete dependency prevents the next meaningful action.

## 8. Handoff between agents

A handoff must be recoverable from GitHub alone.

Before leaving unfinished work, make sure the durable records reveal:
- owning repository;
- active local Issue/Work Order;
- branch/PR if created;
- current PR head SHA and latest formal Review provenance when review has started;
- unresolved review findings/threads and current CI/check state;
- verified/audited SHA or PR head;
- completed acceptance conditions;
- remaining acceptance conditions;
- current blocker, if any;
- exact Next Action.

Do not rely on “continue from the previous chat” as the handoff mechanism.

## 9. Conflict handling

### devflow summary vs repository-local canon

Repository-local canon wins on detailed technical facts. Correct the devflow summary after confirming the local state.

### local specification vs implementation

Do not silently choose the implementation. Determine which is the current canonical requirement; track the discrepancy if it affects work.

### stale Audit SHA

A stale Audit SHA is evidence of prior inspection, not proof of current correctness. Re-audit the relevant changed scope before asserting the old conclusion still applies.

### Project vs devflow

Devflow wins. Repair Project drift with event-sync/reconcile; never copy Project values back into canonical Issues as authority.

## 10. New repository onboarding

Unless explicitly excluded, a new development/documentation repository should receive one devflow Repository Control Issue.

Initial onboarding records:
- repository identity;
- concrete default-branch Audit SHA or explicit no-commit reason;
- local canonical/Current State/test/build/runtime entry points;
- Repository State;
- Work Status;
- Priority;
- Risk;
- Next Action;
- Base adoption classification only when relevant;
- PR-only technical/process state if it affects operation.

Do not convert the repository to Base merely because it is managed.

## 11. Tool/access limitations

When an agent cannot perform a required operation:
- continue every independent read/write/verification step it can perform;
- record the exact remaining operation and required authority in the active durable Issue;
- do not claim the blocked operation happened;
- do not replace an admin/security action with an unrelated workaround.

Examples include repository rename, secret registration, security permission changes, Project UI-only structural checks, and history rewrite.
