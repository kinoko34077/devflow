# GitHub Actions Controller-first Dispatch + Provider Auto-launch Design

Status: AWAITING_REVIEW
Date: 2026-09-29
Authority: devflow#223 under parent devflow#105
Runtime owner: kinoko34077/execution-coordinator

## 1. Purpose

Extend the accepted Agent-first/manual-start execution stack with a bounded controller-first path that can discover accepted work, originate at most one offer per cycle, acquire the existing serialized runtime claim, launch one real provider through GitHub Actions, and continue through the existing execution lifecycle without creating a second task/assignment authority.

This design preserves `PILOT` adoption and the existing Human/security/release/deploy/credential boundaries.

## 2. Existing authority preserved

- Owning repository Issue / Work Order remains detailed durable task truth.
- Repository Control candidate projection remains machine admission/routing evidence.
- execution-coordinator Issue #3 remains the sole ephemeral claim/lease/generation/fencing authority.
- Only a successful serialized claim creates ownership.
- Controller offers are advisory scheduling input only.
- Agent-first and Controller-first paths converge on the same runtime authority.
- Existing trusted discovery, freshness, dependency/readiness, deterministic ranking, exact capability/environment matching, portfolio-v2, one-selection/one-claim-attempt, 3C and no-fallthrough semantics remain unchanged.
- devflow#202 remains the manual-start Actions pickup path.
- execution-coordinator#68 remains the provider-neutral request/dispatch boundary, with a versioned extension for CLAIMED-bound auto-launch.

## 3. Target flow

```text
managed Repository Controls / owning Issues
        ↓
accepted candidate supply + portfolio-v2 metadata
        ↓
GitHub Actions controller cycle
        ↓
max one bounded offer
        ↓
GitHub Actions launcher/orchestration context
        ↓
ACCEPT / DECLINE / DEFER
        ↓ ACCEPT only
serialized claim -> CLAIMED
        ↓
auto-launch ExecutionRequest
        ↓
provider-specific launch adapter
        ↓
provider execution context established
        ↓
acknowledge -> RUNNING
        ↓
normal work / verification / PR / review / release
```

## 4. Controller trigger model

Initial v1 uses:

- scheduled GitHub Actions polling;
- manual `workflow_dispatch` for pilot/recovery/testing.

Rules:

- one controller cycle may originate at most one offer;
- no eligible work is a successful no-op;
- duplicate/overlapping wakes must be idempotent/fail-closed against current candidate/runtime evidence;
- schedule timing is not authority and no stronger timing guarantee is inferred from it.

Future direction is bounded hybrid: add event-driven wake for latency while retaining scheduled polling as reconciliation/fallback. Event-driven wake is outside v1.

## 5. First provider and authentication

The first real auto-launch provider is Claude / Claude Code.

Authentication direction:

- GitHub Actions OIDC / workload identity;
- least-privilege repository/workflow identity binding;
- creation/configuration of trust mappings, credentials, sessions, permissions or identity policy remains Human-gated;
- runtime may only consume an already-approved/configured identity.

Codex auto-launch is deferred.

Ordinary ChatGPT product chats remain manual-start workers through the accepted #190/#202 path. v1 does not try to create ChatGPT UI conversations from GitHub Actions. A future OpenAI API Agent/Conversation runtime would be a distinct programmatic provider adapter, not an ordinary ChatGPT chat.

## 6. Claim / launch ordering

The accepted v1 ordering is:

```text
controller offer
-> launcher validates current offer/candidate/provider availability
-> ACCEPT
-> re-read freshness/conflict/Human gates
-> serialized claim
-> CLAIMED
-> construct CLAIMED-bound auto-launch ExecutionRequest
-> invoke provider adapter
-> prove provider execution context established
-> acknowledge claim
-> RUNNING
-> begin work
```

Rules:

- ACCEPT is not ownership.
- Provider launch occurs only after claim success.
- Repository work must not begin in CLAIMED.
- RUNNING means the provider execution context exists and the current claim has been acknowledged.
- GitHub Actions launcher/orchestration is transport/control context, not a second runtime owner.
- The claim remains bound to the intended provider execution attempt; returned provider/session identity is dispatch evidence, not parallel ownership.
- A stale/fenced generation blocks acknowledge/work even if a delayed launch response later arrives.

Required execution-coordinator contract change:

- add/version an auto-launch ExecutionRequest path valid from a current CLAIMED authority;
- preserve the existing already-RUNNING request path where compatibility requires it;
- preserve exact task/role/fingerprint/source/freshness/capability/environment binding from #68.

## 7. Launch outcome semantics

### 7.1 LAUNCH_UNAVAILABLE

The provider is definitely not started.

```text
CLAIMED -> release
```

Record bounded provider-unavailable evidence. Durable task remains incomplete and may become eligible later.

### 7.2 LAUNCH_FAILED

The launch attempt definitely failed without an active provider worker.

```text
CLAIMED -> fail
```

Record bounded failure evidence. Durable task is not completed.

### 7.3 Ambiguous / unknown result

The system cannot prove whether the provider started, for example after a timeout.

```text
CLAIMED -> WAITING:PROVIDER
```

Then reconcile:

- confirmed live + current authority -> acknowledge -> RUNNING;
- confirmed not started -> release;
- confirmed terminal failure -> fail;
- still unknown -> retain only under existing bounded lease/renew semantics, then expire/recover normally.

Immediate release is prohibited for ambiguous launch because an actually-running provider could otherwise overlap with a second claim.

### 7.4 Provider death after RUNNING

Use existing failure/recovery semantics. It is not a launch-unavailable case.

## 8. Offer durability

Normal high-churn controller offer evidence remains in the GitHub Actions run/log/summary:

```text
offer / ACCEPT / routine DECLINE / routine DEFER
-> run-local evidence
```

Do not append every offer to Issues and do not create a durable offer queue/database.

Durable escalation is required only for significant/recovery-relevant outcomes, including:

- Human Gate / user authority required;
- repeated provider unavailability that materially blocks autonomous operation;
- LAUNCH_FAILED where follow-up is required;
- ambiguous launch / WAITING:PROVIDER reconciliation;
- repeated/unexplained decline/defer patterns that require policy/operator action;
- existing lifecycle events that create/change runtime claim authority.

Use the smallest existing durable owning surface that correctly owns the evidence.

## 9. GitHub Actions responsibility split

### Controller workflow

- trigger by schedule or workflow_dispatch;
- read current accepted portfolio/candidate/runtime evidence;
- apply existing hard filters and deterministic selection;
- produce at most one bounded offer;
- never claim merely because an offer exists.

### Launcher/orchestration workflow/job

- validate offer freshness and provider availability;
- return ACCEPT / DECLINE / DEFER;
- on ACCEPT, refresh hard constraints and acquire exactly one serialized claim;
- construct the CLAIMED-bound auto-launch request;
- invoke exactly one provider adapter;
- reconcile launch outcome;
- acknowledge only after provider execution context is established.

### Claude provider adapter

- concrete Claude/Claude Code launch transport only;
- GitHub OIDC direction for authentication;
- return typed launch status and provider/session evidence;
- no candidate discovery/ranking/priority/claim authority.

## 10. Ordinary ChatGPT and future OpenAI runtimes

The design deliberately separates:

```text
ordinary ChatGPT product chat
= manually started user/chat worker
= #190/#202 path
```

from:

```text
OpenAI API Agent/Conversation runtime
= programmatic API execution surface
= possible future provider adapter
```

and from:

```text
Codex
= future coding-provider adapter
= currently deferred
```

API-created sessions must not be represented as ordinary ChatGPT UI chats.

## 11. Safety and compatibility invariants

- Sole runtime authority remains execution-coordinator claim/lease/generation/fencing.
- Stale candidate/fingerprint/source/freshness fails closed.
- Capability/environment mismatch fails before work.
- Live conflict/fencing and 3C remain unchanged.
- Human/User/release/deploy/publication/security/credential/session/permission/destructive/shared-history gates remain unchanged.
- Manual-start #202 remains supported.
- Provider/model identity never implies capability.
- No second queue/database/controller truth.
- No work stealing or LLM-semantic ranking.
- Adoption remains PILOT.

## 12. Implementation acceptance

Implementation is not released by this design. After written-spec approval and implementation-plan approval, acceptance requires at least:

- controller consumes only accepted live candidate/portfolio evidence;
- at most one offer per cycle;
- typed accept/decline/defer;
- ACCEPT alone never creates ownership;
- hard constraints fail before unauthorized work;
- serialized claim/fencing remains authoritative;
- CLAIMED-bound auto-launch request is versioned and tested;
- real Claude/Claude Code launch works through the accepted OIDC-based adapter after Human-approved identity setup exists;
- unavailable/failed/ambiguous launch follows the specified transitions and leaves no unexplained claim;
- racing controller cycles cannot create duplicate ownership;
- stale generations remain fenced;
- 3C remains intact;
- Agent-first/manual-start #202 has no regression;
- bounded live E2E succeeds on real managed candidate supply;
- final runtime contains no unexplained live claim;
- Current State / #107 / #105 / #188 are reconciled after acceptance;
- #188 is no longer merely deferred;
- #105 PARK state is re-evaluated only after all remaining parent conditions are checked.

## 13. Non-goals

- no PILOT -> REQUIRED_FOR_AUTONOMOUS promotion;
- no ordinary ChatGPT product auto-launch;
- no Codex auto-launch in v1;
- no event-driven wake in v1;
- no work stealing;
- no daemon outside GitHub Actions;
- no weighted/learned/LLM scheduler;
- no second durable task/assignment database;
- no provider-to-provider spawning outside the accepted Actions launcher path;
- no credential/session/permission/release/deploy/publication/destructive/shared-history mutation without required Human authorization.

## 14. Related authority

- devflow#105
- devflow#106
- devflow#175
- devflow#188
- devflow#189
- devflow#202
- devflow#208
- devflow#209
- devflow#223
- devflow#107
- execution-coordinator#68
- execution-coordinator#85
- execution-coordinator#3

## 15. Next step

This design is awaiting user review. After explicit approval, invoke the architectural implementation-planning stage. Do not release runtime implementation before that review/plan boundary is complete.
