# Task Checkpoint Cursor v1 — Current-Main Reconciliation

Status: Accepted implementation reconciliation (initial v1); follow-up P3 hardening accepted  
Date: 2026-09-30  
Owning Work Order: `devflow#233`  
Original reviewed design: `docs/superpowers/specs/2026-09-29-task-checkpoint-cursor-design.md` / PR #234  
Implementation base at reconciliation: `e51ce12405b867215e4d2c1eb8b5eb9fcace2a39`

## 1. Approval and purpose

KiNoTch. explicitly directed continuation of the Task Checkpoint Cursor work on 2026-09-30. The written-spec approval boundary recorded by `devflow#233` is therefore satisfied.

The reviewed PR #234 design remains the feature contract. This addendum reconciles that design with the durable-progress and affected-surface policies accepted on devflow main after PR #234 was written.

The initial v1 implementation was accepted through PR #257. The later bounded canonical-validation hardening from `devflow#260` / PR #261 did not alter the authority model; its accepted behavior is reflected by the canonical design and operator documentation.

**Standing-policy supersession (2026-10-01):** `devflow#290` / PR #291 changes only the eligibility/default relationship with durable progress: a Task Checkpoint Cursor is required for eligible single-frontier multi-step work and is paired with the designated durable progress surface. Historical statements below that described the Cursor as optional are superseded by this note and the updated wording in §2–§3. Cursor authority remains navigation/drift projection only.

## 2. Relationship to durable progress

`docs/operations/DURABLE_PROGRESS_EXTERNALIZATION.md` remains the standing operational contract.

Task Checkpoint Cursor v1 is a compact **projection** of a task's recoverable execution position. Under the standing policy updated by `devflow#290`, it is required for eligible single-frontier multi-step work and complements rather than replaces the mandatory designated durable progress surface.

Therefore:

- the owning Issue / Work Order remains durable task truth;
- the durable progress surface remains responsible for enough state to recover scope, completed position, first unfinished action, exact target version, blocker and compact evidence;
- for eligible single-frontier multi-step work, a cursor must project the single canonical `first_unfinished` frontier from that durable state;
- absence of a cursor on an eligible task is an operational gap that must be repaired before broad continuation; it does not retroactively invalidate already accepted work or erase an otherwise usable durable progress surface;
- presence of a cursor does not make an otherwise non-compliant task durable;
- when an accepted transition changes the projected recovery frontier, the cursor is part of the directly affected durable-surface set and must be reconciled before the bounded unit exits;
- broad audits remain a backstop and do not own ordinary cursor cleanup.

## 3. Resume order

For eligible single-frontier multi-step work:

1. read normal devflow / repository authority and the owning Issue / Work Order;
2. read or repair the unique trusted cursor and use `first_unfinished` to identify the compact current frontier before reconstructing historical checkpoint chronology;
3. follow the owning task's durable reference to the designated progress surface and read the detailed progress/evidence around that frontier;
4. inspect only the live evidence, Session state, blockers and readiness gates required to validate the cursor's current frontier;
5. resume at `first_unfinished` when runnable;
6. if cursor and authoritative durable progress disagree, warn and reconcile both layers rather than replaying accepted history by default.

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

### Initial v1 acceptance

Initial v1 acceptance required a qualifying different-system/model review because the initial feature changed devflow operational authority/source-of-truth semantics and added executable helper behavior. The initial acceptance gates were:

- Required PR gate GREEN on the exact implementation head;
- current-head Formal Review;
- qualifying different-system/model current-head Formal Review;
- review-readiness GREEN;
- directly affected durable surfaces reconciled before acceptance/exit.

### Later bounded maintenance

Later bounded maintenance, including P3 canonical-validation hardening, is classified under its own PR review policy; it does not inherit a permanent different-reviewer requirement when authority semantics are unchanged.

The initial v1 design approval did not authorize release, deployment, publication, credential/session/permission change, destructive action, shared-history rewrite or RDC use; subsequent bounded maintenance remains subject to the same external safety gates.
