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

#### Reviewer input packet

Before reviewing the diff, resolve only the material needed for the change:

- owning Issue / Work Order and its acceptance criteria/non-goals;
- PR base and current exact head SHA;
- complete changed-file list and diff;
- repository-local specifications / Current State relevant to the changed behavior;
- implementer verification evidence and current Actions/checks for the exact head;
- previous formal Reviews, unresolved review threads and durable findings, when present;
- Priority/Risk and required review role from the owning task / Control.

Chat history is not review evidence. Unchanged unrelated specifications, Issues and repository areas are not read merely because they exist.

#### Proportional review depth

Review and verification optimize for useful evidence per unit of effort, not exhaustive ceremony.

Default depth model:

```text
small/local change
  -> targeted tests + targeted review

local failure/finding
  -> expand around the affected state/data/control-flow/dependency boundary

cross-cutting/high-impact change
  -> broader changed-scope regression/integration review

final acceptance / major milestone
  -> whole relevant system/repository verification where justified
```

Avoid self-evident or low-information checks that are already guaranteed by a stronger current check and would not expose a distinct defect class. Do not add tests merely to increase test count or satisfy a checklist.

The review dimensions below are dimensions to consider, not six mandatory exhaustive audits. Mark an irrelevant dimension `N/A`. A review is too shallow when it skips a plausible affected boundary; it is too broad when it repeatedly checks unrelated already-proven behavior without an impact reason.

#### Review dimensions

1. **Scope / requirement trace**
   - changed behavior maps to the owning Issue/specification;
   - acceptance criteria are not silently weakened;
   - non-goals and unrelated behavior remain outside scope.
2. **Correctness / state / failure paths**
   - inspect affected normal, boundary, invalid/error, retry/recovery and lifecycle paths;
   - when applicable, inspect stale-result, ordering, cleanup/cancellation and duplicate-action hazards.
3. **Regression / compatibility**
   - preserve affected existing behavior, persisted data, public API/CLI/UI contracts and migration assumptions where relevant.
4. **Design / maintainability**
   - responsibilities and source-of-truth boundaries remain coherent;
   - avoid duplicated knowledge and unjustified speculative abstraction.
5. **Verification quality**
   - tests/checks demonstrate the changed contract;
   - RED/GREEN evidence is credible when claimed;
   - CI/check evidence belongs to the exact reviewed head.
6. **Risk-specific checks**
   - apply only when the diff touches the corresponding boundary: security/privacy/credentials/deploy/dependencies/workflows/UI accessibility-usability/etc.

A narrower `security-review` or `spec-review` must state its scope. It does not silently replace a required baseline review unless another current Review covers the omitted baseline.

#### Review findings

Material findings should be recoverable in this form:

```text
Finding-ID: R<n>
Severity: P0 | P1 | P2 | P3
Blocking: YES | NO
Location: <file/line or behavioral surface>
Requirement: <Issue/spec/test contract, when applicable>
Observed: <current diff behavior>
Expected: <required behavior>
Impact: <why it matters>
Disposition: OPEN | FIXED | DEFERRED | NOT_A_FINDING
Evidence: <diff/test/run/reference>
```

Diff-local findings belong in inline Review threads when practical. P0/P1 findings that outlive one Review cycle or change task readiness belong in the owning Issue. P2/P3 may remain in the Review when bounded to that PR; durable deferral needs a follow-up Issue when dependency/handoff/history matters. `DEFERRED` names the follow-up or accepted non-goal; `NOT_A_FINDING` records why the concern does not violate the current contract.

Merge-blocking conditions include:

- any unresolved P0/P1 finding;
- acceptance/spec mismatch;
- missing/failing required CI/check evidence;
- review against a stale head;
- unresolved `REQUEST_CHANGES` evidence;
- unresolved blocking review thread;
- unauthorized release/deploy/credential/permission/destructive scope expansion;
- required independent review represented only by self-review.

P2/P3 are not automatically non-blocking: mark `Blocking: YES` when the finding can invalidate acceptance, cause meaningful regression/data-state corruption, or make verification unreliable.

#### Clean Review summary

A clean formal Review records what was actually checked, for example:

```markdown
## Review Result
- Blocking findings: none
- Scope / requirements: PASS
- Correctness / failure paths: PASS | N/A
- Regression / compatibility: PASS | N/A
- Design / maintainability: PASS | N/A
- Verification evidence: PASS
- Risk-specific checks: PASS | N/A
- Reviewed Actions/checks: <run/check refs>
- Reviewed-Commit: <full SHA>
```

`No blocking findings` alone is not a substitute for stating the reviewed dimensions.

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

#### Exact-SHA freshness and incremental re-review

Review freshness is commit-specific. `Reviewed-Commit` must equal the PR head used for merge-readiness. Any later push makes prior review evidence stale for merge-readiness.

For a new head after review:

1. compare the previous `Reviewed-Commit...new head`;
2. review every changed hunk plus surrounding behavior invalidated by that delta;
3. reuse earlier unchanged evidence instead of repeating it;
4. perform broader changed-scope review when the delta materially changes scope, acceptance, architecture, persistence, security boundary or test strategy;
5. submit a fresh formal Review against the exact new head.

Thread resolution alone never refreshes Review provenance.

A `REQUEST_CHANGES` Review remains blocking evidence until the finding is addressed or explicitly dispositioned and a fresh Review is submitted.

#### Information ownership during review

- repository specification/design docs own durable desired behavior/contracts;
- repository Current State owns durable current repository facts/limitations useful beyond one task;
- owning Issue/Work Order owns bounded task scope, acceptance, blockers, durable findings and next action;
- PR/CI own the concrete diff and implementation/verification evidence;
- formal Review owns exact-SHA review evidence and diff-local findings;
- devflow Control remains a cross-repository summary/index.

Reference the owning surface instead of copying the same canonical information into multiple places. `REPOSITORY_ISSUE_MANUAL.md` defines finding promotion/retirement in detail.

Reviewer handoff/resume starts from the owning Issue, current PR head SHA, latest formal Review(s), unresolved review findings/threads, and current CI/check evidence. Long-term Current State remains in repository-owned documentation, not Review text.

## 5. Merge policy

Low/medium operational risk is not equivalent to automatic merge. All of the following must hold for merge without a new user confirmation:

- the user has already granted broad authorization for this class of change;
- verification evidence is current;
- when independent review is required, a current-head formal Review from a different agent exists with no unresolved blocking finding;
- no unresolved REQUEST_CHANGES Review remains;
- current required Actions/checks are green for the PR head;
- the accepted `Reviewed-Commit` equals the current PR head;
- no unresolved blocking review thread or durable P0/P1 finding remains;
- branch protection reports a merge-compatible state;
- there is no unresolved Critical/High-risk security or destructive boundary;
- catastrophic failure likelihood is low;
- the change can be restored through a normal revert PR.

### 5.1 Auto-merge execution

Auto-merge is a merge-execution convenience, not a review or verification gate. Enable it only for a LOW-risk, safely reversible PR after every devflow policy gate that GitHub may not enforce natively is already satisfied.

In particular:

- do not use auto-merge for release, deploy, publication, credential, permission, destructive, or other confirmation-gated finalization;
- when independent review is required, the current-head independent formal Review must already exist and have no unresolved blocker before auto-merge is enabled;
- required CI/status evidence must be current and green, and blocking review conversations/findings must already be resolved;
- while AI reviewer surfaces share one GitHub actor and native required approval count remains `0`, never enable auto-merge early on the assumption that GitHub will wait for agent-level independent Review;
- after enablement, branch protection continues to govern technical merge eligibility; after merge, perform the normal Issue/Control reconciliation in Section 6.

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
