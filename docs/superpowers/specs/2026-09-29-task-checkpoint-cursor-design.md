# Task Checkpoint Cursor v1 Design

Status: Accepted design; implemented by PR #257; P3 hardening by PR #261  
Date: 2026-09-29  
Owning Work Order: `devflow#233`  
Original design base: `0d5ec291800a46e836e08c2231f4b44cdac463a5`

## 1. Purpose

Long-running agent work already records `Last-Checkpoint` and `Next-Action` in worker-owned Execution Session Records, and interruption-prone work may keep a bounded progress ledger. Recovery still requires a successor to locate and interpret several records before it can determine the first unfinished unit.

Task Checkpoint Cursor v1 adds one lightweight task-level pointer whose only job is to answer:

> What is the first unfinished recovery-relevant checkpoint for this owning Issue / Work Order right now?

The cursor is navigation and drift detection. It is not task authority, an execution claim, a lease, a scheduler assignment, a lock, a review gate, a readiness signal, or a replacement for evidence.

## 2. Fixed user requirements

1. Progress moves a visible current-position marker forward as recovery-relevant checkpoints are accepted.
2. After timeout, crash, chat loss, or worker replacement, the successor starts from the marker rather than replaying earlier accepted checkpoints solely because prior conversation context is missing.
3. If a worker arrives with an older position or appears to duplicate already-completed work, ordinary cursor mismatch produces a warning and live-state re-read, not an automatic hard rejection.
4. The worker investigates the mismatch from live GitHub evidence and adopts or reconciles the cursor as appropriate.
5. Existing fail-closed boundaries for release/deploy/publication, destructive actions, credentials/sessions/permissions, security-sensitive actions, merge/review gates, and other difficult-to-reverse operations remain unchanged.
6. The mechanism must remain lightweight and must not become a second queue, task database, scheduler, or permanent agent-role system.

## 3. Authority model

Existing authority remains unchanged:

- owning Issue / Work Order: durable task truth, scope, acceptance, checkpoint definitions, readiness, dependencies and blockers;
- Task Checkpoint Cursor: current first-unfinished checkpoint projection only;
- Execution Session Record: one worker/session's current execution scope, provenance, bounded plan, `Last-Checkpoint`, `Next-Action`, blocker and handoff;
- branch / PR / Actions / tests: implementation and verification evidence;
- Formal Review: exact-SHA review evidence;
- execution-coordinator runtime state: atomic claim/lease/generation/fencing authority when actually used;
- devflow Repository Control: cross-repository summary/index;
- GitHub Project: display only;
- chat: never durable resume authority.

If the cursor conflicts with the owning Issue, accepted PR/check evidence, repository-local canon, or a live execution-coordinator claim, the cursor is reconciled from those authoritative surfaces. The cursor never overrides them.

A cursor that points to checkpoint `X` means only “`X` is the first unfinished recovery unit.” It does **not** mean `X` is currently runnable. `BLOCKED`, `WAITING`, dependency, review, Human, security and other readiness gates remain owned by their existing authoritative surfaces.

## 4. Storage decision

### 4.1 Selected: one dedicated task-owned Issue comment

Each eligible owning Issue / Work Order MAY have exactly one recognized cursor comment containing the sentinel:

```text
<!-- devflow-task-checkpoint-cursor:v1 -->
```

The comment is task-owned, not worker-owned. Different authorized workers may update the same cursor comment after re-reading live state. This is intentionally different from Execution Session Records, which remain worker/session-owned.

A recognized cursor comment must be on the owning Issue and come from a trusted write-capable source. On public repositories, a same-repository comment from an `OWNER`, `MEMBER`, or `COLLABORATOR` is trusted. A future GitHub Actions adapter may also create/update the canonical comment as `github-actions[bot]` when the workflow runs with repository-authorized Issue write permission. Untrusted comments that copy the sentinel are ignored and reported as spoof/noise rather than treated as cursor authority.

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

````markdown
<!-- devflow-task-checkpoint-cursor:v1 -->

# Task Checkpoint Cursor

```yaml
schema_version: 1
task: kinoko34077/example#123
revision: 7
last_completed: S1.2
first_unfinished: S1.3
head: 0123456789abcdef0123456789abcdef01234567
evidence:
  - https://github.com/kinoko34077/example/actions/runs/123456
updated_at: 2026-09-29T13:30:00Z
```
````

Field semantics:

- `schema_version`: fixed integer `1`.
- `task`: exact owning `owner/repository#issue` identity.
- `revision`: monotonically increasing cursor revision used only to detect observed drift; it is not a lock, compare-and-swap guarantee, or fencing token.
- `last_completed`: checkpoint identifier most recently accepted; nullable before the first checkpoint.
- `first_unfinished`: checkpoint identifier the next worker should resume from; nullable only when the checkpoint sequence is terminal. It does not imply readiness to execute.
- `head`: optional exact full 40-hex branch/PR/default-branch SHA relevant to the accepted movement.
- `evidence`: optional compact references supporting the movement; not a replacement for PR/Actions/Review evidence.
- `updated_at`: UTC timestamp for navigation/debugging; GitHub comment metadata remains the authoritative modification time.

Canonical numeric spelling for `schema_version` and `revision` is canonical positive base-10 decimal only, with no sign, underscore/separator or extra scalar whitespace. Evidence items are single-line data and may not contain the cursor sentinel or begin with a fenced-block token; these constraints prevent a writer from emitting framing that the canonical parser cannot safely read back.

No worker/session identity is stored in the cursor. Worker provenance stays in Execution Session Records.

## 6. Checkpoint definition

Checkpoint identifiers are owned by the task's durable plan/checklist. The cursor does not invent them and v1 does not infer ordering from identifier spelling.

Checkpoint identifiers used by a cursor MUST be unique within the owning task and stable once published. A checkpoint identifier already referenced by a cursor or durable evidence must not later be reused for a different semantic unit. If the task plan changes materially, introduce a new identifier or explicitly reconcile the cursor against the revised plan.

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

### 6.1 Single-frontier constraint

v1 represents exactly one **canonical recovery frontier** per owning task: one `first_unfinished` checkpoint.

It does not model multiple simultaneously runnable branches. When an owning task contains independently progressing parallel units, use the existing devflow decomposition rules:

- split independently recoverable units into bounded child/owner Issues when separate ownership is warranted; or
- keep the full parallel checklist in a progress ledger while designating one canonical task-level recovery frontier for the cursor.

Do not create one cursor per worker or multiple competing cursors on one owning Issue in v1. If no single canonical recovery frontier can be defined without losing material state, the task is not eligible for a v1 cursor until it is decomposed or its progress ledger defines one.

## 7. Worker read/resume contract

For an eligible task, resume order becomes:

1. read normal devflow/repository authority;
2. open the owning Issue / Work Order;
3. locate the unique recognized v1 cursor comment;
4. read the cursor before reconstructing historical progress;
5. verify the referenced checkpoint still exists in the owning task and compare only the live evidence needed for that checkpoint;
6. inspect relevant Execution Session Records for active overlap/provenance;
7. verify the owning task's current readiness, dependency, blocker and safety gates;
8. resume from `first_unfinished` when the checkpoint is runnable, or remain at that checkpoint while the authoritative blocker/gate remains unresolved.

A successor MUST NOT replay an earlier accepted checkpoint solely because chat history, Memory, or the predecessor session disappeared.

Missing cursor is not an error for legacy or trivial tasks. The worker falls back to the existing Issue/Session/PR resume path and may initialize a cursor when the task qualifies and the next unfinished checkpoint is unambiguous.

## 8. Cursor movement

### 8.1 Initialization

When an eligible task has no recognized cursor and its canonical recovery frontier is unambiguous, `initialize` creates the first cursor with:

- `revision: 1`;
- `last_completed`: the latest accepted checkpoint, or `null` when none is complete;
- `first_unfinished`: the first unfinished checkpoint, or `null` only when terminal;
- optional head/evidence references;
- `updated_at`.

Initialization must be derived from the owning task and live evidence. It must not guess a frontier from chat history or from checkpoint identifier spelling.

If multiple trusted cursor comments already exist, initialization is not used; return `WARN_DUPLICATE_MARKER` and reconcile.

### 8.2 Normal advance

Before moving the cursor, the worker re-reads the live cursor and the evidence that establishes completion of the current checkpoint.

A normal advance provides at least:

- expected `revision`;
- expected `first_unfinished`;
- completed checkpoint;
- next `first_unfinished` or terminal `null`;
- optional head/evidence references.

If expected and live state match at comparison time, the helper prepares an update that sets:

- `last_completed` to the completed checkpoint;
- `first_unfinished` to the next checkpoint;
- `revision` to live revision + 1;
- optional head/evidence;
- `updated_at`.

After a clean expected/live match, a non-terminal next frontier must differ from the completed checkpoint; a no-op frontier is invalid through normal advance and correction uses explicit `reconcile`. Stale live checkpoint/revision drift is classified before this no-op check so ordinary stale-worker drift remains advisory.

The GitHub comment transport is not an atomic execution lock. A transport adapter MUST re-read immediately before update and MUST re-read after update when the transport allows it. Any observed difference between expected, written, and post-write live state becomes drift and sends the worker back through live-state reconciliation. Atomic ownership remains an execution-coordinator responsibility when that runtime is used.

### 8.3 Drift is advisory by default

A revision/checkpoint mismatch does not by itself prove unsafe work. v1 also does not guess whether arbitrary checkpoint identifiers are globally “ahead” or “behind.” The helper returns the observed expected/live difference and leaves the worker responsible for reading the task's actual checkpoint order and evidence.

Required outcomes:

- `OK_INITIALIZED`: no recognized cursor existed and the verified initial cursor was created.
- `OK_ADVANCED`: expected cursor matched at comparison time, the requested forward update was written, and the post-write read still reflects that update when post-write verification is available.
- `WARN_CHECKPOINT_DRIFT`: live `first_unfinished` differs from the worker's expected checkpoint. Re-read the owning task, cursor, relevant evidence and current sessions; normally adopt the live cursor when the task proves another worker already advanced it.
- `WARN_REVISION_DRIFT`: revision changed while the same checkpoint still appears current. Re-read cursor/evidence before continuing.
- `WARN_POST_WRITE_DRIFT`: the adapter wrote an intended update but the immediate post-write live cursor differs from the written state. Re-read the owning task/evidence and reconcile; do not report the advance as cleanly accepted.
- `WARN_DUPLICATE_MARKER`: more than one trusted recognized marker exists. Determine the canonical marker from live task/evidence and reconcile.
- `WARN_MALFORMED_MARKER`: recognized marker cannot be parsed or violates v1 invariants. Reconstruct from durable task/evidence before replacing it.
- `WARN_UNTRUSTED_MARKER`: an untrusted comment copies the cursor sentinel. Ignore it for resume decisions and report the spoof/noise.
- `NO_MARKER`: use legacy resume logic or `initialize` only when the task qualifies and state is unambiguous.

Ordinary warning outcomes MUST NOT be described as runtime claim rejection or fencing failure.

## 9. Reconciliation and backward movement

A normal `advance` operation never intentionally moves the cursor backward and never treats an observed mismatch as authority to overwrite live state.

If live evidence demonstrates the cursor is wrong, the worker uses an explicit `reconcile` operation after recording the reason on the owning Issue or in the cursor update evidence. Reconciliation may:

- repair malformed fields;
- select one canonical marker when duplicates exist;
- move `first_unfinished` backward when previously accepted progress was invalidated;
- move directly forward when the cursor failed to record already-accepted evidence;
- reset head/evidence references after task-plan changes.

Reconciliation increments `revision` and records a compact reason/evidence reference. It is a visible correction, not an implicit stale-writer overwrite.

Because v1 deliberately does not claim atomic compare-and-swap semantics for Issue comments, a rare concurrent write race can still require post-write reconciliation. The cursor remains a recoverable projection; owning task/evidence stays authoritative.

## 10. Warning versus hard stop

The cursor mechanism itself is intentionally advisory for normal concurrency/drift.

Examples that remain warning/re-read cases:

- another worker already completed the same checkpoint;
- revision changed during work;
- a successor started from an old chat summary;
- the live marker names a different checkpoint than the worker expected;
- a stale session record disagrees with the task-level cursor;
- post-write verification discovers that another writer changed the cursor.

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

- `read`: discover trusted recognized markers and parse the unique canonical cursor when possible;
- `compare`: compare expected revision/checkpoint with live cursor and return structured outcome plus expected/live data;
- `initialize`: create the first cursor from verified owning-task/evidence state when no marker exists and one canonical frontier is unambiguous;
- `advance`: perform the supported forward update only when the latest observed cursor matches the worker's expectation; otherwise return warning data;
- `reconcile`: explicitly replace/repair cursor state from verified durable evidence;
- `render`: produce canonical v1 comment text.

The pure transition/parser logic belongs in devflow and is testable without network access. GitHub transport is a thin adapter.

A GitHub Actions adapter MAY call the same helper and surface drift with GitHub warning annotations while keeping the job successful for ordinary drift. v1 correctness does not require installing a workflow into every managed repository. This avoids turning cursor adoption into a repository-wide workflow migration.

## 12. GitHub Actions behavior when used

When an Action adapter is present:

- ordinary `WARN_*` drift emits `::warning::` / job-summary guidance and does not fail the workflow solely because the cursor moved;
- `OK_INITIALIZED` / `OK_ADVANCED` update the canonical cursor comment and report the resulting revision/checkpoint;
- `WARN_POST_WRITE_DRIFT` reports that a write occurred but the resulting live state must be reconciled rather than presenting the advance as authoritative success;
- malformed/duplicate state reports warning plus reconciliation guidance rather than guessing;
- safety failures originating outside cursor semantics retain their existing failing behavior;
- Action concurrency may serialize cursor-update jobs in that adapter, but serialization is an optimization, not authority and not a lock contract.

## 13. Interaction with Execution Session Records

Cursor and Session Records answer different questions:

```text
Task Checkpoint Cursor
= where the task resumes

Execution Session Record
= who/session is currently working on what bounded scope, with provenance and handoff state
```

A session's `Next-Action` SHOULD normally agree with the task cursor for the slice it owns. If they differ, the worker reads live evidence and resolves the discrepancy; it does not automatically overwrite either record.

A dead/stale Session Record therefore does not erase task position. The cursor remains at the first unfinished task checkpoint and a successor session can continue from there when the checkpoint is otherwise runnable.

## 14. Interaction with progress-ledger Issues

A dedicated progress ledger such as `devflow#232` may continue to hold the full ordered checkpoint list, stage acceptance, blockers and evidence. The cursor is a compact projection of that ledger's single canonical first-unfinished recovery frontier.

The progress ledger remains useful when the task has many independently recoverable units. The cursor removes the need for a successor to infer the canonical current position by scanning the full ledger first.

If ledger and cursor disagree, ledger/owning-task evidence governs and the cursor is reconciled.

If the ledger intentionally exposes multiple simultaneously active independent frontiers, either select and document one canonical task-level recovery frontier or split those units into separately owned tasks; v1 does not encode several parallel frontiers in one cursor.

## 15. Initial implementation scope

The first implementation should remain bounded:

1. add a small parser/renderer/transition module for cursor v1;
2. add tests for valid read/render, initialization, normal advance, checkpoint drift, revision drift, post-write drift, duplicate marker, malformed marker, untrusted marker, missing marker and explicit reconcile;
3. update canonical devflow docs and `.devflow/WORKFLOW.yaml` with the cursor ownership/resume/readiness contract and single-frontier constraint;
4. update `AGENTS.md` / operating manuals so eligible resume reads cursor before reconstructing historical checkpoints while still checking task readiness/blockers;
5. provide one devflow-local reference/pilot adapter or documented GitHub API path only if needed to prove comment create/update and post-write verification behavior;
6. pilot against a bounded devflow-owned progress Issue before broader adoption.

Do not require a cross-repository credential/App/permission change for v1.

## 16. Acceptance

The design is accepted when implementation can demonstrate all of the following:

- a task has exactly one trusted recognized cursor or a typed missing/duplicate/untrusted condition;
- checkpoint IDs referenced by the cursor remain stable and are not silently repurposed;
- the cursor directly yields one canonical first unfinished recovery frontier;
- the cursor does not imply that the checkpoint is currently runnable and existing blocker/dependency/safety gates remain authoritative;
- interruption followed by a new worker resumes from that checkpoint when runnable;
- already-accepted earlier checkpoints are not replayed solely because session/chat context vanished;
- stale/duplicate expected position produces a structured warning with expected/live data and a re-read path rather than ordinary hard rejection;
- post-write races produce `WARN_POST_WRITE_DRIFT` rather than false clean success;
- explicit reconciliation can correct a wrong cursor without hiding that correction;
- normal advance never intentionally rewinds an observed cursor; any concurrent transport race remains detectable/recoverable from authoritative task evidence rather than being misrepresented as atomic exclusion;
- Execution Session and execution-coordinator authority remain distinct;
- Project remains display-only;
- existing Human/security/merge/review safety gates remain unchanged;
- no heavy queue/scheduler/mandatory per-repository workflow is introduced.

## 17. Rejected expansion for v1

Do not add in v1 without evidence from the pilot:

- weighted scheduling or fairness logic;
- automatic checkpoint generation by an LLM;
- one cursor per worker;
- multiple simultaneous task-level cursors for parallel branches;
- automatic rollback based only on cursor mismatch;
- mandatory GitHub App installation changes;
- cursor state in GitHub Project fields;
- a separate durable database;
- hard rejection for ordinary checkpoint/revision drift;
- per-command or per-tool-call checkpoints.
