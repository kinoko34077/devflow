# Durable Candidate Source Contract v1

Status: proposed for devflow Issue #125  
Parent: devflow #105  
Protocol authority: devflow #106 / merged PR #108  
Runtime consumer: `kinoko34077/execution-coordinator`

## 1. Purpose

Execution Coordination Protocol v1 separates durable workflow truth from ephemeral runtime claim authority. `execution-coordinator` can already validate runtime state and filter normalized `ClaimCandidate` values, but no deterministic durable source for creating those values had been accepted.

This contract defines one opt-in, machine-readable source embedded in the owning repository Issue. It does not create a second assignment database, does not make GitHub Project authoritative, and does not authorize execution merely because an Issue exists or has a particular Work Status.

It answers only:

> Has this exact owning durable Issue explicitly published one valid execution-candidate record, and what exact `ClaimCandidate` fields may a read-only consumer derive from it?

Ranking, capability matching, scheduling, automatic claim submission, controller negotiation, and recovery of interrupted `IMPLEMENTING` work remain separate contracts.

## 2. Authority model

Authority remains:

1. the owning repository Issue / Work Order is detailed durable task authority;
2. devflow is cross-repository policy and Repository Control authority;
3. the candidate marker is an opt-in machine-readable projection **inside the owning Issue**;
4. `ClaimCandidate` is derived runtime input only;
5. execution-coordinator Issue #3 is ephemeral execution state only;
6. GitHub Project is derived display only.

The marker does not override the rest of the Issue. Deterministic contradictions with supported durable guard fields fail closed.

Free-form `Active Work` prose, Issue age, branch/PR existence, Project fields, chat history, and stale summaries are never sufficient candidate authority.

### 2.1 No self-publication during selection

The agent/session consuming candidate sources MUST treat the source Issue as read-only during discovery and claim selection. It MUST NOT add, remove, or relax its own marker as part of the same selection attempt in order to make itself eligible.

Publishing or changing a marker is a separate durable workflow action governed by the owning Issue, devflow policy, existing safety boundaries, and normal Issue-first reporting. Marker authoring must occur before a later consumer evaluates the source. This is a procedural authority boundary rather than a cryptographic identity claim.

## 3. Canonical representation

The canonical source is exactly one versioned JSON object embedded in the **owning repository Issue body**:

```text
<!-- DEVFLOW_EXECUTION_CANDIDATE_V1_BEGIN -->
{
  "schema_version": 1,
  "task_ref": "owner/repository#123",
  "entry_ref": "https://github.com/owner/repository/issues/123",
  "role": "implementer",
  "scope_ready": true,
  "blocked": false,
  "requires_user_confirmation": false,
  "conflict_keys": [
    "component:owner/repository:parser"
  ],
  "provenance": {
    "control_ref": "kinoko34077/devflow#17",
    "work_order_ref": "kinoko34077/devflow#105"
  }
}
<!-- DEVFLOW_EXECUTION_CANDIDATE_V1_END -->
```

Rules:

- no marker: valid Issue, but not machine-discoverable;
- exactly one valid pair: may be normalized after guard validation;
- duplicate, partial, reversed, malformed, unsupported, or contradictory marker: fail closed;
- consumers must not construct a substitute candidate from nearby prose when validation fails.

This representation keeps the machine projection in the same durable Issue instead of introducing a separate assignment store.

## 4. Schema

### 4.1 Required top-level fields

`schema_version`
: Integer. MUST equal `1`.

`task_ref`
: Exact `owner/repository#issue_number`. MUST identify the Issue containing the marker.

`entry_ref`
: Explicit canonical `https://github.com/...` URL used to bootstrap the role-specific work. It MUST identify the same repository as `task_ref`. A consumer must never search for or choose an entry on the source's behalf.

`role`
: One of `implementer`, `reviewer`, `verifier`, `integrator`.

`scope_ready`
: Boolean. Explicit candidate-specific readiness; consumers must not derive `true` merely from prose completeness.

`blocked`
: Boolean. Explicit candidate-specific blocker state.

`requires_user_confirmation`
: Boolean. MUST be `true` whenever current work still crosses a release, deploy, publication, credential/session, permission, destructive, security-sensitive, difficult-to-reverse, or explicit user-decision boundary requiring user approval.

`provenance`
: Object identifying governing devflow authority.

### 4.2 Optional top-level field

`conflict_keys`
: Unique non-empty strings. Omission means `[]`. Keys must be explicit; never infer them from paths, branch names, labels, or file proximity.

### 4.3 Provenance

`control_ref`
: Required exact `kinoko34077/devflow#N`. It MUST resolve to the current open `[REPO] <repository>` Control whose structured `Repository` field matches the owning repository.

`work_order_ref`
: Optional exact `kinoko34077/devflow#N`. If present, it MUST resolve to an open devflow Issue with `[WORK ORDER]` identity. The marker itself establishes the candidate-to-Work-Order provenance link; consumers must not require reverse free-form prose scraping from the Work Order.

Unknown v1 fields are rejected. Authority semantics are not forward-compatible by silent ignore.

## 5. Ordinary role/state guard

Work Status is a **guard**, never source authority. The marker is always required.

| Role | Work Status allowed for ordinary new-candidate discovery |
|---|---|
| `implementer` | `READY_FOR_IMPLEMENTATION` |
| `reviewer` | `AWAITING_REVIEW` |
| `verifier` | `AWAITING_REVIEW` |
| `integrator` | `AWAITING_REVIEW` |

All other Work Status values do not emit an ordinary candidate.

In particular:

- `IMPLEMENTING` without a live runtime claim is not fresh work;
- `BLOCKED` is not ordinary claimable work;
- `AUDITED`, `WORK_ORDER_READY`, `NEEDS_AUDIT`, `NEEDS_REAUDIT`, `PARKED`, and `DONE` are not ordinary candidates;
- interrupted-work recovery/resume/takeover is a separate future contract.

## 6. Deterministic validation

### 6.1 GitHub object

- containing object MUST be an open Issue;
- a PR returned by the Issues API is rejected;
- fetched repository/Issue number MUST equal `task_ref`;
- exactly one complete marker pair is allowed.

### 6.2 Lifecycle and normalized output

There are two layers: **source normalization** and later **claimability filtering**.

If the marker is structurally valid and the role/state table is compatible, the consumer emits one normalized `ClaimCandidate` preserving these booleans exactly:

- `scope_ready=false` -> emit candidate with `scope_ready=false`; later `list_claimable` excludes it;
- `blocked=true` -> emit candidate with `blocked=true`; later `list_claimable` excludes it;
- `requires_user_confirmation=true` -> emit candidate with that value; later `list_claimable` excludes it.

The consumer MUST NOT make those values more permissive.

If Work Status is incompatible with the role/state table, no ordinary candidate is emitted. This includes `BLOCKED` and `IMPLEMENTING`. Implementations may report a guard diagnostic, but must not convert the source into a fresh candidate.

A current `BLOCKED` Work Status combined with marker `blocked=false` is additionally contradictory and is reported as invalid source evidence rather than silently corrected.

### 6.3 Human gates

`requires_user_confirmation=true` is always non-autonomous.

Existing deterministic human-gate evidence is an additional veto:

- canonical `[USER_DECISION]` Next Action;
- literal `[HUMAN_GATE]` currently used in managed-repository handoffs as a compatibility safety token;
- future machine-recognized human-gate tokens accepted by devflow policy.

If such evidence exists while the marker says `requires_user_confirmation=false`, the source is contradictory and fails closed. A consumer MUST NOT silently flip the flag and continue.

`[HUMAN_GATE]` is a v1 compatibility veto, not a new canonical Next Action permission tag; `.devflow/WORKFLOW.yaml` remains authoritative for canonical tag vocabulary.

Safety semantics that cannot be mechanically inferred remain marker-authoring/review obligations. A marker must never set the confirmation flag false to bypass an unresolved sensitive boundary.

### 6.4 Entry

- canonical HTTPS GitHub URL only;
- same owning repository as `task_ref`;
- explicit in marker;
- no substitute branch/PR discovery when absent or invalid.

### 6.5 Provenance

- `control_ref` must resolve to the current open matching Repository Control;
- optional `work_order_ref` must resolve to an open `[WORK ORDER]` devflow Issue;
- missing, invalid, or contradictory provenance fails closed;
- Control `Active Work` prose is not parsed as a source API.

## 7. Exact mapping to ClaimCandidate

When the marker is valid and the role/state guard permits normalization:

| Source | `ClaimCandidate` |
|---|---|
| `task_ref` | `task` |
| `role` | `role` |
| `entry_ref` | `entry_ref` |
| `conflict_keys` or omitted | `conflict_keys` / `()` |
| `scope_ready` | `scope_ready` |
| `blocked` | `blocked` |
| `requires_user_confirmation` | `requires_user_confirmation` |

`list_claimable` subsequently combines these durable flags with runtime `CoordinatorState` and excludes unready, blocked, user-gated, already-owned, conflict-key-incompatible, or same-worker review-conflicting candidates.

## 8. Fail-closed matrix

| Condition | Result |
|---|---|
| marker absent | valid Issue; not discoverable |
| valid marker + compatible role/state | normalize candidate exactly |
| duplicate/partial/reversed marker | invalid source |
| malformed JSON | invalid source |
| unsupported schema version | invalid source |
| unknown v1 field | invalid source |
| task mismatch | invalid source |
| closed Issue | no candidate / source diagnostic |
| source object is PR | invalid source |
| unsupported role | invalid source |
| Work Status incompatible with role | no ordinary candidate |
| `IMPLEMENTING` without runtime claim | no ordinary candidate; recovery only |
| `BLOCKED` + marker `blocked=false` | contradiction; invalid source |
| compatible status + marker `scope_ready=false` | normalize false; `list_claimable` excludes |
| compatible status + marker `blocked=true` | normalize true; `list_claimable` excludes |
| compatible status + marker confirmation true | normalize true; `list_claimable` excludes |
| machine human gate + marker confirmation false | contradiction; invalid source |
| invalid/missing entry | invalid source |
| invalid Control provenance | invalid source |
| invalid optional Work Order provenance | invalid source |
| conflict keys absent | normalize empty tuple; never infer |
| historical Issue without current marker | not discoverable |

Diagnostic names are implementation details; authority results above are normative.

## 9. Live-state conformance fixtures

### 9.1 Fresh bounded implementation

A `READY_FOR_IMPLEMENTATION` Issue such as the current `jev-audit#17` shape is eligible in principle only after that exact owning Issue receives a valid marker naming itself, role `implementer`, current entry, readiness flags, and Control provenance. Work Status + `[IMPLEMENT]` alone is insufficient.

### 9.2 Human-gated work

SCA and kotonomani Human-Gate-bound work is not autonomously claimable. If a marker exists for observability it must carry `requires_user_confirmation=true`; false is contradictory.

### 9.3 Credential/release user decision

A `BLOCKED` kinotch-api-style task with `[USER_DECISION]` does not emit an ordinary candidate. Prior rollout authorization or history cannot override the current gate.

### 9.4 Multi-track Control

Micro-Chordbot demonstrates why `Active Work` prose cannot be flattened into a candidate. Each discoverable track requires one exact owning durable Issue with its own marker.

### 9.5 Interrupted IMPLEMENTING work

A dev_agent-style `IMPLEMENTING` Issue with no live claim is not rediscovered as fresh work. Recovery needs a separate contract.

### 9.6 AUDITED/WAIT and history

AUDITED/WAIT Controls and preserved historical handoffs without current owning markers are not candidates.

## 10. Marker lifecycle

### 10.1 Publish

A marker is published only when the owning Issue intentionally becomes machine-discoverable. Publication is a separate durable workflow update, not part of the consuming worker's selection operation.

### 10.2 Update/disable

Role, entry, readiness, blocker, user-gate, conflict metadata, or provenance changes require marker reconciliation before later autonomous consumers rely on them. Removing the marker disables discovery without invalidating the Issue.

### 10.3 Completion

A marker may remain historically after `DONE`; the Work Status guard prevents ordinary emission. Automation must never resurrect completed work solely from marker text.

### 10.4 Recovery

`IMPLEMENTING` recovery, lease loss, generation takeover, and interrupted session admission remain outside this contract.

## 11. Migration

No bulk rewrite is required.

Existing managed Issues without markers remain valid operational records and are simply non-discoverable. Initial opt-in migration should cover only a small set of current, non-sensitive representative work after consumer validation exists.

Do not add markers merely for coverage to Human-Gate, security/credential, release/deploy, destructive, stale historical, or recovery-only work.

## 12. Required follow-up slices

Acceptance of this spec does not authorize scheduling or claims.

### 12.1 devflow validator/template

A later bounded devflow slice may add:

- JSON-schema/equivalent marker validator;
- template/helper guidance;
- deterministic duplicate/malformed/contradiction tests;
- optional read-only projection helpers;
- never Project -> Issue reverse authority.

### 12.2 execution-coordinator #28 conformance

The provisional #28 parser must be re-audited. The conforming adapter should:

- treat only this marker as candidate source authority;
- use ordinary Issue fields solely for guards explicitly allowed above;
- add section 9 fixtures as RED/GREEN tests;
- preserve exact-reference GET-only behavior and per-source diagnostics;
- avoid ranking, mutation, and automatic claims.

If the provisional adapter cannot be safely conformed, use a normal revert PR; never rewrite shared main.

### 12.3 composed read-only path

Only after conformance may a later slice compose:

```text
explicit source refs
-> marker validation
-> ClaimCandidate normalization
-> get_state()
-> list_claimable()
-> claimable projection
```

It still neither ranks a winner nor submits a claim.

### 12.4 ranking/capability/scheduling

Priority/dependency ranking, capabilities, controller offers, automatic claims, and work stealing remain independent later slices.

## 13. Safety boundary

- marker opt-in never bypasses a user gate;
- recognized human gates veto autonomy;
- existing explicit confirmation requirements remain unchanged;
- runtime claims never authorize release/deploy/publication/credential/session/permission/destructive/security-sensitive/difficult-to-reverse actions;
- incomplete/conflicting evidence fails closed;
- credentials and personal sensitive identifiers must not appear in markers.

## 14. Versioning

A v1 consumer:

- accepts exactly one `DEVFLOW_EXECUTION_CANDIDATE_V1` pair;
- requires `schema_version: 1`;
- rejects unknown authority-bearing fields;
- does not reinterpret future marker versions.

Any change that broadens discoverability, changes role/state compatibility, adds authority fields, or changes safety-gate behavior requires an accepted devflow protocol/spec revision before runtime adoption.
