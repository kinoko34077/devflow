# Task Checkpoint Cursor v1 Design

Status: Proposed written specification for review  
Date: 2026-09-29  
Owning Work Order: `devflow#233`  
Base: `0d5ec291800a46e836e08c2231f4b44cdac463a5`

## 1. Purpose

Long-running agent work already records `Last-Checkpoint` and `Next-Action` in worker-owned Execution Session Records, and interruption-prone work may keep a bounded progress ledger. Recovery still requires a successor to locate and interpret several records before it can determine the first unfinished unit.

Task Checkpoint Cursor v1 adds one lightweight task-level pointer whose only job is to answer:

> What is the first unfinished recovery-relevant checkpoint for this owning Issue / Work Order right now?

The cursor is navigation and drift detection. It is not task authority, an execution claim, a lease, a scheduler assignment, a lock, a review gate, or a replacement for evidence.

## 2. Fixed user requirements

1. Progress moves a visible current-position marker forward as recovery-relevant checkpoints are accepted.
2. After timeout, crash, chat loss, or worker replacement, the successor starts from the marker rather than replaying earlier accepted checkpoints solely because prior conversation context is missing.
3. If a worker arrives with an older position or appears to duplicate already-completed work, ordinary cursor mismatch produces a warning and live-state re-read, not an automatic hard rejection.
4. The worker investigates the mismatch from live GitHub evidence and adopts or reconciles the cursor as appropriate.
5. Existing fail-closed boundaries for release/deploy/publication, destructive actions, credentials/sessions/permissions, security-sensitive actions, merge/review gates, and other difficult-to-reverse operations remain unchanged.
6. The mechanism must remain lightweight and must not become a second queue, task database, scheduler, or permanent agent-role system.

## 3. Authority model

Existing authority remains unchanged:

- owning Issue / Work Order: durable task truth, scope, acceptance, checkpoint definitions and blockers;
- Task Checkpoint Cursor: current first-unfinished checkpoint projection only;
- Execution Session Record: one worker/session's current execution scope, provenance, bounded plan, `Last-Checkpoint`, `Next-Action`, blocker and handoff;
- branch / PR / Actions / tests: implementation and verification evidence;
- Formal Review: exact-SHA review evidence;
- execution-coordinator runtime state: atomic claim/lease/generation/fencing authority when actually used;
- devflow Repository Control: cross-repository summary/index;
- GitHub Project: display only;
- chat: never durable resume authority.

If the cursor conflicts with the owning Issue, accepted PR/check evidence, repository-local canon, or a live execution-coordinator claim, the cursor is reconciled from those authoritative surfaces. The cursor never overrides them.

## 4. Storage decision

### 4.1 Selected: one dedicated task-owned Issue comment

Each eligible owning Issue / Work Order MAY have exactly one active comment containing the sentinel:

```text
<!-- devflow-task-checkpoint-cursor:v1 -->
```

The comment is task-owned, not worker-owned. Different authorized workers may update the same cursor comment after re-reading live state. This is intentionally different from Execution Session Records, which remain worker/session-owned.

A dedicated comment is selected because it:

- avoids rewriting the owning Issue body when only progress changes;
- avoids a repository commit for every checkpoint movement;
- keeps progress with the owning task rather than GitHub Project;
- is accessible through ordinary GitHub Issue APIs used by existing workers;
- can later be updated by a GitHub Action or other adapter without changing the cursor contract.

### 4.2 Alternatives not selected

**Issue-body embedded marker:** simple discovery, but every cursor move rewrites durable task text and increases concurrent overwrite risk.

**Repository YAML/JSON state file:** machine-friendly, but produces commits for ephemeral task progress and mixes task progress into repository source history.

**GitHub Project field:** rejected because Project is a derived display layer and is not canonical operational state.

**execution-coordinator runtime field:** rejected as the universal storage location because the cursor must also work when no runtime claim exists and must not turn resume navigation into atomic execution ownership.

## 5. Cursor format

Canonical v1 comment body:

```markdown
<!-- devflow-task-checkpoint-cursor:v1 -->

# Task Checkpoint Cursor

```yaml
schema_version: 1
task: kinoko34077/example#123
revision: 7
last_completed: S1.2
first_unfinished: S1.3
head: abcdef1234567890
evidence:
  - https://github.com/kinoko34077/example/actions/runs/123456
updated_at: 2026-09-29T13:30:00Z
```
```

Field semantics:

- `schema_version`: fixed integer `1`.
- `task`: exact owning `owner/repository#issue` identity.
- `revision`: monotonically increasing cursor revision used only to detect drift; it is not a lock or fencing token.
- `last_completed`: checkpoint identifier most recently accepted; nullable before the first checkpoint.
- `first_unfinished`: checkpoint identifier the next worker should process; nullable only when the checkpoint sequence is terminal.
- `head`: optional exact branch/PR/default-branch SHA relevant to the accepted movement.
- `evidence`: optional compact references supporting the movement; not a replacement for PR/Actions/Review evidence.
- `updated_at`: UTC timestamp for navigation/debugging; GitHub comment metadata remains the authoritative modification time.

No worker/session identity is stored in the cursor. Worker provenance stays in Execution Session Records.

## 6. Checkpoint definition

Checkpoint identifiers are owned by the task's durable plan/checklist. The cursor does not invent them.

A checkpoint should be the smallest recovery unit for which replay after interruption would create meaningful cost, confusion, or risk. It should not represent every command or tool call.

Typical units include:

- live-state/bootstrap complete;
- failure reproduced / RED established;
- implementation complete;
- targeted GREEN complete;
- regression or real-entry verification complete;
- PR opened at a known head;
- exact-head Review complete;
- merge/disposition complete;
- owner Issue / Current State / devflow Control reconciliation complete.

If a task has no durable checkpoint sequence and is short enough that replay is harmless, no cursor is required.

## 7. Worker read/resume contract

For an eligible task, resume order becomes:

1. read normal devflow/repository authority;
2. open the owning Issue / Work Order;
3. locate the unique active v1 cursor comment;
4. read the cursor before reconstructing historical progress;
5. verify the referenced checkpoint still exists in the owning task and compare only the live evidence needed for that checkpoint;
6. inspect relevant Execution Session Records for active overlap/provenance;
7. start from `first_unfinished` unless live evidence shows the cursor itself requires reconciliation.

A successor MUST NOT replay an earlier accepted checkpoint solely because chat history, Memory, or the predecessor session disappeared.

Missing cursor is not an error for legacy or trivial tasks. The worker falls back to the existing Issue/Session/PR resume path and may create a cursor when the task qualifies and the next unfinished checkpoint is unambiguous.

## 8. Cursor movement

### 8.1 Normal advance

Before moving the cursor, the worker re-reads the live cursor and the evidence that establishes completion of the current checkpoint.

A normal advance provides at least:

- expected `revision`;
- expected `first_unfinished`;
- completed checkpoint;
- next `first_unfinished` or terminal `null`;
- optional head/evidence references.

If expected and live state match, the helper updates:

- `last_completed` to the completed checkpoint;
- `first_unfinished` to the next checkpoint;
- `revision` to live revision + 1;
- optional head/evidence;
- `updated_at`.

### 8.2 Drift is advisory by default

A revision/checkpoint mismatch does not by itself prove unsafe work. The helper therefore returns structured drift information and leaves the AI responsible for re-reading live task state.

Required outcomes:

- `OK_ADVANCED`: expected cursor matched and cursor advanced.
- `WARN_FORWARD_DRIFT`: live cursor is already later than the worker expected. Most likely another worker/session advanced it. Re-read current task/evidence and normally adopt the live cursor.
- `WARN_REVISION_DRIFT`: revision changed while the same checkpoint appears current. Re-read cursor/evidence before continuing.
- `WARN_BEHIND_OR_REORDERED`: live cursor is earlier than the worker expected, or task checkpoint ordering changed. Investigate task edits/evidence before any cursor rewrite.
- `WARN_DUPLICATE_MARKER`: more than one active marker exists. Determine the canonical marker from live task history and reconcile.
- `WARN_MALFORMED_MARKER`: marker cannot be parsed or violates v1 invariants. Reconstruct from durable task/evidence before replacing it.
- `NO_MARKER`: use legacy resume logic; create a marker only when the task qualifies and state is unambiguous.

Ordinary warning outcomes MUST NOT be described as runtime claim rejection or fencing failure.

## 9. Reconciliation and backward movement

A normal `advance` operation never silently moves the cursor backward.

If live evidence demonstrates the cursor is wrong, the worker uses an explicit `reconcile` operation after recording the reason on the owning Issue or in the cursor update evidence. Reconciliation may:

- repair malformed fields;
- select one canonical marker when duplicates exist;
- move `first_unfinished` backward when previously accepted progress was invalidated;
- move directly forward when the cursor failed to record already-accepted evidence;
- reset head/evidence references after task-plan changes.

Reconciliation increments `revision` and records a compact reason/evidence reference. It is a visible correction, not an implicit stale-writer overwrite.

## 10. Warning versus hard stop

The cursor mechanism itself is intentionally advisory for normal concurrency/drift.

Examples that remain warning/re-read cases:

- another worker already completed the same checkpoint;
- revision changed during work;
- a successor started from an old chat summary;
- the marker is one checkpoint ahead of the worker's expectation;
- a stale session record disagrees with the task-level cursor.

Existing external safety rules remain fail-closed where applicable. Examples include:

- release/deploy/publication without required authorization;
- credential/session/permission mutation without required authorization;
- destructive deletion or shared-history rewrite;
- unresolved security-sensitive boundary;
- merge with required review/verification missing or stale;
- execution-coordinator claim/fencing conflict when that runtime authority is actually in use.

A cursor warning never weakens those gates.

## 11. Helper/API boundary

v1 defines a transport-neutral helper contract before choosing a universal GitHub Actions deployment model.

Minimum operations:

- `read`: discover and parse the unique active cursor;
- `compare`: compare expected revision/checkpoint with live cursor and return structured outcome;
- `advance`: perform normal forward movement when live state matches; otherwise return warning data;
- `reconcile`: explicitly replace/repair cursor state from verified durable evidence;
- `render`: produce canonical v1 comment text.

The pure transition/parser logic belongs in devflow and is testable without network access. GitHub transport is a thin adapter.

A GitHub Actions adapter MAY call the same helper and surface drift with GitHub warning annotations while keeping the job successful for ordinary drift. v1 correctness does not require installing a workflow into every managed repository. This avoids turning cursor adoption into a repository-wide workflow migration.

## 12. GitHub Actions behavior when used

When an Action adapter is present:

- ordinary `WARN_*` drift emits `::warning::` / job-summary guidance and does not fail the workflow solely because the cursor moved;
- `OK_ADVANCED` updates the canonical cursor comment and reports the new revision/checkpoint;
- malformed/duplicate state reports warning plus reconciliation guidance rather than guessing;
- safety failures originating outside cursor semantics retain their existing failing behavior;
- Action concurrency may serialize cursor-update jobs, but serialization is an optimization, not authority and not a lock contract.

## 13. Interaction with Execution Session Records

Cursor and Session Records answer different questions:

```text
Task Checkpoint Cursor
= where the task resumes

Execution Session Record
= who/session is currently working on what bounded scope, with provenance and handoff state
```

A session's `Next-Action` SHOULD normally agree with the task cursor for the slice it owns. If they differ, the worker reads live evidence and resolves the discrepancy; it does not automatically overwrite either record.

A dead/stale Session Record therefore does not erase task position. The cursor remains at the first unfinished task checkpoint and a successor session can continue from there.

## 14. Interaction with progress-ledger Issues

A dedicated progress ledger such as `devflow#232` may continue to hold the full ordered checkpoint list, stage acceptance, blockers and evidence. The cursor is a compact projection of that ledger's first unfinished checkpoint.

The progress ledger remains useful when the task has many independently recoverable units. The cursor removes the need for a successor to infer current position by scanning the full ledger first.

If ledger and cursor disagree, ledger/owning-task evidence governs and the cursor is reconciled.

## 15. Initial implementation scope

The first implementation should remain bounded:

1. add a small parser/renderer/transition module for cursor v1;
2. add tests for valid read/render, normal advance, forward drift, revision drift, backward/reordered warning, duplicate marker, malformed marker, missing marker, and explicit reconcile;
3. update canonical devflow docs and `.devflow/WORKFLOW.yaml` with the cursor ownership/resume contract;
4. update `AGENTS.md` / operating manuals so eligible resume reads cursor before reconstructing historical checkpoints;
5. provide one devflow-local reference/pilot adapter or documented GitHub API path only if needed to prove comment update behavior;
6. pilot against a bounded devflow-owned progress Issue before broader adoption.

Do not require a cross-repository credential/App/permission change for v1.

## 16. Acceptance

The design is accepted when implementation can demonstrate all of the following:

- a task has exactly one discoverable cursor or a typed missing/duplicate condition;
- the cursor directly yields the first unfinished checkpoint;
- interruption followed by a new worker resumes from that checkpoint;
- already-accepted earlier checkpoints are not replayed solely because session/chat context vanished;
- stale/duplicate expected position produces a structured warning and re-read path rather than ordinary hard rejection;
- explicit reconciliation can correct a wrong cursor without hiding that correction;
- Execution Session and execution-coordinator authority remain distinct;
- Project remains display-only;
- existing Human/security/merge/review safety gates remain unchanged;
- no heavy queue/scheduler/mandatory per-repository workflow is introduced.

## 17. Rejected expansion for v1

Do not add in v1 without evidence from the pilot:

- weighted scheduling or fairness logic;
- automatic checkpoint generation by an LLM;
- one cursor per worker;
- automatic rollback based only on cursor mismatch;
- mandatory GitHub App installation changes;
- cursor state in GitHub Project fields;
- a separate durable database;
- hard rejection for ordinary forward/revision drift;
- per-command or per-tool-call checkpoints.
