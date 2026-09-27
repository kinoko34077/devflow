# Autonomous Work Allocation Policy v1 — Design

Status: user-approved architecture decision; repository merge pending written-spec review  
Date: 2026-09-27  
Parent: devflow #105  
Execution protocol: devflow #106 / merged PR #108  
Durable candidate source slice: devflow #125  
Runtime implementation: `kinoko34077/execution-coordinator`

## 1. Purpose

This document fixes the architecture for CPU-core-like autonomous multi-agent work allocation above the accepted Execution Coordination Protocol v1.

It resolves the remaining policy ambiguities around:

- where machine-discoverable work candidates are published;
- which surface owns candidate-specific readiness and freshness;
- who may publish versus consume candidates;
- when use of `execution-coordinator` is mandatory;
- how initial scheduling/ranking works;
- how capabilities and controller priorities participate without creating a second assignment truth.

This document does not implement the scheduler, discovery adapter, runtime claim transport, repo-monitor, or controller transport. Those remain bounded follow-up slices.

## 2. Authority model

Authority is split into three non-overlapping layers:

1. **Owning repository Issue / Work Order** — detailed durable task authority: objective, scope, acceptance, dependencies, implementation detail and technical completion evidence.
2. **devflow Repository Control candidate projection** — machine-readable admission record stating that one exact durable task may currently participate in autonomous execution for one or more roles.
3. **execution-coordinator runtime state** — ephemeral ownership only: claim, lease, generation, liveness, wait state, conflict ownership and takeover.

GitHub Project, branch existence, PR existence, labels, chat history and free-form prose are not candidate authority.

A candidate projection is not a second durable task truth. It is an admission projection over the owning durable task.

### Trust prerequisite

Control discovery and every consumer of the projection MUST enforce the trusted-author rule from devflow #127: accept only the unique `[REPO] <repository>` Control whose GitHub `author_association` is `OWNER`, `MEMBER`, or `COLLABORATOR`. Outsider-authored lookalikes MUST be ignored and reported, while duplicate trusted Controls MUST fail closed. The exact owning Issue/Work Order snapshot used for `task_body_sha256` MUST pass the same trusted-author check, as required by execution-coordinator#34; missing or unknown association fails closed.

`REQUIRED_FOR_AUTONOMOUS` MUST NOT be enabled until this trust rule is implemented and verified in every canonical Control/discovery path. `PILOT` may exercise only the bounded trusted path; it does not waive the trust prerequisite.

## 3. Canonical candidate source — Repository Control projection

The canonical machine-discoverable source is an opt-in versioned candidate block in the unique devflow `[REPO] <repository>` Repository Control.

The owning Issue remains the detailed durable authority and is referenced exactly from the projection.

The v1 projection MUST NOT require repository-local Issues to expose a universal devflow `Work Status` or `Next Action` schema.

The projection MUST support multiple independent task tracks inside one repository without parsing `Active Work` prose.

No candidate may be manufactured from repository status alone, Control prose, Project state, Issue age, branch/PR existence or absence of a runtime claim.

## 4. Candidate representation — task envelope plus roles

The preferred v1 logical shape is one **task envelope** containing task-level admission state plus one or more role entries.

Conceptual shape:

```json
{
  "task_ref": "owner/repo#123",
  "task_body_sha256": "sha256:<digest>",
  "entry_ref": "https://github.com/owner/repo/issues/123",
  "phase": "READY_FOR_IMPLEMENTATION",
  "scope_ready": true,
  "blocked": false,
  "requires_user_confirmation": false,
  "conflict_keys": ["component:owner/repo:parser"],
  "required_capabilities": ["python", "github"],
  "required_environment": [],
  "roles": [
    {
      "role": "implementer",
      "action": "IMPLEMENT"
    }
  ]
}
```

Task-level fields MUST NOT be duplicated independently per `(task, role)` in a way that can express contradictory lifecycle phases for the same task.

Role-specific values remain inside `roles`; task-level freshness, blockers, confirmation state, scope readiness and lifecycle phase remain single-valued per task envelope.

Omitted `conflict_keys`, `required_capabilities` or `required_environment` normalize to empty sets/tuples and are never inferred from prose or repository layout.

## 5. Freshness and machine authority

For autonomous discovery, the candidate projection itself is the task-specific machine authority for:

- projected lifecycle phase/action compatibility;
- `scope_ready`;
- `blocked`;
- `requires_user_confirmation`;
- explicit conflict keys;
- required capabilities/environment;
- published roles.

The owning task body remains authoritative for detailed task content.

Each candidate envelope is bound to the exact owning Issue/Work Order body using canonical SHA-256. If the current owning body digest differs from the published digest, the candidate is stale and MUST fail closed until republished/reconciled.

Repository-level Control `Repository State` remains a live veto. A repository that is not `ACTIVE` emits no ordinary autonomous candidates.

Safety/user-confirmation boundaries remain live vetoes and cannot be relaxed by a candidate projection. Release, deploy, publication, credential/session/permission, destructive, security-sensitive and difficult-to-reverse operations continue to require explicit user authority under devflow policy.

Consumers MUST NOT repair stale/missing candidate state by interpreting free-form `Active Work`, `Next Action`, labels, Project fields or nearby text.

## 6. Candidate publication boundary

Candidate publication and candidate consumption are logically separate durable operations.

A worker/session that publishes, adds or relaxes a candidate envelope MUST NOT consume that newly relaxed candidate in the same execution attempt.

The publication path is:

```text
owning task/current durable state
-> candidate projection update
-> normal review/validation/reconciliation
-> later independent consumption attempt
```

This is a procedural separation, not a cryptographic identity guarantee. The system may use the same GitHub account while still requiring separate execution attempts/provenance.

Candidate publication MUST be reviewable, fail closed on malformed/contradictory data, and remain revertible through ordinary GitHub history.

## 7. Work Order provenance

A Work Order reference is optional provenance, not autonomous claim authority by itself.

V1 MUST NOT depend on historical or inconsistent Work Order title prefixes as the identity contract.

If `work_order_ref` is present, it identifies the governing devflow Issue by exact repository/issue reference. Stronger machine classification of Work Orders requires a future explicit stable marker/schema and must not be inferred from title text.

## 8. Execution Coordination adoption mode

Adoption is machine-readable and separate from runtime implementation readiness.

Canonical modes:

- `OFF` — autonomous execution coordination disabled;
- `PILOT` — bounded opt-in pilots only;
- `REQUIRED_FOR_AUTONOMOUS` — any automatic discovery/self-selection/parallel-agent implementation must obtain a coordinator claim before work begins;
- `REQUIRED_FOR_AGENT_WORK` — all ordinary agent implementation work must use coordinator claims unless an explicit break-glass path applies.

Initial mode is **`PILOT`**.

Promotion path:

```text
PILOT
-> multi-agent / multi-repository pilot evidence
-> REQUIRED_FOR_AUTONOMOUS
-> optionally, after further evidence, REQUIRED_FOR_AGENT_WORK
```

Human manual work is not globally required to use execution-coordinator in v1.

Manual repair of execution-coordinator/devflow itself, emergency recovery and other explicit break-glass operations must remain possible when the coordinator is unavailable. Such exceptions do not authorize autonomous parallel work without claims.

## 9. Mandatory-use boundary

Once mode reaches `REQUIRED_FOR_AUTONOMOUS`, the following MUST use coordinator claim authority before implementation begins:

- automatically discovered work;
- self-selected work from the runnable frontier;
- multiple agents working concurrently across managed repositories;
- scheduler/work-stealing loops;
- controller-offered work that the agent accepts.

A successful dispatch/offer is not ownership. Ownership begins only after the serialized claim commits and the worker successfully acknowledges execution.

## 10. Initial scheduler policy — deterministic lexicographic ranking

The initial autonomous scheduler uses deterministic lexicographic ordering, not an opaque weighted score and not an auction.

A candidate must first pass all hard filters:

1. valid non-stale candidate projection;
2. repository and task safety gates;
3. dependency/frontier readiness;
4. runtime claim/conflict compatibility;
5. exact capability/environment compatibility.

Remaining candidates are ranked by this initial order:

1. durable priority from the trusted Repository Control `Priority` field: `P0 > P1 > P2 > P3`; it is not read from owning-Issue prose;
2. explicit controller priority/urgency hint when present;
3. dependency-frontier order / unblock value represented by explicit durable dependency data;
4. role/action readiness class;
5. explicit candidate-projection `ready_at` in canonical UTC form, oldest first when present; it MUST NOT be derived from Issue `created_at`, `updated_at`, comments, labels, or edit timing;
6. canonical `task_ref` lexical order as the final deterministic tie-breaker.

No hidden LLM preference or free-form semantic scoring participates in v1 ranking.

If some ranking field is unavailable under the accepted schema, it MUST have one explicit neutral/default ordering rule rather than being guessed from prose. In particular, an absent `ready_at` receives the defined neutral/default value; Issue timestamps and prose never substitute for it.

The rank fields through `ready_at` define deterministic rank classes. The canonical `task_ref` comparison remains the stable audit order, but a worker MUST avoid making every idle worker submit the same first claim from one class. Within the highest-ranked eligible class, selection uses a worker-scoped deterministic rotation:

1. identify the stable worker identity and the current discovery-cycle identifier;
2. order candidates by `(SHA-256(worker_id || "\\0" || task_ref || "\\0" || discovery_cycle_id), task_ref)`;
3. submit at most one claim attempt in that discovery cycle.

This is a selection-spread rule, not a second assignment authority: hard eligibility and rank-class ordering remain unchanged, and the serialized runtime claim remains the sole ownership decision. If a stable worker identity is unavailable, use canonical `task_ref` order and still enforce the attempt cap. A rejected claim ends the current cycle; the worker refreshes and starts a new cycle rather than racing through the whole frontier in one attempt burst. The v1 default cap is one claim attempt per discovery cycle; any future increase requires an explicit policy revision and queue-capacity evidence.

Weighted scoring, auctions and learned scheduling remain later alternatives requiring a separate accepted policy revision.

## 11. Capability and environment matching

V1 capability/environment matching uses exact tags only.

Eligibility requires:

```text
required_capabilities subset-of worker.capabilities
required_environment subset-of worker.environment
```

No fuzzy or model-judged inference such as “this worker can probably do Rust” is allowed in v1.

Unknown/missing required tags fail closed for that worker but do not invalidate the candidate for other workers.

## 12. Agent-first autonomous loop

The intended v1 autonomous worker loop is:

```text
bootstrap live devflow canon
-> read canonical candidate frontier
-> validate freshness and safety gates
-> read coordinator state
-> list_claimable
-> exact capability/environment filter
-> deterministic rank classes + worker-scoped tie rotation
-> submit at most one serialized claim in this discovery cycle
-> if rejected: end the cycle and refresh on the next cycle
-> if accepted: establish isolated execution context
-> acknowledge CLAIMED -> RUNNING
-> execute with renew/progress/wait/resume/release/fail
```

A worker MUST NOT begin implementation before claim and acknowledge succeed when the current adoption mode requires coordination.

## 13. Controller relationship

Controller-side dispatch does not become a second assignment authority.

A controller may publish priority/urgency hints and bounded capability/environment requirements. An agent may accept, decline or defer an offer.

Only a successful serialized runtime claim creates execution ownership.

Controller input MUST NOT override:

- user-confirmation gates;
- security/release/deploy/publication/credential/destructive boundaries;
- runtime conflicts;
- stale candidate projections;
- generation fencing;
- capability/environment incompatibility.

## 14. Recovery is separate from fresh discovery

`IMPLEMENTING` without a live claim MUST NOT automatically re-enter the ordinary fresh candidate frontier.

Lost/stale/orphaned work recovery remains a separate contract using durable evidence, generation fencing and explicit recovery/takeover semantics.

The scheduler MUST NOT convert “no current claim” into “fresh task”.

## 15. Required implementation order

The architecture is implemented in independently revertible slices:

1. accept the corrected candidate-source specification conforming to this policy;
2. implement devflow candidate-block parser/body-digest/fail-closed validator;
3. re-audit and adapt execution-coordinator durable discovery to the accepted Control-projection contract;
4. compose `discover -> get_state -> list_claimable` as one read-only projection path;
5. implement managed-repository/frontier enumeration without heuristic prose inference;
6. implement explicit dependency-frontier handling and deterministic ranking;
7. implement exact capability/environment filtering;
8. implement autonomous worker bootstrap/self-selection/racing claim loop;
9. implement read-only repo-monitor liveness projection;
10. implement controller offer/agent negotiation transport through the same claim authority;
11. run bounded concurrent multi-worker/multi-repository pilot;
12. consider promotion from `PILOT` to `REQUIRED_FOR_AUTONOMOUS` only from pilot evidence.

Do not combine discovery, ranking, scheduling, capability matching and claim mutation into one opaque subsystem.

## 16. Safety and rollback

This policy does not weaken existing devflow safety boundaries.

Autonomous scheduling MUST classify work requiring release/deploy/publication, credential/session/permission changes, destructive deletion, shared-history rewrite, security-sensitive action or other difficult-to-reverse action as non-autonomous until explicit user authority is present.

Normal code/docs changes with low catastrophic potential and safe revert may continue under standing authorization after current verification and review.

Every implementation slice must remain revertible by normal PR; shared-main history rewriting is prohibited for rollback.

## 17. Canonical relationship

Authority order for this design family:

1. current explicit user decisions;
2. this autonomous-allocation policy for the decisions fixed here;
3. accepted Execution Coordination Protocol v1 for claim/lease/runtime semantics;
4. accepted durable-candidate source contract for concrete Control projection schema;
5. machine-readable workflow/schema implementing the accepted contracts;
6. repository-local runtime implementation/tests.

The durable-candidate source contract MUST conform to this document and may specify concrete marker names, serialization, validation details and versioning, but must not move candidate authority back into free-form owning-Issue parsing or weaken publication/freshness/adoption/ranking rules fixed here.

## 18. Fixed decisions

The following are intentionally fixed for v1:

- **1B** Candidate source: Repository Control projection.
- **2B** Candidate projection is the task-specific machine admission authority; owning Issue remains detailed task truth.
- **3C** Publisher and consumer are logically separated across execution attempts.
- **4B** Coordinator is required for autonomous/parallel agent execution after promotion, not globally for all human/manual work.
- **6B** Initial scheduler is deterministic lexicographic ranking, with worker-scoped deterministic spread within equal-rank classes and a bounded claim-attempt cap.
- Adoption mode is machine-readable and starts at `PILOT`.
- Capability/environment matching uses exact tag subset checks.
- Controller offers are priority hints only; claim authority remains unique.
- Task-level candidate data uses one task envelope with role entries to avoid cross-role lifecycle contradiction.
- `work_order_ref` is optional provenance only unless a later stable machine identity contract is explicitly accepted.
