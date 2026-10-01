# Task Checkpoint Cursor v1

Status: Required for eligible single-frontier multi-step work; otherwise not applicable / optional  
Owning specification: `docs/superpowers/specs/2026-09-29-task-checkpoint-cursor-design.md`  
Current-main reconciliation: `docs/superpowers/specs/2026-09-30-task-checkpoint-cursor-v1-reconciliation.md`  
Pure helper: `tools/task_checkpoint_cursor.py`

## 1. Purpose

A Task Checkpoint Cursor is a compact projection of one owning Issue / Work Order's current recovery position. Its only task-level question is:

> What is the `first_unfinished` recovery-relevant checkpoint now?

The cursor lets a successor locate the current frontier before reconstructing historical checkpoint chronology. It is intentionally the **structural locator**, not the detailed progress log. The owning task's designated durable progress surface supplies the detailed checkpoint history, evidence, findings, decisions and blockers. A successor uses the Cursor to find **where**, then the progress surface to understand **what happened there**. It remains subordinate to the owning task, durable progress surface, current PR/check/Review evidence, repository canon and any live execution-coordinator claim.

The cursor is **not readiness authority**. It is also **not claim, lease, lock, CAS, or fencing authority**. A cursor naming checkpoint `X` means only that `X` is the projected first unfinished recovery unit; existing blocker, dependency, Human, security, Review, CI, publication, credential/session/permission and destructive-operation gates still govern whether `X` may run.

## 2. Eligibility and single-frontier rule

v1 represents exactly one **single canonical recovery frontier** per owning task.

For durable multi-step work, a cursor is required when the task or its durable progress ledger can identify one canonical `first_unfinished` checkpoint without losing material parallel state. Initialize or reuse it on the owning Issue / Work Order before entering the next materially distinct recovery unit. If independently progressing units have separate frontiers, split them into separately owned bounded tasks or retain the complete parallel state in the durable progress surface and designate one canonical task-level frontier.

Do not create one cursor per worker. Do not use multiple competing trusted cursor comments on one owning Issue. A dedicated progress Issue / ledger may coexist with the cursor and is often the correct place for detailed progress; the cursor itself remains a trusted comment on the owning task and should reference the designated progress surface/checkpoint in `evidence` when practical.

A missing cursor does not invalidate already accepted work. On an eligible task it is an operational gap: recover the unambiguous frontier from live durable evidence, initialize/reconcile the cursor, then continue. On genuinely parallel/ambiguous work where one frontier would lose material state, use the ordinary durable-progress resume path until one canonical frontier exists.

## 3. Recognized Issue comment

The canonical v1 comment contains exactly one sentinel:

```text
<!-- devflow-task-checkpoint-cursor:v1 -->
```

followed by one canonical fenced `yaml` block. Example:

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
updated_at: 2026-09-30T04:30:00Z
```
````

Field rules are enforced by `tools/task_checkpoint_cursor.py`. In particular:

- checkpoint identifiers are stable ASCII tokens and identifier spelling does not imply order;
- `schema_version` and `revision` use canonical positive base-10 decimal tokens only: no sign, underscore/separator, or extra scalar whitespace;
- `head` is either `null` or a full 40-hex exact SHA;
- `evidence` items are single-line data and may not contain the cursor sentinel or begin with a fenced-block token such as triple backticks;
- `updated_at` is UTC `Z` time.

These writer-side restrictions ensure `render_cursor_comment()` does not emit a cursor body that the canonical parser cannot safely recognize as one cursor.

## 4. Trust boundary

On a public repository, recognize a marker as trusted when its owning-Issue comment has GitHub `author_association` `OWNER`, `MEMBER`, or `COLLABORATOR`. A repository-authorized `github-actions[bot]` cursor may also be trusted by the helper contract.

An untrusted comment copying the sentinel is noise, not task authority. Surface `WARN_UNTRUSTED_MARKER`, ignore it for resume position, and continue evaluating any unique trusted marker.

More than one trusted recognized marker is never silently ordered by comment age, revision or author. Return `WARN_DUPLICATE_MARKER` and reconcile explicitly from live durable evidence.

## 5. Read and resume

For a task with an accepted cursor:

1. read normal devflow/repository authority and the owning Issue / Work Order;
2. inspect the owning Issue comments for the unique trusted cursor;
3. read `first_unfinished` first to identify the roadmap/current-position frontier;
4. follow the owning task's durable reference to the designated progress surface and read the detailed progress/evidence for that frontier;
5. inspect active Session overlap plus only the current volatile head/check/Review/blocker/dependency/readiness/safety evidence needed for that frontier;
6. resume there when runnable;
7. if cursor and progress surface disagree, warn, re-read live evidence and reconcile both layers rather than choosing one silently or replaying accepted history.

The worker performs this discovery itself. A user reminder containing the progress Issue number, cursor sentinel, or current checkpoint is not a prerequisite for correct resume behavior.

Chat, Memory and GitHub Project fields are not resume authority.

## 6. Initialize

When there is `NO_MARKER` and the owning durable state plus its designated progress surface expose one unambiguous frontier, initialize revision `1` from that state before the next materially distinct recovery unit. Include the durable progress surface/current checkpoint reference in `evidence` when practical so the compact locator and detailed progress remain connected.

Initialization must not infer a checkpoint from chat history or checkpoint-name ordering. If a trusted marker already exists, use normal read/compare semantics. If multiple trusted markers exist, return `WARN_DUPLICATE_MARKER` and reconcile instead of initializing another marker.

The pure helper prepares the initial `CursorState`; the caller writes the canonical comment and immediately re-reads it when transport permits. If the readback exactly equals the intended initial state, classify `OK_INITIALIZED`. Any different canonical state is `WARN_POST_WRITE_DRIFT` and must be reconciled rather than reported as clean initialization.

## 7. Compare and advance

Before movement, re-read the live cursor and the evidence establishing completion of its current `first_unfinished` checkpoint.

Compare the worker's expected revision and expected `first_unfinished` with the live cursor:

- exact match -> movement may be prepared;
- different checkpoint -> `WARN_CHECKPOINT_DRIFT`;
- same checkpoint but different revision -> `WARN_REVISION_DRIFT`.

Checkpoint drift takes precedence because v1 does not infer global order from identifier spelling.

A normal advance:

1. requires the completed checkpoint to equal the expected current `first_unfinished`;
2. requires a non-terminal next `first_unfinished` to differ from the completed checkpoint; a no-op frontier is not a normal advance;
3. increments live `revision` by one;
4. sets `last_completed` to the completed checkpoint;
5. sets the next `first_unfinished` or terminal `null`;
6. records compact exact-head/evidence references where useful;
7. writes the canonical replacement comment through the caller's GitHub transport;
8. immediately re-reads the comment when transport permits.

If authoritative evidence requires correction without a forward frontier movement, use explicit reconciliation rather than manufacturing an advance revision.

The pure helper prepares/classifies state; it performs no GitHub network write.

## 8. Post-write verification

If an advance readback exactly matches the written canonical state, classify `OK_ADVANCED`. If an initialization readback exactly matches the intended initial state, classify `OK_INITIALIZED`.

If any canonical field differs, classify `WARN_POST_WRITE_DRIFT`. A write occurred, but the movement must not be reported as clean acceptance. Re-read the owning task/evidence and reconcile.

Issue-comment transport is intentionally not presented as atomic CAS. Serialization by an optional Action may reduce races but does not create task ownership authority.

## 9. Explicit reconciliation

Use explicit reconciliation when authoritative durable evidence proves the cursor projection is wrong. Reconciliation may repair malformed state, select one canonical marker after duplicates, move a frontier backward after invalidated acceptance, move it forward after a missed projection update, or replace stale head/evidence references.

Record the reason/evidence on the owning task. Reconciliation increments the revision and remains visible as a correction rather than hiding a stale overwrite.

When an accepted transition changes the projected frontier, the cursor is one of the directly affected durable surfaces and must be reconciled before that bounded unit exits.

## 10. Outcomes

The v1 helper uses these operational outcomes:

- `OK_CURSOR` — one trusted valid cursor was found;
- `NO_MARKER` — no trusted cursor exists;
- `OK_INITIALIZED` — initial-create readback equals the intended initial cursor;
- `OK_MATCH` — expected and live position match;
- `OK_PREPARED` — a forward replacement state was prepared after a clean comparison;
- `OK_ADVANCED` — advance readback equals the intended state;
- `WARN_CHECKPOINT_DRIFT` — live checkpoint differs from expected;
- `WARN_REVISION_DRIFT` — revision differs while checkpoint is unchanged;
- `WARN_POST_WRITE_DRIFT` — post-write live state differs from the intended write;
- `WARN_DUPLICATE_MARKER` — multiple trusted markers exist;
- `WARN_MALFORMED_MARKER` — one trusted recognized marker violates v1 format;
- `WARN_UNTRUSTED_MARKER` — an untrusted comment copied the sentinel.

Ordinary `WARN_*` outcomes mean re-observe/reconcile. They are not execution-coordinator fencing failures and do not by themselves hard-reject normal work.

## 11. Relation to durable progress and Sessions

The owning Issue / Work Order owns task truth. The durable progress surface owns detailed recoverable progress, evidence, findings, decisions, blockers and enough context to continue. The Task Checkpoint Cursor is required for eligible single-frontier multi-step work and is the compact structural current-position projection that complements that durable state. The Execution Session Record owns worker/session provenance, bounded scope and collision/handoff state. PR/Actions/tests/Formal Review own concrete implementation and verification evidence.

The cursor does not replace the durable progress surface or its evidence. A dead/stale Session does not erase the task frontier; a successor reads the live durable state and cursor, checks collision/readiness, and continues from the current frontier.

Canonical standing policy: `docs/operations/DURABLE_PROGRESS_EXTERNALIZATION.md`.
