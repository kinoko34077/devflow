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

- devflow#155 — GitHub-native Development Reconciliation Loop
- devflow#111 — Formal Review policy
- devflow#142/#144 — Manual Execution Session semantics
- devflow#105/#125 — execution allocation/candidate-source authority
- devflow#151 — read-only portfolio projection design input
