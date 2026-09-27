# Execution Coordination Durable Candidate Source Contract

Status: Candidate canonical specification for devflow Issue #125
Schema: `.devflow/execution-candidate.schema.json`
Parent control specification: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
Execution Coordination parent: devflow #105

## 1. Purpose

This specification defines the durable GitHub source contract from which a later read-only Execution Coordination adapter may derive normalized `ClaimCandidate` values.

It exists to answer one bounded question deterministically:

> Which exact owning repository Issue / Work Order has explicitly opted into ordinary claim discovery, for which execution role and entry point, without inventing authority from prose, Project fields, repository age, PR existence, branch existence, or stale status?

This contract does not rank work, assign workers, submit claims, recover interrupted work, or create a second durable task database.

## 2. Authority model

Authority remains split as follows:

- the **owning repository Issue / Work Order** owns the bounded task, acceptance criteria, blocker and detailed task history;
- the **devflow Repository Control** owns only the cross-repository repository summary and routing state;
- a devflow cross-repository Work Order may own shared ordering/constraints when present;
- the **execution-candidate marker** is an explicit machine-readable projection embedded in the owning task itself;
- `ClaimCandidate` is a derived runtime input only;
- execution-coordinator system Issue #3 is ephemeral execution state only;
- GitHub Project remains a derived display layer only.

The marker therefore does not become a competing task record. It states only the minimum execution-discovery facts required to normalize the already-existing owning task.

## 3. Selected source representation

The v1 source is exactly one explicit HTML-comment marker embedded in the body of the owning open GitHub Issue / Work Order.

Exact framing:

```text
<!-- devflow-execution-candidate:v1
{JSON object}
-->
```

The JSON object must validate against `.devflow/execution-candidate.schema.json` and the contextual rules in this specification.

Example:

```text
<!-- devflow-execution-candidate:v1
{
  "schema": 1,
  "mode": "ordinary",
  "task": "kinoko34077/jev-audit#17",
  "role": "implementer",
  "entry_ref": "https://github.com/kinoko34077/jev-audit/issues/17",
  "control_ref": "kinoko34077/devflow#17",
  "parent_ref": null,
  "scope_ready": true,
  "blocked": false,
  "requires_user_confirmation": false,
  "conflict_keys": []
}
-->
```

A repository-local template is not required. Any managed repository may opt in by adding this exact marker to the owning task body when the task reaches a supported ordinary-discovery state.

## 4. Why the marker lives in the owning task

The following alternatives are rejected for v1:

### 4.1 devflow Control as the candidate record

Rejected because one Control can summarize several independent tracks. Making the Control a task-source API would duplicate repository-local authority and flatten multi-track state into an ambiguous synthetic task.

### 4.2 GitHub Project fields

Rejected because Project is display-only and reverse authority is prohibited.

### 4.3 Active Work / Next Action / arbitrary prose parsing

Rejected because human-readable summaries are not a stable parser API. Link presence, wording, age, status, PR existence and branch existence are insufficient authorization.

### 4.4 Separate private durable task store

Rejected because it would create a second assignment truth and break Issue-first authority.

## 5. Marker cardinality and syntax

For ordinary discovery:

1. zero markers means the Issue remains fully valid operationally but is **not discoverable**;
2. exactly one v1 marker is permitted in one owning Issue body;
3. two or more v1 markers in one body are invalid and fail closed;
4. malformed marker framing, malformed JSON, schema mismatch or unknown fields fail closed;
5. marker-like strings inside quoted prose/code are not authorization unless they match the exact framing consumed by the later parser;
6. only `schema = 1` and `mode = ordinary` are accepted by this contract.

A future recovery/resume contract must use a different mode/schema and is not inferred from this marker.

## 6. Field contract

### `schema`

Required integer constant `1`.

### `mode`

Required string constant `ordinary`.

This prevents ordinary fresh discovery from silently absorbing future recovery/resume semantics.

### `task`

Required exact canonical task reference in `owner/repository#issue-number` form.

Context rule: it must identify the Issue containing the marker itself. Copying a marker into a different Issue without updating `task` invalidates the source.

### `role`

Required enum:

- `implementer`
- `reviewer`
- `verifier`
- `integrator`

The role is explicit authorization for only that execution stage. It must not be inferred from title, labels, PR state or prose.

### `entry_ref`

Required GitHub Issue or Pull Request URL in the same owning repository as `task`.

It is the bootstrap/resume entry point supplied to the normalized candidate. The referenced resource must exist and be readable. If it is a PR, the PR must be open when used as an ordinary candidate entry.

### `control_ref`

Required exact devflow Repository Control reference.

Context rule: it must resolve to the unique open `[REPO] <repository>` Control for the repository named by `task`.

### `parent_ref`

Required field whose value is either `null` or an exact devflow Issue reference.

Use it only when a devflow cross-repository Work Order is the durable parent for this task. Absence of a parent is represented explicitly by `null`; a parser must not infer a parent from backlinks or prose.

### `scope_ready`

Required boolean mapped directly to `ClaimCandidate.scope_ready`.

`false` is a deliberate non-claimable state. It is not equivalent to a parser failure.

### `blocked`

Required boolean mapped directly to `ClaimCandidate.blocked`.

`true` means the task can be represented but must not become claimable through the ordinary projection.

### `requires_user_confirmation`

Required boolean mapped directly to `ClaimCandidate.requires_user_confirmation`.

This must be `true` for a source that remains behind an explicit user-decision/security/credential/release/deploy/publication/destructive boundary. A later adapter must not reinterpret prior broad authorization as permission to clear this flag.

### `conflict_keys`

Required array of unique non-empty strings mapped directly to `ClaimCandidate.conflict_keys`.

An empty list means **no conflict key is explicitly declared by this task**. The adapter must not invent conflict keys from changed files, path proximity, branch names or repository identity.

## 7. Contextual validation

JSON Schema validation is necessary but not sufficient. The later adapter/validator must additionally perform all of the following checks before normalization.

### 7.1 Owning task identity

- containing Issue is open;
- `task` exactly matches the containing repository and Issue number;
- repository is managed by exactly one open devflow Repository Control;
- `control_ref` exactly matches that Control.

### 7.2 Entry reference

- `entry_ref` resolves successfully;
- it belongs to the same owning repository as `task`;
- if it refers to a PR, that PR is open;
- failure to read/resolve is fail-closed.

### 7.3 Parent reference

When `parent_ref` is non-null:

- it must resolve successfully in `kinoko34077/devflow`;
- it must be open while used as an ordinary active parent;
- no parent may be inferred when the field is null.

### 7.4 Control guard

The devflow Control is a **validation/routing guard**, not the task source.

For an autonomous-ready ordinary record (`scope_ready=true`, `blocked=false`, `requires_user_confirmation=false`), the Control must expose the following exact stage compatibility:

| role | Control Work Status | leading Next Action tag |
| --- | --- | --- |
| implementer | `READY_FOR_IMPLEMENTATION` | `[IMPLEMENT]` |
| reviewer | `AWAITING_REVIEW` | `[REVIEW]` |
| verifier | `AWAITING_REVIEW` | `[VERIFY]` |
| integrator | `AWAITING_REVIEW` | `[MERGE]` |

If the Control is stale, contradictory, missing the required section, uses an unsupported tag, or is in another Work Status, the source fails closed for ordinary autonomous discovery.

This means Work Status / Next Action can veto an inconsistent marker but cannot create a candidate by themselves.

### 7.5 Explicit non-autonomous states

A marker may remain schema-valid while non-claimable:

- `scope_ready=false`;
- `blocked=true`;
- `requires_user_confirmation=true`.

The normalized `ClaimCandidate` preserves these flags and existing `list_claimable` filtering excludes them.

However, contradictory high-level state still fails closed. Examples:

- Control `BLOCKED` while marker says `blocked=false`;
- leading Next Action `[USER_DECISION]` while marker says `requires_user_confirmation=false`;
- closed task with any ordinary marker;
- `AUDITED / [WAIT]` Control paired with an autonomous-ready ordinary marker.

An unsupported/manual-only stage such as a Human Gate is not automatically mapped to a role. Until devflow defines a canonical machine tag/transition for that gate, ordinary discovery fails closed.

## 8. Mapping to `ClaimCandidate`

After schema + contextual validation, mapping is exact and lossless:

| Source field | `ClaimCandidate` field |
| --- | --- |
| `task` | `task` |
| `role` | `role` |
| `entry_ref` | `entry_ref` |
| `conflict_keys` | `conflict_keys` |
| `scope_ready` | `scope_ready` |
| `blocked` | `blocked` |
| `requires_user_confirmation` | `requires_user_confirmation` |

`control_ref`, `parent_ref`, `schema` and `mode` are validation/provenance fields and are not copied into the current `ClaimCandidate` dataclass.

No other field may be synthesized during v1 normalization.

## 9. Discovery algorithm boundary

The later adapter must remain read-only.

Minimum deterministic discovery contract:

1. read live devflow managed Repository Controls;
2. use Controls only to identify managed repositories and as the contextual guard described above;
3. enumerate open repository Issues through GitHub API rather than relying solely on search-index freshness;
4. ignore Pull Requests when enumerating task sources; a PR may only be an explicit `entry_ref` from an owning Issue marker;
5. inspect Issue bodies for the exact v1 marker;
6. validate marker cardinality, JSON Schema and contextual rules;
7. fail closed per-record on invalid/contradictory records and surface deterministic validation evidence;
8. normalize valid records to `ClaimCandidate`;
9. sort normalized candidates by canonical `task` then `role` only for deterministic output order;
10. call the existing read-only `list_claimable` projection against current CoordinatorState.

The sort in step 9 is not ranking or scheduling. Priority/dependency/capability selection remains a later slice.

The adapter must not mutate owning Issues, Controls, Project fields or runtime Issue #3 during discovery/listing.

## 10. Fail-closed rules

The following never produce an autonomous ordinary candidate:

- no marker;
- duplicate marker;
- malformed framing or JSON;
- unsupported schema/mode/field;
- `task` mismatch with containing Issue;
- closed owning Issue;
- missing/duplicate/mismatched devflow Control;
- missing/unreadable/stale `entry_ref`;
- unresolved non-null `parent_ref`;
- unsupported role;
- contradictory Work Status / Next Action guard;
- `scope_ready=false` after projection;
- `blocked=true` after projection;
- `requires_user_confirmation=true` after projection;
- active runtime task/role or conflict-key collision as already enforced by `list_claimable`;
- same-worker implementer/reviewer conflict as already enforced by `list_claimable` when worker identity is supplied.

A read/transport/API failure must not be converted into eligibility.

## 11. Ordinary discovery versus recovery

`mode=ordinary` represents a fresh bounded task stage explicitly prepared for a new claim.

It does **not** authorize:

- taking over an `IMPLEMENTING` task merely because runtime Issue #3 currently has no claim;
- resuming a lost worker;
- reconstructing a stale lease;
- reviving a closed/superseded task;
- inferring recovery from PR/branch existence.

Recovery/takeover requires a separate future contract with its own durable evidence and fencing semantics.

## 12. Representative conformance cases

The contract must explain current live-state classes without repository-specific hard-coded exceptions.

| durable state class | v1 result |
| --- | --- |
| bounded owning Issue, explicit marker, Control `READY_FOR_IMPLEMENTATION`, `[IMPLEMENT]`, no blocker/user gate | valid implementer source, subject to runtime conflict filtering |
| SCA extended GUI awaiting interactive Human Gate | no autonomous candidate; current unsupported/manual gate fails closed |
| kotonomani content/Voice Human Gate | no autonomous candidate |
| kinotch-api `BLOCKED / [USER_DECISION]` credential/release continuation | not claimable; contradictory autonomous-ready marker would be invalid |
| Micro-Chordbot blocked security/history decision plus independent UI work | Control prose cannot be flattened into a guessed candidate; only an explicit owning-task marker can opt in a separate supported track |
| dev_agent `IMPLEMENTING` with no live runtime claim | not rediscovered as fresh ordinary work; recovery is separate |
| execution-coordinator `AUDITED / [WAIT]` | no autonomous ordinary candidate |
| closed preserved-local-delta handoffs | no candidate; closed task cannot source ordinary work |

## 13. Migration and lifecycle

The representation is opt-in.

- existing managed Issues remain valid without a marker;
- absence of a marker means only `not discoverable by this adapter`, not `invalid Issue`;
- do not bulk rewrite historical Issues;
- add/update the marker only when the owning task intentionally enters a supported execution stage;
- when the stage/role changes, update the single marker rather than appending another marker;
- when the task closes, no cleanup mutation is required for safety because closed Issues are excluded, though repository policy may remove/retire the marker during normal closure reconciliation;
- a first pilot annotation should occur only in the later adapter slice, together with parser/validator tests and live read-only evidence.

## 14. Required follow-up implementation slices

Acceptance of this specification does not authorize runtime implementation in the same PR.

The next bounded execution-coordinator slice may implement only:

- strict marker extraction;
- JSON Schema-equivalent structural validation;
- contextual live GitHub/devflow validation;
- read-only managed-repository Issue enumeration;
- normalization to existing `ClaimCandidate`;
- deterministic diagnostics/order;
- composition with existing `get_state` + `list_claimable`.

That slice must not include ranking, capability/environment matching, scheduling/work stealing, automatic claim submission, controller negotiation, repo-monitor projection, or recovery/takeover.

Potential devflow-side follow-ups, only if implementation evidence requires them:

- expose a read-only MCP helper for candidate-source diagnostics;
- add an optional repository-local Issue snippet/example to operations documentation;
- add a dedicated validator tool for repository authors.

No Project Sync change is required because candidate markers remain repository-local technical task data and Project is not their authority/display contract.

## 15. Acceptance rationale

This contract keeps the current authority chain intact:

```text
owning repository Issue / Work Order
  -> explicit machine marker in that same durable task
  -> read-only normalization
  -> ClaimCandidate
  -> list_claimable + CoordinatorState
  -> later explicit claim mutation
```

No intermediate durable assignment database, Project reverse authority, Control prose parser or implicit recovery rule is introduced.
