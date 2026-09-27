# Durable Candidate Source Contract v1

Status: proposed for devflow Issue #125  
Parent: devflow #105  
Protocol authority: devflow #106 / merged PR #108  
Runtime consumer: `kinoko34077/execution-coordinator`

## 1. Purpose

Execution Coordination Protocol v1 already separates durable workflow truth from ephemeral runtime claim authority. `execution-coordinator` can validate current runtime state and filter normalized `ClaimCandidate` values, but a deterministic durable source for creating those normalized values has not previously been defined.

This contract defines one opt-in, machine-readable candidate source that remains embedded in the owning repository Issue. It does not create a second assignment database, does not make GitHub Project authoritative, and does not authorize automatic execution merely because an Issue exists or carries a particular Work Status.

The source contract is deliberately narrower than a scheduler. It answers only:

> Has the owning durable Issue explicitly published one versioned execution-candidate record, and if so, what exact normalized candidate fields may a read-only consumer derive from it?

Ranking, capability matching, scheduling, automatic claim submission, controller negotiation, and recovery of interrupted `IMPLEMENTING` work remain separate contracts.

## 2. Authority model

The following authority hierarchy is unchanged:

1. the owning repository Issue / Work Order remains detailed durable task authority;
2. devflow remains cross-repository policy and Repository Control authority;
3. this marker is an opt-in machine-readable projection stored **inside the owning durable Issue**;
4. `ClaimCandidate` is derived runtime input only;
5. execution-coordinator Issue #3 remains ephemeral execution state only;
6. GitHub Project remains derived display only.

The marker does not override the rest of the owning Issue. Deterministic contradictions between the marker and supported durable guard fields fail closed.

Free-form `Active Work` prose, Issue age, branch existence, pull-request existence, Project fields, chat history, and stale summaries are never sufficient candidate authority.

## 3. Selected representation

The canonical durable-candidate source is one versioned JSON object embedded in the **owning repository Issue body** between exact markers:

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

The marker is intentionally opt-in:

- no marker: the Issue remains a valid durable operational record but is **not discoverable through this contract**;
- exactly one valid marker pair: the record may be normalized after guard validation;
- duplicate, partial, reversed, malformed, unsupported, or contradictory markers: fail closed for that source;
- consumers must not infer a substitute candidate from nearby prose when marker validation fails.

This representation was selected over a dedicated candidate database because the owning Issue remains the source document and no replicated assignment truth is introduced. It was selected over prose-derived projection because the source fields are explicit and machine-validated.

## 4. Schema

### 4.1 Required top-level fields

`schema_version`
: Integer. MUST equal `1`.

`task_ref`
: String in exact `owner/repository#issue_number` form. MUST identify the Issue containing the marker. A marker cannot nominate a different owning task.

`entry_ref`
: Absolute canonical GitHub URL used to bootstrap or continue the role-specific work. For a fresh implementer candidate this SHOULD normally be the owning Issue URL. For review/verifier/integrator work it MAY identify the explicit current PR or other canonical GitHub entry authorized by the owning Issue. It MUST refer to the same owning repository and MUST NOT be inferred by the consumer.

`role`
: One of `implementer`, `reviewer`, `verifier`, `integrator`.

`scope_ready`
: Boolean. Explicit durable statement that the role-specific scope and acceptance boundary are sufficiently defined for autonomous consideration. The consumer must not derive `true` from prose completeness alone.

`blocked`
: Boolean. Explicit durable blocker state for autonomous continuation.

`requires_user_confirmation`
: Boolean. Explicit durable Human/User gate. This MUST be `true` whenever the candidate crosses a release, deploy, publication, credential/session, permission, destructive, security-sensitive, difficult-to-reverse, or explicit user-decision boundary that still requires user approval.

`provenance`
: Object identifying the devflow Control and, when applicable, cross-repository Work Order governing the source.

### 4.2 Optional top-level field

`conflict_keys`
: Array of unique non-empty strings. Omission is equivalent to an empty array. Conflict keys MUST be explicitly and durably specified; consumers must not derive keys from paths, file proximity, branch names, or Issue labels.

### 4.3 Provenance fields

`control_ref`
: Required string in exact `kinoko34077/devflow#N` form naming the current Repository Control for the owning repository.

`work_order_ref`
: Optional string in exact `kinoko34077/devflow#N` form naming the governing cross-repository Work Order when one exists.

Unknown fields are rejected in v1. Extending the schema requires a new accepted protocol revision rather than silently ignoring new authority-bearing fields.

## 5. Ordinary candidate role/state guard

Work Status is a **guard**, not candidate authority. The marker is still required.

For ordinary new-candidate discovery v1, a valid marker may be normalized only under these Work Status guards:

| Candidate role | Owning Issue Work Status allowed for ordinary discovery |
|---|---|
| `implementer` | `READY_FOR_IMPLEMENTATION` |
| `reviewer` | `AWAITING_REVIEW` |
| `verifier` | `AWAITING_REVIEW` |
| `integrator` | `AWAITING_REVIEW` |

All other Work Status values fail closed for ordinary discovery.

In particular:

- `IMPLEMENTING` is **not** an ordinary fresh-candidate state, even when no live runtime claim exists;
- `BLOCKED` is not claimable ordinary work;
- `AUDITED`, `WORK_ORDER_READY`, `NEEDS_AUDIT`, `NEEDS_REAUDIT`, `PARKED`, and `DONE` are not ordinary candidates;
- recovery/resume/takeover of interrupted work is a separate future contract.

The role/state table does not mean Work Status alone is sufficient. It only validates that an explicit marker is compatible with the current durable lifecycle.

## 6. Deterministic guard validation

A read-only consumer MUST apply all of the following before emitting a normalized source record.

### 6.1 GitHub object guard

- the containing object MUST be an open Issue;
- a pull request returned from the Issues API MUST be rejected as a candidate source;
- the fetched repository and Issue number MUST match `task_ref` exactly;
- the marker MUST occur exactly once.

### 6.2 Durable lifecycle guard

- current Work Status MUST satisfy the role/state table in section 5;
- `blocked=true` means the candidate is not claimable;
- if current Work Status is `BLOCKED`, a marker claiming `blocked=false` is contradictory and fails closed;
- `scope_ready=false` means the candidate is not claimable;
- a marker may remain present while temporarily unready or blocked, but it cannot authorize execution in that state.

### 6.3 Human-gate guard

`requires_user_confirmation=true` always excludes autonomous ordinary claimability.

In addition, deterministic existing human-gate evidence is a veto even if the marker incorrectly says `false`:

- canonical Next Action tag `[USER_DECISION]`;
- explicit `[HUMAN_GATE]` token used by current managed-repository handoffs;
- any future machine-recognized human-gate token added by accepted devflow policy.

A contradiction between a machine-recognized human gate and `requires_user_confirmation=false` fails closed; the consumer MUST NOT silently correct the marker to `true` and continue.

Semantic safety boundaries that cannot be inferred mechanically remain authoring/review obligations: a marker MUST NOT state `requires_user_confirmation=false` when the underlying task still requires approval for release, deployment, publication, credentials/sessions, permissions, destructive action, security-sensitive action, or another difficult-to-reverse action.

### 6.4 Entry guard

- `entry_ref` MUST be a canonical `https://github.com/...` URL;
- it MUST identify the same owning repository as `task_ref`;
- it MUST be explicitly stored in the marker;
- consumers MUST NOT search for or choose a branch/PR as a substitute when the entry is absent or invalid.

### 6.5 Provenance guard

- `control_ref` MUST identify the open devflow Repository Control for the owning repository;
- if `work_order_ref` is present, it MUST identify the governing devflow Work Order referenced by the current durable task context;
- missing, duplicate, invalid, or contradictory provenance fails closed;
- a Control's `Active Work` prose remains informational and is not parsed to manufacture a source record.

## 7. Mapping to ClaimCandidate

Once the marker and guards validate, mapping is direct:

| Marker / source evidence | `ClaimCandidate` |
|---|---|
| `task_ref` | `task` |
| `role` | `role` |
| `entry_ref` | `entry_ref` |
| `conflict_keys` or omitted | `conflict_keys` / `()` |
| `scope_ready` plus compatible role/state guard | `scope_ready` |
| `blocked` | `blocked` |
| `requires_user_confirmation` | `requires_user_confirmation` |

The consumer must preserve false values. It must not discard an explicit blocked/user-gated record and then reconstruct a more permissive candidate from other Issue fields.

A higher-level `list_claimable` projection may then combine the normalized durable candidate with current runtime `CoordinatorState` to exclude task/role ownership, conflict-key overlap, same-worker review conflicts, and other runtime conditions.

## 8. Fail-closed matrix

| Source condition | Result |
|---|---|
| marker absent | valid Issue, not discoverable |
| one valid marker + all guards valid | normalize candidate |
| duplicate marker | source failure |
| partial/reversed marker | source failure |
| malformed JSON | source failure |
| unsupported schema version | source failure |
| unknown v1 field | source failure |
| `task_ref` != containing Issue | source failure |
| closed Issue | source failure / no candidate |
| source object is PR | source failure |
| unsupported role | source failure |
| Work Status incompatible with role | no ordinary candidate; contradiction recorded |
| `IMPLEMENTING` with no runtime claim | no ordinary candidate; recovery path only |
| `BLOCKED` + marker `blocked=false` | contradiction, fail closed |
| `scope_ready=false` | normalized unready record or direct exclusion; never claimable |
| human-gate token + marker confirmation false | contradiction, fail closed |
| invalid/missing entry | source failure |
| missing/invalid Control provenance | source failure |
| duplicate/conflicting provenance | source failure |
| conflict keys absent | empty set; never infer |
| stale historical handoff with no current marker | not discoverable |

Implementations MAY expose diagnostic distinctions such as `not_discoverable`, `invalid_source`, and `guard_blocked`, but those diagnostics must not change the authority result.

## 9. Current live-state conformance fixtures

These examples are specification fixtures, not repository-specific exceptions.

### 9.1 Fresh bounded implementation

A `READY_FOR_IMPLEMENTATION` owning Issue such as the current `jev-audit#17` shape may become an implementer candidate **only after** that owning Issue receives a valid v1 marker explicitly naming itself, role `implementer`, the current entry, readiness flags, and Control provenance.

Without the marker, Work Status + `[IMPLEMENT]` alone remain insufficient.

### 9.2 Human-gated review/content work

SCA and kotonomani Human-Gate-bound work is not autonomously claimable. A marker present for observability must have `requires_user_confirmation=true`; an inconsistent false value fails closed.

### 9.3 Credential/release user decision

A `BLOCKED` kinotch-api-style task with `[USER_DECISION]` is not a candidate. Neither prior rollout authorization nor repository history can override the current gate.

### 9.4 Multi-track Control

Micro-Chordbot demonstrates why a Control's `Active Work` prose cannot be flattened into one candidate. Only a marker in one exact owning Issue can nominate one exact task/role. An independent UI track and a blocked security/history track require separate owning durable entries if both are to become discoverable.

### 9.5 Interrupted IMPLEMENTING work

A dev_agent-style `IMPLEMENTING` Issue with no current runtime claim is not rediscovered as fresh work. A future recovery contract may inspect generation, lease, expected state, and explicit recovery authority separately.

### 9.6 AUDITED/WAIT and historical handoffs

Repository Controls or preserved-delta handoffs that are `AUDITED`/`WAIT` and have no current owning implementation marker are not candidates.

## 10. Authoring and lifecycle rules

### 10.1 Creating a marker

A marker is added only when a durable owning Issue intentionally becomes eligible for machine discovery. It must be added or changed through normal repository Issue authority and must not be generated from Project display state.

### 10.2 Updating or disabling a marker

When role, readiness, entry, blocker, user-gate, or conflict metadata changes, the owning Issue marker must be updated before autonomous discovery may rely on the new state.

Removing the marker disables machine discovery without invalidating the Issue itself.

### 10.3 Completion

When durable work reaches `DONE`, the marker may be removed or left present as historical content; the Work Status guard prevents ordinary candidate emission either way. New automation must not resurrect it solely because the marker text still exists.

### 10.4 Recovery

Transition into or out of `IMPLEMENTING` is not ordinary discovery. A live/expired/lost claim and higher-generation takeover require separate runtime recovery semantics. This contract does not infer recovery eligibility.

## 11. Migration policy

No bulk rewrite is required.

Existing managed Issues without the marker remain fully valid durable records and continue under existing devflow governance. They are simply invisible to autonomous durable-candidate discovery until intentionally opted in.

Initial migration SHOULD be bounded to a small number of representative, currently active, non-sensitive Issues after the consumer validator is accepted. Migration must not add markers to Human-Gate, security/credential, release/deploy, destructive, stale historical, or recovery-only work merely to increase coverage.

## 12. Required later implementation slices

Acceptance of this specification does **not** itself authorize automatic scheduling or claims. Follow-up work remains separated.

### 12.1 devflow schema/template/validator slice

A later bounded devflow change may provide:
- marker JSON-schema or equivalent validator;
- Issue template guidance/helper text;
- deterministic validation tests for duplicate/malformed/contradictory records;
- optional read-only projection helpers;
- no Project-to-Issue reverse authority.

### 12.2 execution-coordinator conformance slice

`execution-coordinator#28` must be re-audited against this contract. Its provisional free-form heading parser must not be treated as canonical source authority. The conforming adapter should:
- parse only the v1 marker as source authority;
- treat ordinary Issue prose as validation guards only where this spec explicitly allows it;
- add the fixtures in section 9 as RED/GREEN tests;
- preserve exact-source GET-only behavior;
- preserve per-source diagnostics;
- continue to avoid ranking and mutation.

If adaptation is more complex or unsafe than reverting the provisional adapter, normal revert PR remains acceptable; shared-main history must not be rewritten.

### 12.3 composed read-only query slice

Only after the source adapter is accepted may a later read-only composition combine:

```text
explicit source refs
-> durable candidate marker validation
-> ClaimCandidate normalization
-> get_state()
-> list_claimable()
-> claimable projection
```

This composition still does not select a winner or submit a claim.

### 12.4 later ranking / capability / scheduling slices

Priority/dependency ranking, capability matching, controller offers, automatic claim submission, and bounded work stealing remain separate changes with their own acceptance and safety boundaries.

## 13. Security and safety boundary

This source contract is permission-minimizing:

- marker presence is opt-in but is not itself permission to bypass a user gate;
- recognized human gates veto autonomy;
- sensitive action boundaries continue to require explicit user confirmation under devflow safety policy;
- runtime claims do not authorize release/deploy/publication/credential/session/permission/destructive/security-sensitive/difficult-to-reverse actions;
- consumers fail closed when evidence conflicts or is incomplete;
- no credentials or personal sensitive identifiers belong in the marker.

## 14. Versioning

The marker name and `schema_version` jointly define the contract version.

A v1 consumer:
- accepts exactly one `DEVFLOW_EXECUTION_CANDIDATE_V1` marker pair;
- requires `schema_version: 1`;
- rejects unknown authority-bearing fields;
- does not reinterpret future markers.

Any change that adds authority semantics, broadens discoverability, changes role/state compatibility, or changes safety-gate behavior requires an accepted devflow protocol/spec revision before runtime consumers adopt it.
