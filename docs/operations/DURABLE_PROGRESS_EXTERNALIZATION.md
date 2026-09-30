# Durable Progress Externalization

Status: Standing operational policy
Standing summary: `devflow#49` (this checked-in document is the canonical static contract)
Change tracking: `devflow#236`

## 1. Purpose

Agent work must remain recoverable when a chat, tool session, worker process, provider context, or local execution path disappears.

For GitHub-backed work, durable progress is therefore an execution precondition rather than an end-of-task reporting convenience.

The rule is designed to prevent two failure modes:

1. completed work becomes practically unusable because no explicit resume position survived;
2. a successor reconstructs state from indirect artifacts or chat, creating speculation and unnecessary re-verification.

## 2. Priority

Within already-authorized work, use this order:

```text
Safety / explicit Human gate
> durable progress externalization
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
- an accepted task checkpoint cursor as a compact projection when that mechanism is available.

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
4. only then begin the next unit.

Do not use "write progress at the end" or "write progress when replying in chat" as the normal schedule.

Checkpoint externalization precedes the next material unit.

## 7. Working notes are allowed

The progress surface may also contain concise temporary material such as:

- `NOTE` — useful scratch context;
- `HYPOTHESIS` — unconfirmed explanation;
- `UNVERIFIED` — observation not yet accepted as evidence;
- partial findings;
- command/run/artifact references;
- failed-path notes that prevent a successor from repeating useless work.

Temporary notes do not become specification, Current State, accepted finding, or verification evidence merely by being written there. Promote only accepted durable information to the surface that owns it.

## 8. Missing or stale progress is an operational defect

If qualifying work has no usable durable progress surface, or the latest checkpoint / first unfinished action is ambiguous:

- do not discard existing artifacts;
- do not guess from chat and continue broad mutation/review/audit;
- inspect the live owning Issue, branch, PR, exact head, checks, Reviews, and task evidence only as far as needed to reconcile the position;
- establish or repair the durable progress surface;
- then continue from the resolved first unfinished unit.

This is fail-to-reconcile, not fail-to-work: ordinary missing progress does not invalidate accepted artifacts, but it must be repaired before broad continuation.

## 9. Resume and re-verification

A successor starts from the latest explicit durable checkpoint and first unfinished action.

Already accepted earlier units are not repeated solely because previous chat/provider state disappeared.

Re-observation or re-verification after resume should be bounded to:

- volatile state such as current head, CI/check status, Review status, lease/claim state, or external dependency state;
- scope changed after the checkpoint;
- concrete drift, inconsistency, missing evidence, or invalidated acceptance.

Do not rerun the entire historical workflow just to gain confidence after context loss.

## 10. Relation to other devflow records

- Owning Issue / Work Order: durable task truth, scope, acceptance and blocker authority.
- Durable progress surface: recoverable execution position and temporary working context.
- Execution Session Record: worker/session provenance, bounded scope and active handoff/collision state.
- Task Checkpoint Cursor: compact first-unfinished navigation/drift projection when implemented; it does not replace the progress surface or evidence.
- PR / Actions / tests / Formal Review: concrete diff and verification/review evidence.
- Repository Current State/specification: accepted repository-level state and durable requirements/design, not temporary progress chronology.

## 11. Chat behavior

Chat may remain concise and need not duplicate the full ledger.

However, chat concision is never a reason to omit GitHub externalization. The durable record must exist independently of whether progress is mentioned in the user-facing reply.

Standing operational detail is also summarized in `devflow#49`.
