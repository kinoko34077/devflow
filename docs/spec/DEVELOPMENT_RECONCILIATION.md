# Development Reconciliation Contract

Status: proposed for acceptance under devflow#156  
Authority: devflow cross-repository workflow specification  
Scope: deterministic assessment of durable GitHub evidence

This document defines the smallest shared contract for the Development Reconciliation Loop. It is a derived decision contract: it does not become a second task database, worker-session authority, PR state, or runtime claim/lease system.

## 1. Authority and processing model

A reconciler evaluates an immutable observation of live evidence and returns a derived disposition plus, when safe, a bounded next transition:

```text
observed evidence
  -> validated facts
  -> deterministic disposition
  -> bounded transition request
  -> re-observe before mutation
```

The owning Issue/Work Order remains durable task truth. PRs, Actions/checks and Formal Reviews remain implementation/verification evidence. Manual Execution Session records remain worker-owned provenance. Execution-coordinator remains runtime claim/lease/generation authority. Project and chat are never inputs that manufacture authority.

A transition request is permission to attempt one named operation after a final re-read; it is not a completed mutation. Any executor must compare the requested task identity, PR head and relevant evidence again immediately before changing durable state.

## 2. Evidence contract

Each input is represented as:

```text
source, observed_identity, observed_at, source_revision, freshness_result, value
```

The reconciler MUST reject an input whose `observed_identity` is not the requested repository/object identity. It MUST also reject an input that is absent, stale, contradictory or untrusted when that input is required by the applicable rule.

| Evidence | Required facts | Freshness / validation |
| --- | --- | --- |
| Owning Issue/Work Order | repository, number, state, body/acceptance, current task references | exact repository/Issue identity; body revision or equivalent observation recorded |
| Repository Control | managed repository, Work Status, Repository State, Active Work, gates, candidate envelope when applicable | exact devflow Control identity; accepted Audit SHA/current head relation recorded |
| Pull Request | repository, number, state, base/head SHA, mergeability | exact repository/PR identity; head is the candidate under assessment |
| Required checks | check identity, conclusion, head SHA, requiredness | success must be for the assessed head; queued/running or absent required checks are not success |
| Formal Review | reviewer, review state, reviewed commit SHA, blocking finding/thread status | review must cover the assessed head; unresolved `REQUEST_CHANGES` or blocking finding fails closed |
| Review policy | whether the Issue/Work Order or accepted policy requires an independent reviewer | read from accepted policy/owning task, never inferred from Project or prose heuristics |
| Manual Execution Session | worker-owned status, checkpoint, branch/PR, last trusted update, linked activity | use #142/#144 stale rules; do not rewrite the worker record as a reconciler action |
| Human/confirmation gates | explicit release/deploy/publication, credential/session/permission, destructive, shared-history, protected-gate or difficult-to-reverse condition | a trusted explicit gate is blocking even when all CI/review evidence passes |
| External dependency | named provider/environment/manual condition and its current status | dependency must identify the condition and recheck signal; generic waiting is insufficient |

No global time-to-live is invented here. A producer must provide the applicable freshness policy or the result is `NEEDS_EVIDENCE`. For Manual Execution Sessions, `CLAIMED`/`RUNNING` becomes stale only after one hour with neither a trusted record update nor linked branch/PR/check activity after the recorded checkpoint; `WAITING` remains active while its named blocker exists, then follows the same rule.

## 3. Dispositions

The vocabulary is intentionally separate from Work Status, PR state, Review state and Session status.

- `AUTO_ADVANCE`: all required evidence is valid and a named reversible workflow transition is allowed.
- `NEEDS_REVIEWER`: an explicit different-reviewer requirement is unsatisfied.
- `NEEDS_RECOVERY`: a worker/session is stale or interrupted under the accepted Manual Execution Session rules and recovery assessment is warranted.
- `NEEDS_HUMAN`: a trusted explicit human/confirmation gate blocks automation.
- `WAIT_EXTERNAL`: a named external condition is unresolved and no safe transition is available yet.
- `NEEDS_EVIDENCE`: required evidence is absent, stale, untrusted or contradictory; the reconciler must not guess.
- `NO_ACTION`: no transition is currently warranted, including an active worker with no completed transition, an already reconciled terminal state, or an inapplicable task.

`NEEDS_EVIDENCE` is the only disposition added to the initial #156 candidates. It prevents missing/contradictory evidence from being collapsed into a human decision, external wait or ordinary no-op.

## 4. Deterministic evaluation order

The reconciler applies the first matching rule after identity validation. It emits all observed reason codes, but one disposition and at most one next transition.

1. If repository/object identity cannot be proven, or required evidence is missing, stale, untrusted or contradictory, return `NEEDS_EVIDENCE`.
2. If a trusted explicit human/confirmation gate is present, return `NEEDS_HUMAN`.
3. If a named external dependency is unresolved, return `WAIT_EXTERNAL`.
4. If an eligible Manual Execution Session is stale/interrupted and no newer trusted activity supersedes it, return `NEEDS_RECOVERY`.
5. If accepted review policy requires a different reviewer and that review is absent or not fresh for the assessed head, return `NEEDS_REVIEWER`.
6. If a merged PR has verified post-merge acceptance evidence and repository reconciliation remains, return `AUTO_ADVANCE` with the post-merge reconciliation transition.
7. If an open PR satisfies the automatic-advance rule below, return `AUTO_ADVANCE` with the bounded PR transition.
8. Otherwise return `NO_ACTION`.

A later rule never overrides an earlier evidence-integrity or safety boundary. Re-observation can produce a different result when the durable evidence changes.

## 5. Required transition rules

| Situation | Required conditions | Disposition | Bounded transition |
| --- | --- | --- | --- |
| Safe PR advance | owning task is open and acceptance is satisfied; PR is open; repository/PR/head identities match; required checks succeed for exact head; Formal Review is fresh for exact head; no unresolved blocking finding/thread; no explicit different-reviewer requirement; no human gate or external blocker | `AUTO_ADVANCE` | attempt the repository-approved merge/reconciliation using the expected head SHA; re-read before mutation |
| Different reviewer required | task/policy explicitly requires a different reviewer, and no qualifying fresh review exists for exact head | `NEEDS_REVIEWER` | publish one idempotent reviewer request containing task, PR, head and required evidence |
| Stale/interrupted worker | #142/#144 stale rule is met and no newer trusted branch/PR/check activity supersedes the checkpoint | `NEEDS_RECOVERY` | publish recovery assessment/request; preserve the worker-owned Session Record and provenance |
| Human gate | release/deploy/publication, credential/session/permission, destructive, shared-history, protected-gate or other difficult-to-reverse action is explicitly required | `NEEDS_HUMAN` | publish the exact decision required; do not perform or simulate the gated action |
| External wait | named CI, provider, environment, manual external system or other dependency is unresolved and its recheck signal is known | `WAIT_EXTERNAL` | record the named blocker and recheck condition; do not mutate task truth |
| Invalid evidence | required identity, freshness, required check/review, blocker state or authority relation is absent, stale, contradictory or untrusted | `NEEDS_EVIDENCE` | publish the missing/contradictory evidence request; do not infer a transition |
| Post-merge reconciliation | PR is merged with verified merge/head evidence; owning acceptance is verified; remaining operation is updating the owning Issue/Current State/Control summary | `AUTO_ADVANCE` | reconcile only the state owned by that repository; close/advance the owning task only when its acceptance is explicit |
| No transition | evidence is valid but a worker is actively progressing, the terminal state is already reconciled, or no rule applies | `NO_ACTION` | no durable mutation; retain reason codes and next observation trigger |
| Downstream publication | a stable `NEEDS_REVIEWER` or `NEEDS_RECOVERY` result is consumed by the publication child and has not already been emitted for the same evidence identity | same disposition | publish an idempotent reviewer/recovery work item; the producer may not consume its newly relaxed/publicized candidate in the same attempt |

The generic `AUTO_ADVANCE` result does not authorize release/deploy/publication, credential/session/permission changes, destructive deletion, shared-history rewrite, or another confirmation-gated operation. Such evidence must select `NEEDS_HUMAN` before transition evaluation reaches automatic advancement.

## 6. Facts, classifications and transitions

Implementations MUST keep these layers distinguishable:

- Facts: observed values and provenance, such as `pr.head_sha`, `checks.required=success`, or `session.last_activity_at`.
- Classifications: derived conclusions, such as `head_review_fresh`, `different_reviewer_required`, or `session_stale`.
- Transition: one disposition, reason-code list, expected evidence identity and optional bounded action.

A machine-readable result has this minimum shape:

```json
{
  "contract_version": "development-reconciliation.v1",
  "task_ref": "owner/repository#number",
  "observed_at": "RFC-3339 timestamp",
  "evidence_identity": {
    "repository": "owner/repository",
    "task_body_sha256": "exact digest when required",
    "pr_number": 0,
    "pr_head_sha": "exact head when applicable",
    "control_audit_sha": "accepted control SHA when applicable"
  },
  "disposition": "AUTO_ADVANCE",
  "reason_codes": ["REQUIRED_CHECKS_PASS", "FORMAL_REVIEW_FRESH"],
  "next_transition": {
    "kind": "MERGE_OR_RECONCILE",
    "expected_head_sha": "exact head",
    "recheck_before_mutation": true
  }
}
```

`next_transition` is omitted for `NO_ACTION`, `WAIT_EXTERNAL`, `NEEDS_HUMAN` and `NEEDS_EVIDENCE` unless it is a non-mutating observation/recheck request. A publication result must include an idempotency key derived from task identity, evidence identity, disposition and transition kind; it must never use title text, Project fields or chat text as authority.

## 7. Provenance, idempotency and recovery invariants

- Reconciliation is repeatable: the same validated evidence yields the same disposition and reason codes.
- Every mutating executor re-reads the evidence and uses an expected head/identity guard.
- A reconciler never writes `FAILED`, `HANDOFF` or another lifecycle state into a disappeared worker's Session Record.
- A recovery publication describes the evidence and requested assessment; the successor worker creates its own Session Record.
- A publication/addition/relaxation attempt cannot consume the same newly changed candidate in that execution attempt.
- Existing Work Status, Session Status, PR state, Review state and execution-coordinator claim state are referenced, not copied into a new state machine.
- Project/chat/prose heuristics cannot create a candidate or transition.
- If a mutation fails or the identity guard changes, return to observation and emit `NEEDS_EVIDENCE` or the newly applicable disposition; do not rewrite shared history.

## 8. Downstream conformance

#157, #158 and #159 may consume this contract only by:

1. reading the result and its evidence identity;
2. re-observing the same owning authority before mutation;
3. preserving the disposition/reason codes in their own durable Issue/PR evidence;
4. not introducing a second disposition vocabulary;
5. keeping their repository-specific implementation details in the owning repository.

A downstream implementation that needs a new disposition, evidence source or transition must update this contract first through a bounded devflow Issue/PR.

## 9. Acceptance checklist for devflow#156

- [ ] Every disposition is defined by observable evidence and deterministic conditions.
- [ ] Facts, derived classifications and executable transitions are distinguishable.
- [ ] Missing/stale/contradictory evidence fails closed as `NEEDS_EVIDENCE`.
- [ ] Review escalation follows accepted #111 semantics.
- [ ] Stale-session assessment preserves #142/#144 worker provenance.
- [ ] Runtime allocation authority remains outside this contract.
- [ ] The transition table covers success, reviewer wait, recovery, Human Gate, external wait, invalid evidence and post-merge reconciliation.
- [ ] #157/#158/#159 can consume this contract without inventing independent state vocabularies.

## Related authority

- devflow#155 — GitHub-native Development Reconciliation Loop parent
- devflow#111 — Formal Review policy
- devflow#142/#144 — Manual Execution Session semantics
- devflow#105/#125 — execution allocation/candidate-source authority
- devflow#151 — read-only portfolio projection design input

## 10. Stage-2 bounded maintenance producer contract

This section is the canonical contract extension owned by `devflow#264` under the staged lightweight-work authority `devflow#215/#232`.

Its purpose is to let Stage 2 automate deterministic `audit`, `triage`, and `sync-check` work without adding a second task database, disposition vocabulary, scheduler, claim authority, or semantic/LLM authority.

### 10.1 Reuse existing authorities

Stage-2 maintenance production reuses the existing layers rather than replacing them:

- this contract owns evidence validation, disposition precedence, bounded transition semantics, and fail-closed behavior;
- `DEVELOPMENT_RECONCILIATION_PUBLICATION.md` owns freshness-bound/idempotent reviewer/recovery work publications and Repository Control projection rules;
- the accepted durable-candidate source contract under `devflow#125` owns ordinary machine admission in the unique Repository Control and exact owning-body freshness binding;
- Stage-1 work-class semantics under `devflow#215` own the closed work-class vocabulary and explicit role/work-class compatibility;
- `devflow#209` owns runnable supply publication/withdrawal policy;
- execution-coordinator remains the sole runtime claim/lease/generation/fencing authority.

A Stage-2 producer MUST NOT duplicate those authorities in a private queue or parallel lifecycle.

### 10.2 Deterministic portfolio observation

A Stage-2 producer may classify only evidence obtained from exact live authoritative sources needed by the applicable rule, including:

- the unique open managed Repository Control;
- explicitly referenced owning Issue/Work Order;
- explicitly referenced PR, checks and Formal Reviews;
- trusted Manual Execution Session records;
- accepted repository Current State/specification when that surface owns the fact being assessed;
- exact current/default-branch identity where required.

Every required source must preserve exact object identity plus a revision, digest, SHA, or equivalent freshness binding and an observation time.

GitHub Project fields, search-index results, Issue age, labels, branch existence, free-form similarity, provider/model identity, idle worker state, or a desire to keep workers busy MUST NOT establish closure, readiness, mutation authority, or runnable demand.

Discovery/search may identify a possible source, but exact authoritative readback MUST confirm the relevant fact before classification or mutation. Search/index disagreement with exact source truth is an evidence signal, never closure authority.

A required source that is unreadable, missing, duplicate, contradictory, identity-mismatched, or insufficiently fresh yields `NEEDS_EVIDENCE`; it MUST NOT be silently treated as clean or `NO_ACTION`.

### 10.3 Finding metadata is not a second disposition vocabulary

Stage-2 rule/finding names are diagnostic metadata and reason detail only. Examples include:

- `CONTROL_AUDIT_SHA_MISMATCH`;
- `CONTROL_ACTIVE_WORK_TERMINAL`;
- `OWNER_TERMINAL_CONTROL_ACTIVE`;
- `PR_TERMINAL_OWNER_STALE`;
- `STALE_NEXT_ACTION_TARGET`;
- `ORPHAN_OPEN_PR`;
- `OBSOLETE_UNMERGED_PR`;
- `ACTIVE_PRODUCER_YIELD`;
- `REVIEW_GATE_YIELD`;
- `HUMAN_GATE_YIELD`;
- `RECOVERY_CANDIDATE`;
- `SOURCE_UNAVAILABLE_OR_AMBIGUOUS`;
- `SEMANTIC_PROJECTION_SUSPECTED`.

They do not create a new lifecycle. Every report still resolves through the existing dispositions from Section 3.

### 10.4 Read-only first and sync-check mutation allowlist

Initial Stage-2 producer execution is read-only.

A later `sync-check` executor may mutate durable state only when the transition is explicitly accepted by this canonical contract, all required preconditions are machine-provable, and the executor re-observes the exact identity immediately before mutation.

The initial bounded mutation class that S2.4 may implement is limited to machine-owned or projection state whose desired value follows deterministically from exact durable authority, such as:

- retire or replace a stale Control Active Work / Next Action projection after the exact bounded owner is proven terminal and no active producer, Human/security, external, or reviewer gate remains;
- withdraw or supersede stale machine-readable supply publication whose freshness/owner evidence no longer matches;
- update an explicitly machine-owned health/projection surface from exact authoritative evidence.

These candidates are not implementation merely by appearing here. S2.4 must still define and test each concrete transition before enabling mutation.

The following remain outside automatic sync-check mutation unless a later bounded canonical change explicitly admits them:

- semantic rewriting of README or Current State prose;
- ambiguous parent/spec Issue closure;
- arbitrary Issue closure;
- arbitrary PR merge;
- source-code changes or semantic fixes merely because prose or search output appears stale.

Such cases route through `NEEDS_EVIDENCE`, a durable triage finding, an existing Human/review gate, or another separately owned task as applicable.

### 10.5 Stable bounded report identity

One Stage-2 observation run produces a bounded report containing at least:

- observed repository and Control identity;
- exact source/evidence references and freshness bindings;
- canonical Development Reconciliation disposition;
- reason codes;
- diagnostic finding class when applicable;
- current owner/producer/gate classification;
- optional bounded transition request;
- explicit recheck trigger when no mutation is permitted.

A logical finding/report identity is derived from canonical repository/object identity, relevant evidence revision/digest/SHA, rule/finding identity, and transition identity when applicable. Observation timestamps are not part of logical identity.

Re-observing unchanged logical evidence therefore yields the same logical identity. Changed authority/evidence yields a different identity and requires reclassification.

### 10.6 No task inflation and durable tracking boundary

A producer MUST NOT create runnable demand merely because:

- a managed repository exists;
- a worker is idle;
- a previous audit once found drift;
- a clean run occurred;
- an Issue is old;
- search/index output looks stale;
- provider/model identity appears suitable;
- keeping workers busy would be convenient.

The default handling is:

- clean state, intentional wait, active trusted producer, or accepted future-spec state -> no synthetic task;
- source-unavailable, contradictory, or semantic-only ambiguity -> `NEEDS_EVIDENCE` / triage evidence, not autonomous implementation supply;
- Human/security/device/publication/credential/destructive/reviewer gate -> yield/route through the existing gate rather than manufacturing maintenance implementation;
- durable Issue or supply mutation occurs only when a concrete finding materially changes and the already-accepted tracking/publication criteria are satisfied.

The observation collector itself creates no Issue, claim, merge, branch, credential change, or provider launch.

### 10.7 Publication / consumption separation

Stage 2 preserves 3C publication/consumption separation. A worker/execution attempt that creates, adds, or relaxes a candidate/publication MUST NOT consume that changed supply in the same execution attempt.

Publication remains a durable projection of current authority, not assignment. Runtime ownership begins only after a later consumer re-reads the publication and succeeds through execution-coordinator claim/acknowledge semantics.

### 10.8 Derived implementation boundaries

The Stage-2 sequence is intentionally split so each later unit has one responsibility:

- **S2.2 read-only audit core:** immutable observation normalization, deterministic rules, and accepted historical regression fixtures; no GitHub mutation.
- **S2.3 deterministic triage:** map findings to the existing disposition vocabulary and to track/publish/no-op decisions; prove clean, active-producer, gate and semantic-ambiguity cases do not inflate task supply.
- **S2.4 bounded sync-check:** implement only explicitly accepted low-risk projection repairs, with immediate identity re-read, expected-identity guard, idempotent second run, and fail-closed changed evidence.
- **S2.5 supply integration:** publish only currently valid bounded demand through existing #209/candidate authorities while preserving 3C and retirement on readiness/freshness change.

A later unit that needs a new disposition, evidence source, mutable surface, or transition beyond this contract must update this canonical contract first through a bounded reviewed change.
