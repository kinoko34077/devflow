# Durable Progress Externalization

Status: Standing operational policy
Standing summary: `devflow#49` (this checked-in document is the canonical static contract)
Change tracking: `devflow#251`, `devflow#233`

## 1. Purpose

Agent work must remain recoverable when a chat, tool session, worker process, provider context, or local execution path disappears.

For GitHub-backed work, durable progress is therefore an execution precondition rather than an end-of-task reporting convenience.

The rule is designed to prevent three failure modes:

1. completed work becomes practically unusable because no explicit resume position survived;
2. a successor reconstructs state from indirect artifacts or chat, creating speculation and unnecessary re-verification;
3. an accepted transition leaves directly affected Issues, Controls, Current State or routing records stale, forcing later audit workers to rediscover and repair producer-owned drift.

## 2. Priority

Within already-authorized work, use this order:

```text
Safety / explicit Human gate
> durable progress externalization and affected-surface reconciliation
> throughput / shortest-path / convenience / chat concision
```

This policy never authorizes release/deploy/publication, destructive operations, credential/session/permission changes, shared-history rewrite, or other security-sensitive/difficult-to-reverse operations that require explicit confirmation.

## 3. When a durable progress surface is mandatory

When a GitHub repository exists, create or reuse one durable GitHub progress surface before substantive continuation if the work involves any of:

- mutation or implementation;
- review or verification;
- audit or investigation;
- more than one recovery-relevant step/tool call/turn;
- material reconstruction or re-verification cost after interruption;
- likely continuation by another worker.

A single-step read-only lookup with no continuation/recovery value is exempt. If it grows into multi-step or continuation-relevant work, externalize progress immediately before continuing.

## 4. Allowed surfaces

Use the narrowest owning surface that survives interruption:

- existing owning Issue / Work Order;
- trusted comment on that Issue / Work Order;
- dedicated bounded progress Issue/ledger when it improves recovery;
- an accepted Task Checkpoint Cursor as an **optional compact projection** when that mechanism is available; it **does not replace the durable progress surface**.

Do not create one Issue per checkpoint. Prefer updating one progress surface for one bounded operation unless independent completion, handoff, or acceptance justifies decomposition.

Chat, Memory, provider summaries, and GitHub Project fields are not durable progress authority.

## 5. Minimum recoverable state

The progress surface must allow a successor to recover at least:

- `Scope` / `Excludes`;
- latest completed checkpoint / `Last-Checkpoint`;
- first unfinished action / `Next-Action`;
- branch / PR / exact head when applicable;
- current `Blocker`;
- compact evidence references needed to understand accepted completion.

Exact field spelling may follow the owning repository's format. The information, not one universal template, is mandatory.

## 6. Update ordering

Before crossing into the next materially distinct recovery unit:

1. finish the current bounded unit;
2. externalize its accepted/result state to the durable progress surface;
3. set the first unfinished next action;
4. reconcile the directly affected durable surfaces when the accepted transition would otherwise leave them stale, contradictory, or misleading;
5. only then begin the next unit.

Do not use "write progress at the end", "clean it up later", or "write progress when replying in chat" as the normal schedule.

Checkpoint externalization and affected-surface reconciliation precede the next material unit.

## 7. Affected-surface reconciliation before exit

The worker that causes an accepted state transition owns the cleanup of the finite set of durable surfaces made stale, contradictory, or concretely suspect by that transition.

Before entering the next materially distinct unit, or before leaving the current task as `DONE`, `RELEASED`, `HANDOFF`, `WAITING`, or equivalent, inspect the directly affected surfaces as applicable. Typical members of this affected set include:

- owning Issue / Work Order `Work Status`, `Blocker`, acceptance and `Next Action`;
- durable progress ledger / checkpoint;
- Task Checkpoint Cursor when its projected frontier changes;
- Execution Session state;
- branch / PR / accepted exact-head references;
- parent, child or dependency Issues whose current routing changed;
- active-work, candidate, supply or routing projections that still advertise retired work;
- repository Current State when accepted repository-level state changed;
- specification / ADR when accepted durable requirements or design changed;
- Repository Control when the cross-repository summary changed.

When a cursor frontier changes, that cursor is a **directly affected durable surface** and must be reconciled before the bounded unit exits.

This is not a full-repository or all-Issue sweep. The closure set is bounded to surfaces that the current transition directly changed or gave a concrete reason to suspect are stale.

When an in-scope stale status, resolved blocker, obsolete route/reference, or contradictory current-state projection can be corrected safely within existing authority, correct it as part of the bounded unit before exit.

Do not take over another active worker's semantic scope, cross a Human/security/permission gate, or absorb an independent unrelated defect merely because it was discovered during reconciliation. Instead, leave a durable finding/reference on the appropriate owning surface.

A bounded unit is not operationally complete until:

1. its target change or disposition is accepted;
2. required verification/review evidence is current;
3. its durable checkpoint is current;
4. directly affected durable projections agree with the accepted state transition.

Cross-repository or periodic consistency audits are a backstop for missed drift, interaction defects and policy gaps. They are not the routine garbage collector for stale state produced by ordinary workers.

## 8. Working notes are allowed

The progress surface may also contain concise temporary material such as:

- `NOTE` — useful scratch context;
- `HYPOTHESIS` — unconfirmed explanation;
- `UNVERIFIED` — observation not yet accepted as evidence;
- partial findings;
- command/run/artifact references;
- failed-path notes that prevent a successor from repeating useless work.

Temporary notes do not become specification, Current State, accepted finding, or verification evidence merely by being written there. Promote only accepted durable information to the surface that owns it.

## 9. Missing or stale progress is an operational defect

If qualifying work has no usable durable progress surface, or the latest checkpoint / first unfinished action is ambiguous:

- do not discard existing artifacts;
- do not guess from chat and continue broad mutation/review/audit;
- inspect the live owning Issue, branch, PR, exact head, checks, Reviews, and task evidence only as far as needed to reconcile the position;
- establish or repair the durable progress surface;
- then continue from the resolved first unfinished unit.

This is fail-to-reconcile, not fail-to-work: ordinary missing progress does not invalidate accepted artifacts, but it must be repaired before broad continuation.

## 10. Resume and re-verification

A successor starts from the latest explicit durable checkpoint and first unfinished action.

When an accepted Task Checkpoint Cursor exists, use its `first_unfinished` value as the compact resume projection before reconstructing historical checkpoint chronology. Validate that projection against the owning task, current durable progress surface, volatile evidence, active Session overlap, and current readiness/safety gates. Cursor drift means warn/re-read/reconcile; it does not authorize replay or hard rejection by itself.

Already accepted earlier units are not repeated solely because previous chat/provider state disappeared.

Re-observation or re-verification after resume should be bounded to:

- volatile state such as current head, CI/check status, Review status, lease/claim state, or external dependency state;
- scope changed after the checkpoint;
- concrete drift, inconsistency, missing evidence, or invalidated acceptance.

Do not rerun the entire historical workflow just to gain confidence after context loss.

Detailed cursor procedure: `docs/operations/TASK_CHECKPOINT_CURSOR.md`.

## 11. Relation to other devflow records

- Owning Issue / Work Order: durable task truth, scope, acceptance and blocker authority.
- Durable progress surface: recoverable execution position and temporary working context.
- Execution Session Record: worker/session provenance, bounded scope and active handoff/collision state.
- Task Checkpoint Cursor: optional compact first-unfinished navigation/drift projection; it does not replace the durable progress surface or evidence and is not readiness/claim authority.
- PR / Actions / tests / Formal Review: concrete diff and verification/review evidence.
- Repository Current State/specification: accepted repository-level state and durable requirements/design, not temporary progress chronology.
- Repository Control: cross-repository summary projection that must be reconciled when the accepted transition changes the summary it owns.

## 12. Chat behavior

Chat may remain concise and need not duplicate the full ledger.

However, chat concision is never a reason to omit GitHub externalization or affected-surface reconciliation. The durable record and directly affected projections must be coherent independently of whether progress is mentioned in the user-facing reply.

Standing operational detail is also summarized in `devflow#49`.