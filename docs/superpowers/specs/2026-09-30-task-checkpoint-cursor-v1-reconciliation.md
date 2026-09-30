# Task Checkpoint Cursor v1 — Current-Main Reconciliation

Status: Approved design reconciliation for implementation  
Date: 2026-09-30  
Owning Work Order: `devflow#233`  
Original reviewed design: `docs/superpowers/specs/2026-09-29-task-checkpoint-cursor-design.md` / PR #234  
Current accepted devflow base: `e51ce12405b867215e4d2c1eb8b5eb9fcace2a39`

## 1. Approval and purpose

KiNoTch. explicitly directed continuation of the Task Checkpoint Cursor work on 2026-09-30. The written-spec approval boundary recorded by `devflow#233` is therefore satisfied.

The reviewed PR #234 design remains the feature contract. This addendum reconciles that design with the durable-progress and affected-surface policies accepted on devflow main after PR #234 was written.

## 2. Relationship to durable progress

`docs/operations/DURABLE_PROGRESS_EXTERNALIZATION.md` remains the standing operational contract.

Task Checkpoint Cursor v1 is an optional compact **projection** of a task's recoverable execution position. It does not replace the mandatory durable progress surface required for qualifying work.

Therefore:

- the owning Issue / Work Order remains durable task truth;
- the durable progress surface remains responsible for enough state to recover scope, completed position, first unfinished action, exact target version, blocker and compact evidence;
- a cursor may project the single canonical `first_unfinished` frontier from that durable state;
- absence of a cursor does not make an otherwise compliant durable progress surface invalid;
- presence of a cursor does not make an otherwise non-compliant task durable;
- when an accepted transition changes the projected recovery frontier, the cursor is part of the directly affected durable-surface set and must be reconciled before the bounded unit exits;
- broad audits remain a backstop and do not own ordinary cursor cleanup.

## 3. Resume order

For a task with an accepted v1 cursor:

1. read normal devflow / repository authority and the owning Issue / Work Order;
2. identify the durable progress surface;
3. read the unique trusted cursor projection before reconstructing historical checkpoint chronology;
4. inspect only the live evidence, Session state, blockers and readiness gates required to validate the cursor's current frontier;
5. resume at `first_unfinished` when runnable;
6. if cursor and authoritative durable state disagree, warn and reconcile rather than replaying accepted history by default.

Chat, Memory and Project fields remain non-authoritative for resume.

## 4. Cursor authority boundary

The cursor remains navigation and drift detection only.

It is not:

- a task database or queue;
- readiness authority;
- a lock, claim, lease, compare-and-swap guarantee or fencing token;
- Review / CI / merge authority;
- permission to cross Human, security, publication, credential/session/permission or destructive-operation gates.

`execution-coordinator` remains the atomic claim / lease / fencing authority when that runtime is actually used.

## 5. v1 implementation boundary

Implement the smallest transport-neutral helper surface required by the reviewed design:

- strict v1 parse / render;
- trusted-marker inspection with typed missing, duplicate, untrusted and malformed outcomes;
- initialization;
- expected/live comparison;
- forward advance preparation;
- post-write verification;
- explicit reconciliation;
- stable single-frontier semantics.

The pure helper must use the Python standard library only. No new runtime dependency or repository-wide GitHub App / workflow installation is required.

The helper does not perform GitHub network writes. Existing GitHub clients, agents or a future thin Actions adapter may transport the canonical comment. v1 correctness is proved through pure transition tests plus one bounded real Issue-comment pilot.

## 6. Pilot boundary

Use `devflow#233` itself as the first bounded transport pilot after the helper is GREEN:

- one trusted canonical cursor comment;
- frontier movement only after the corresponding durable checkpoint is accepted;
- ordinary stale expected state produces warning / re-read semantics;
- no destructive or security-sensitive operation is part of the pilot.

Pilot state is progress evidence, not permanent specification authority.

## 7. Review boundary

Because this work changes devflow operational authority/source-of-truth semantics and adds executable helper behavior, final acceptance requires:

- Required PR gate GREEN on the exact implementation head;
- current-head Formal Review;
- qualifying different-system/model current-head Formal Review;
- review-readiness GREEN;
- directly affected durable surfaces reconciled before acceptance/exit.

No merge, release, deployment, publication, credential/session/permission change, destructive action, shared-history rewrite or RDC use is authorized by this work.