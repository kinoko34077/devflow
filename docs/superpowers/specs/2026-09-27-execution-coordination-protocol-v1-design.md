# Execution Coordination Protocol v1 — Design

Status: Proposed design for devflow #106 / parent #105
Date: 2026-09-27
Audit base: `2e9f5735d80d82820e2ebf500ca4a07d86573bf3`
Target runtime repository: `kinoko34077/execution-coordinator`

## 1. Purpose

Add a short-lived execution coordination plane for KiNoTch. managed repositories without replacing the existing durable GitHub-native devflow model.

The protocol must let multiple agents independently discover work, acquire non-conflicting execution ownership, expose current liveness/wait state, recover abandoned work, and later accept controller-side priority offers through the same claim authority.

The intended result is:

```text
GitHub durable control
  -> claimable work
  -> agent/controller negotiation
  -> serialized claim mutation
  -> execution lease
  -> branch/worktree/PR
  -> CI/review/user/dependency waits
  -> release/takeover/completion
```

## 2. Authority split

### devflow

Owns durable cross-repository policy and protocol semantics:

- task/execution/wait vocabulary;
- claim/lease/fencing contract;
- worker identity requirements;
- role and conflict semantics;
- controller/agent negotiation contract;
- safety and user-confirmation boundaries;
- managed-repository bootstrap expectations.

The existing devflow MCP remains read-only. It must not become the high-churn write runtime.

### execution-coordinator

Owns the runtime implementation of the protocol:

- claim discovery projection;
- claim/acknowledge/renew/progress/wait/resume/release/fail/expire/takeover mutations;
- ephemeral current claim state;
- liveness/progress timestamps;
- conflict-key enforcement;
- worker-generation fencing checks;
- later controller offers and agent capability responses.

It does not own repository requirements, local technical state, code, PR evidence, or durable cross-repository policy.

### owning repositories

Own:

- repository-local Issues/Work Orders;
- acceptance criteria and dependencies;
- implementation branches/worktrees;
- code/tests/specification;
- PRs and implementation verification.

### repo-monitor

Remains a read-only observer/projection. It may combine devflow, execution-coordinator, repository Issue/PR and Actions evidence but is not a claim authority.

## 3. State model

Durable and ephemeral state are separate axes.

### 3.1 Durable task state

Existing devflow/repository-local state remains authoritative. The runtime derives whether a task is claimable; it does not create a second durable task truth.

A v1 claim candidate must have:

- an owning repository Issue/Work Order;
- enough durable acceptance/scope information to implement or review;
- no unresolved durable blocker that forbids the requested role;
- no user-confirmation boundary that forbids autonomous continuation;
- a current repository/control entry path.

### 3.2 Execution state

Canonical runtime execution values:

- `CLAIMED`: ownership issued but active work not yet acknowledged;
- `RUNNING`: current worker is actively executing;
- `WAITING`: current task is intentionally waiting on an external condition;
- `RELEASED`: current worker intentionally relinquished the execution slot;
- `FAILED`: attempt ended unsuccessfully and no live ownership remains;
- `EXPIRED`: lease elapsed before valid renewal;
- `SUPERSEDED`: a newer generation owns the same exclusive execution boundary.

`STALLED`, `LOST`, and `ORPHANED` are observer classifications, not canonical mutation states in v1.

### 3.3 Wait reason

When state is `WAITING`, exactly one primary reason is recorded:

- `CI`
- `REVIEW`
- `USER_DECISION`
- `DEPENDENCY`
- `PROVIDER`
- `RATE_LIMIT`
- `EXTERNAL`
- `SCHEDULE`

Wait evidence must reference a durable/external source when one exists, such as PR checks, Review state, owning Issue text, dependency relation, or provider status evidence.

## 4. Worker identity

GitHub actor identity is insufficient because multiple agent surfaces may authenticate as the same GitHub user.

Each worker registers a bounded identity packet:

```yaml
worker_id: <stable-for-session unique id>
system: ChatGPT | Codex | ClaudeCode | dev_agent | Human | Other
model: <model/version or unknown>
host_id: <non-secret host label or unknown>
session_id: <opaque session id>
roles:
  - implementer
  - reviewer
capabilities:
  - <bounded capability tags>
```

Do not store credentials, local filesystem secrets, provider payloads, or unnecessary personal/device identifiers.

`worker_id` identifies the current execution participant; it is not a security principal by itself.

## 5. Claim record

A current claim contains at least:

```yaml
claim_id: <unique id>
generation: <monotonic integer for exclusive boundary>
task: <owner/repo#issue>
role: implementer | reviewer | verifier | integrator
worker_id: <worker id>
base_sha: <exact repository base/head when applicable>
branch: <branch or null>
state: CLAIMED | RUNNING | WAITING
wait_reason: <value or null>
conflict_keys:
  - <key>
claimed_at: <UTC timestamp>
heartbeat_at: <UTC timestamp>
last_progress_at: <UTC timestamp>
lease_until: <UTC timestamp>
evidence_ref: <PR/run/review/dependency reference or null>
```

## 6. Claim lifecycle

Every mutating v1 operation carries a caller-supplied `idempotency_key`. Retrying the same logical mutation reuses that key; a different payload under the same key is rejected.

### 6.1 Claim

`claim(task, role, worker, conflict_keys, expected_state, idempotency_key)` is accepted only when:

- the task remains eligible for that role;
- no valid exclusive claim already owns the same task/role;
- no incompatible active conflict key exists;
- the supplied durable-state expectation is still current enough for the operation;
- the worker has not presented a stale/superseded generation for a continuation operation.

On success, the coordinator allocates a new `claim_id`, increments the exclusive-boundary generation, stores the current claim, and returns the generation.

### 6.2 Acknowledge/run

The worker transitions `CLAIMED -> RUNNING` after it has successfully established its execution context.

For implementation work, the worker should use a dedicated branch/worktree before mutating repository code.

### 6.3 Renew

`renew(claim_id, generation)` updates liveness only if the supplied generation is still current.

A stale generation returns a hard rejection. The caller must stop treating itself as authoritative.

### 6.4 Progress

Progress is separate from heartbeat. A worker may remain alive without making forward progress.

`last_progress_at` changes only when a meaningful execution milestone occurs, such as a tested code change, new blocking finding, PR transition, or equivalent role-specific progress.

### 6.5 Waiting

When work intentionally blocks on CI/review/user/dependency/provider/external state, the worker records `WAITING` plus evidence.

`WAITING` remains lease-bound. Wait evidence never extends `lease_until` and never exempts a runtime claim from expiry. If ownership is retained during a bounded unsafe-to-transfer wait, the worker must continue valid renewals; if renewal stops, the claim expires normally. Wait evidence affects observer classification, not runtime ownership authority.

A waiting claim need not continuously hold an implementation-exclusive slot when doing so would prevent useful independent work. Role/conflict release policy is explicit per transition:

- `WAITING:CI`: implementation claim may be released after push/PR when no local mutation remains in flight;
- `WAITING:REVIEW`: implementer slot is normally released; reviewer role becomes independently claimable;
- `WAITING:USER_DECISION`: active execution ownership is released unless preserving it is necessary for a bounded unsafe-to-transfer operation; retained ownership remains lease-bound and renewable;
- dependency/provider/rate-limit waits normally release execution ownership.

The durable task remains waiting even when the worker lease is released. A live retained `WAITING` claim returns to active execution through `resume(claim_id, generation, idempotency_key)`, which requires the current unexpired generation, clears wait metadata, and transitions `WAITING -> RUNNING`.

### 6.6 Release/fail

`release` relinquishes authority intentionally. `fail` ends the current attempt with a bounded reason/evidence reference.

Neither operation marks the durable Issue complete.

### 6.7 Expire/takeover

Every current runtime claim, including `WAITING`, expires when `lease_until` passes without valid renewal. Durable wait evidence may affect whether an observer classifies the abandoned work as `LOST`, but it never extends the lease or preserves execution authority.

v1 uses an explicit two-step recovery in the same serialized mutation lane:

1. `expire(idempotency_key)` sweeps elapsed claims and commits the updated snapshot;
2. `takeover(..., idempotency_key)` / `claim(...)` then allocates the next generation.

`takeover` does not atomically perform the expiry sweep in v1. An expired-but-unswept claim may therefore reject a new claim until the explicit `expire` mutation commits. Atomic sweep-plus-takeover is deferred.

A new worker may then acquire a new generation. The previous worker is fenced and must not continue integration on the stale generation.

## 7. Fencing rule

Every authority-bearing mutation after claim acquisition carries `(claim_id, generation)`.

The coordinator rejects the mutation if that generation is not current for the relevant exclusive boundary.

For repository mutation, participating agents must re-check current generation before high-impact continuation points such as:

- first code mutation after a long pause;
- push after an extended interruption;
- opening/updating the authoritative implementation PR;
- enabling merge/auto-merge;
- integration handoff.

Branch isolation limits stale-worker damage, while generation checks determine which attempt is current.

## 8. Conflict keys

Conflict keys represent execution exclusivity, not mere relatedness.

Allowed v1 key classes:

```text
repo:<owner/repo>
component:<owner/repo>:<component>
path-group:<owner/repo>:<logical-group>
contract:<stable-contract-name>
schema:<stable-schema-name>
workflow:<stable-workflow-name>
```

Rules:

- whole-repository keys are exceptional, not default;
- line-level locks are out of scope;
- two claims may coexist if all their keys are compatible;
- the same exclusive key may not be concurrently owned by incompatible claims;
- reviewer claims are normally compatible with an implementer claim because reviewers must be able to inspect active work, but a reviewer may not also become the same task's independent implementer authority;
- cross-repository logical contracts use `contract:` or `schema:` keys.

Compatibility is evaluated inside the serialized mutation lane.

## 9. GitHub Actions serialization

GitHub Actions is the v1 mutation serializer.

The coordinator repository exposes one workflow-level mutation lane for all authority-changing operations:

```yaml
concurrency:
  group: execution-coordinator-state-mutation
  queue: max
```

`cancel-in-progress` is not enabled.

Current GitHub Actions behavior permits at most one running member of a concurrency group. With `queue: max`, up to 100 runs may remain pending in one concurrency group; when that queue is full, additional runs are canceled/rejected. Ordering follows when a run started waiting in the concurrency group (FIFO-oriented), but execution order is not a stronger dispatch-order guarantee. `queue: max` must not be combined with `cancel-in-progress: true`.

A canceled/rejected queued run makes **no authority change**. Clients must not treat dispatch acceptance as mutation success; authority changes only after the serialized run successfully commits the system-Issue snapshot. The protocol requires serializability, not stronger global fairness.

All v1 authority-changing operations use the global lane:

- claim;
- acknowledge/run;
- renew;
- progress;
- wait transition;
- resume;
- release;
- fail;
- explicit expire sweep;
- takeover/claim after expiry;
- controller offer acceptance that creates a claim.

Fine-grained conflict-key mutation lanes are deferred until real throughput requires them.

## 10. Current-state storage

### 10.1 Selected v1 store

Use one long-lived GitHub Issue in `execution-coordinator` titled exactly:

`[SYSTEM] Execution Coordination State`

Its body contains a machine-readable current snapshot under a versioned marker. GitHub Actions owns mutations to that snapshot.

Reasons for selecting this for v1:

- no external database/service is required;
- runtime state is visible through GitHub REST/API to agents and repo-monitor;
- no heartbeat commits pollute `main` or a state branch;
- the single mutation lane prevents concurrent body-write races;
- it is operationally reversible and easy to inspect during the pilot.

The system Issue is current state, not the durable task source of truth.

### 10.2 Durable lifecycle evidence

Do not append a comment for every heartbeat.

Durable comments are emitted only for significant authority boundaries:

- claim acquired;
- explicit release;
- failure;
- expiry;
- takeover/supersession;
- controller offer accepted when it creates ownership.

Heartbeat/progress refreshes update the current snapshot only.

### 10.3 Lease cadence

Initial v1 defaults:

- lease duration: 15 minutes;
- active worker renewal target: every 5 minutes;
- stalled observer threshold: 15 minutes without progress while heartbeat remains current;
- expiration: no valid renewal by `lease_until`.

These are protocol defaults and may become repository/runtime configuration after pilot evidence. A worker in an explicit durable wait should release its active execution claim rather than consume heartbeat runs indefinitely whenever safe. If a bounded unsafe-to-transfer `WAITING` claim is retained, it must renew before `lease_until`; wait evidence alone never protects it from expiry.

Because the v1 global `queue: max` lane can hold at most 100 pending runs, renewal clients must treat a canceled/overflowed run as **no authority change** and must not assume `lease_until` moved. The first merged-main pilot smoke records dispatch-to-snapshot-commit latency so renewal cadence can be validated against real queue behavior.

## 11. Runtime API/command surface

The initial implementation surface may be CLI plus GitHub workflow dispatch rather than a continuously running service.

Required logical operations:

```text
list_claimable
get_state
claim
acknowledge
renew
progress
wait
resume
release
fail
expire
takeover
```

The transport may later gain MCP/API adapters, but all adapters use the same state machine and serialized mutation path.

The existing read-only devflow MCP is not changed into this writer.

## 12. Agent-first scheduling

Initial scheduling is distributed/self-selected.

Agent flow:

```text
bootstrap devflow/repository
-> read READY/frontier work
-> read coordinator state
-> filter blocked/user-decision/capability-incompatible work
-> filter incompatible conflict ownership
-> rank by durable priority/dependency frontier
-> submit claim
-> start only on accepted claim
```

A rejected racing claim causes the agent to refresh state and select another eligible candidate.

## 13. Controller-side negotiation envelope

Controller-first dispatch is a later implementation phase, but v1 fixes the shared envelope so it cannot become a second assignment truth.

Controller offer:

```yaml
task: <repo#issue>
role: <role>
priority: <priority/urgency>
required_capabilities: []
required_environment: []
conflict_keys: []
risk: <risk>
authority_requirements: []
```

Agent response:

```yaml
worker_id: <id>
result: ACCEPTED | DECLINED_CAPABILITY | DECLINED_CONFLICT | DEFERRED_BUSY | BLOCKED_DEPENDENCY | REQUIRES_USER_AUTHORITY
capabilities: []
availability: <bounded state>
active_claims: []
reason: <bounded explanation>
```

Only `ACCEPTED` followed by a successful serialized claim creates ownership.

Controller priority can affect ranking but cannot override blockers, conflicts, user-confirmation boundaries, or claim generation.

## 14. repo-monitor projection

repo-monitor may derive:

- `RUNNING`: current valid claim + recent heartbeat;
- `STALLED`: current valid claim + recent heartbeat + progress older than threshold;
- `WAITING_CI`: durable/task wait evidence points to pending CI;
- `AWAITING_REVIEW`: implementation released and review requirement is unsatisfied;
- `WAITING_USER`: explicit user decision required;
- `BLOCKED`: durable dependency prevents the next role;
- `LOST`: a previous runtime claim expired and durable/external evidence does not establish that the work was intentionally waiting; wait evidence affects this observer label but never prevents runtime lease expiry;
- `ORPHANED`: branch/PR evidence exists with no valid/current ownership mapping.

These are projections. repo-monitor must not claim direct knowledge of ChatGPT/Codex internal process state.

## 15. Repository bootstrap

`execution-coordinator` is a separate managed repository.

Initial repository contains only the minimum needed to enter normal development:

- `README.md` explaining authority/boundary;
- `AGENTS.md` pointing workers through devflow first;
- `project/project.json` if Repository Base is adopted;
- `project/docs/INDEX.md`;
- `project/docs/CURRENT_STATE.md`;
- `.gitignore`;
- no production claim implementation in the bootstrap commit.

After creation it receives one devflow `[REPO] execution-coordinator` Control Issue and one local implementation Issue linked to #105/#106.

## 16. Initial implementation slices

After this design is accepted:

1. create/onboard `execution-coordinator`;
2. add deterministic pure state-machine tests first;
3. implement snapshot parser/serializer and generation checks;
4. implement the global Actions mutation workflow with `queue: max`;
5. implement claim/renew/release/expire/takeover operations;
6. create the `[SYSTEM] Execution Coordination State` Issue;
7. prove same-task double-claim rejection and non-conflicting parallel claims;
8. add wait evidence and reviewer-role behavior;
9. add a minimal client/CLI adapter;
10. integrate one agent surface as the first pilot;
11. add repo-monitor read projection only after runtime evidence is stable;
12. add controller priority offers after agent-first scheduling works.

## 17. Failure handling

- failed or canceled Actions mutation run leaves the previous system-Issue snapshot authoritative;
- callers treat a missing success result, queue overflow cancellation, or other canceled run as no authority change;
- every mutating operation carries an `idempotency_key`; retries reuse the same key so a repeated successful mutation does not allocate a second claim/generation;
- malformed state blocks mutation rather than being repaired heuristically;
- stale generation rejects authority-bearing mutation;
- GitHub/API outage means no new claim authority is issued; already-running workers must stop at lease expiry unless they can revalidate before then;
- user-confirmation-gated actions remain governed by existing devflow policy regardless of coordinator state.

## 18. Verification

Minimum deterministic verification:

- simultaneous claim race produces exactly one valid owner;
- independent non-conflicting claims both succeed;
- conflict-key collision rejects the second incompatible claim;
- renew extends only the current generation;
- stale generation cannot renew/push authority forward;
- expiry permits a new generation takeover after the explicit expire sweep;
- `WAITING` remains lease-bound and expired waiting ownership can be recovered;
- live `WAITING` can `resume -> RUNNING`, while expired waiting cannot resume;
- idempotent retry does not duplicate ownership;
- canceled/overflowed serialized runs produce no authority change;
- CI wait is not classified as lost work merely because no active claim remains;
- reviewer role remains independent from implementer ownership;
- malformed snapshots with incompatible conflict ownership or same-worker implementer/reviewer overlap fail closed;
- controller offer must still pass normal claim rules;
- malformed system state fails closed.

Integration verification uses exact-head GitHub Actions and the existing devflow formal Review policy.

## 19. Non-goals

- no replacement of GitHub Issues/PRs/Reviews/Actions with an opaque private task database;
- no write expansion of the existing devflow MCP;
- no repo-monitor scheduling authority;
- no line-level locks;
- no whole-repository lock by default;
- no controller override of user/security/deploy/destructive boundaries;
- no model-level identity claim based only on GitHub actor identity;
- no distributed consensus system beyond the GitHub Actions serialized mutation authority required for v1.

## 20. Acceptance of this design

The design is implementation-ready when:

- devflow #106 records it as the protocol design artifact;
- no placeholder or unresolved authority ambiguity remains;
- `execution-coordinator` ownership boundaries are accepted;
- GitHub Actions serialization uses a non-canceling queued global lane;
- the v1 current-state store and lease cadence are fixed;
- implementation is decomposed into bounded Issues/PRs instead of one monolithic change.
