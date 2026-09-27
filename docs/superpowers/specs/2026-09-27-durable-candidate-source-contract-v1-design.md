# Durable Candidate Source Contract v1

Status: proposed for devflow Issue #125  
Parent: devflow #105  
Protocol authority: devflow #106 / merged PR #108  
Runtime consumer: `kinoko34077/execution-coordinator`

## 1. Purpose

Execution Coordination Protocol v1 already separates durable GitHub task truth from ephemeral runtime claim authority. `execution-coordinator` can filter normalized `ClaimCandidate` values, but devflow does not yet provide a machine-safe source that identifies which exact owning Issue/Work Order may be normalized into a candidate and for which role.

This contract defines one opt-in, machine-readable **hash-bound projection in the managed repository's devflow Repository Control Issue**. The projection points to exact owning repository Issues/Work Orders and binds each record to the exact owning Issue body revision by SHA-256. It does not replace the owning Issue, does not make the Control a second detailed task store, and does not authorize scheduling or claim mutation by itself.

The contract answers only:

> Has the repository's canonical devflow Control explicitly projected one exact owning task/role as a current execution candidate, and does that projection still match the exact durable task body it was reviewed against?

Ranking, capability matching, scheduling, automatic claim submission, controller negotiation, and recovery of interrupted `IMPLEMENTING` work remain separate contracts.

## 2. Authority model

The existing authority split remains unchanged:

1. the owning repository Issue / Work Order remains detailed durable task authority;
2. devflow remains cross-repository policy and Repository Control authority;
3. the Control's candidate block is a **derived, hash-bound execution-discovery projection**, not a second task truth;
4. `ClaimCandidate` remains derived runtime input only;
5. execution-coordinator Issue #3 remains ephemeral execution state only;
6. GitHub Project remains derived display only.

The projection cannot make stale owning state claimable. If the owning Issue body changes after projection, the body digest no longer matches and the record fails closed until the Control is deliberately refreshed.

Free-form `Active Work` prose, Issue age, branch existence, pull-request existence, Project fields, chat history, and stale summaries are never sufficient candidate authority.

## 3. Selected representation and rejected alternatives

### Selected: Repository Control hash-bound projection

A Repository Control is already the unique cross-repository index for one managed repository. A consumer can locate exactly one open `[REPO] <repository>` Control, inspect one explicit machine block, then fetch only the owning entries named by that block.

This keeps machine discovery centralized in the existing devflow bootstrap path while leaving detailed task authority in each owning repository.

### Rejected for v1: marker inside every owning Issue

Embedding a machine marker directly in every repository-local Issue would preserve local ownership but would require heterogeneous managed repositories to adopt a new task-body format merely to participate in discovery. It would also force the discovery layer to enumerate repository-local Issues before it knows which ones are candidates.

### Rejected for v1: dedicated candidate registry/database

A separate registry would simplify enumeration but risks becoming a second durable assignment truth. The Repository Control already provides the single cross-repository index needed by v1.

## 4. Selected representation

A Control MAY contain exactly one versioned JSON block between these exact markers:

```text
<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->
{
  "schema_version": 1,
  "source_ref": "kinoko34077/devflow#17",
  "repository": "kinoko34077/jev-audit",
  "candidates": [
    {
      "task": "kinoko34077/jev-audit#17",
      "task_body_sha256": "sha256:<64 lowercase hex characters>",
      "task_work_status": "READY_FOR_IMPLEMENTATION",
      "next_action_tag": "IMPLEMENT",
      "role": "implementer",
      "entry_ref": "https://github.com/kinoko34077/jev-audit/issues/17",
      "scope_ready": true,
      "blocked": false,
      "requires_user_confirmation": false,
      "conflict_keys": []
    }
  ]
}
<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->
```

The block is intentionally opt-in:

- no block: the Control and all owning Issues remain valid, but this repository publishes no ordinary execution candidates;
- one valid block: its records may be validated and normalized;
- duplicate, partial, reversed, malformed, unsupported, stale, or contradictory blocks fail closed;
- consumers must not manufacture substitute candidates from `Active Work`, `Next Action`, PR lists, branches, labels, Project fields, or other nearby prose.

## 5. Canonical body digest

`task_body_sha256` binds the projection to the exact durable task body that was inspected when the projection was authored.

The digest algorithm is deterministic:

1. fetch the owning Issue through the GitHub API;
2. take the Issue `body` string; `null` is treated as the empty string;
3. normalize CRLF (`\r\n`) and lone CR (`\r`) to LF (`\n`);
4. do not trim leading/trailing whitespace and do not otherwise normalize Unicode;
5. encode the resulting string as UTF-8;
6. compute SHA-256;
7. serialize as `sha256:` followed by 64 lowercase hexadecimal characters.

Issue comments are not part of the digest. Adding verification/progress comments therefore does not invalidate the candidate. Editing the durable Issue body does invalidate it.

The digest is a staleness/freshness binding, not a cryptographic trust or signature mechanism.

## 6. Block schema

### 6.1 Required outer fields

`schema_version`
: Integer. MUST equal `1`.

`source_ref`
: Exact `kinoko34077/devflow#N` reference to the Control Issue containing the block. It MUST identify that exact containing Control.

`repository`
: Exact `owner/repository` identity managed by the containing Control. It MUST match the Control's canonical `Repository` field.

`candidates`
: Array of zero or more candidate records. An empty array explicitly publishes no ordinary candidate.

Unknown outer fields are rejected in v1.

### 6.2 Required candidate fields

`task`
: Exact `owner/repository#issue_number` reference. It MUST identify an Issue/Work Order in the same managed repository as the outer `repository`.

`task_body_sha256`
: Digest defined in section 5. A mismatch means the projection is stale and the record is not emitted.

`task_work_status`
: The exact durable work state that the devflow projection author reviewed for this candidate.

`next_action_tag`
: The exact action tag that the devflow projection author reviewed for this candidate, without brackets or prose.

`role`
: One of `implementer`, `reviewer`, `verifier`, `integrator`.

`entry_ref`
: Absolute canonical GitHub URL used for bootstrap/resume. It MUST identify the same owning repository. For a fresh implementer this normally identifies the owning Issue; review/verifier/integrator work may point to the exact authoritative PR when durably authorized.

`scope_ready`
: Boolean indicating whether scope and acceptance are sufficiently fixed for the requested role.

`blocked`
: Boolean indicating whether durable task state currently prohibits autonomous continuation for this candidate record.

`requires_user_confirmation`
: Boolean indicating whether a Human/User gate currently prohibits autonomous continuation.

Unknown candidate fields are rejected in v1 except the optional field defined below.

### 6.3 Optional candidate field

`conflict_keys`
: Array of unique Protocol v1 conflict keys. Omission is equivalent to `[]`. Keys must already be durably justified; consumers must never derive them from paths, file proximity, branch names, repository identity, PR diffs, or labels.

### 6.4 Projection interpretation rule

`task_work_status`, `next_action_tag`, `scope_ready`, `blocked`, `requires_user_confirmation`, and `conflict_keys` are **reviewed projection values bound to `task_body_sha256`**. The discovery consumer MUST NOT scrape or heuristically parse the owning Issue body to reconstruct these values.

The owning Issue body remains detailed durable authority. The hash binding ensures that any later body edit invalidates the reviewed projection until devflow deliberately refreshes it.

This rule is what allows heterogeneous repository-local Issue formats to remain valid without imposing a new shared task template.

## 7. ClaimCandidate mapping

After block, Control, task, digest, and lifecycle validation succeeds, mapping is direct:

| Projection field | `ClaimCandidate` |
|---|---|
| `task` | `task` |
| `role` | `role` |
| `entry_ref` | `entry_ref` |
| `conflict_keys` or omitted | `conflict_keys` / `()` |
| `scope_ready` | `scope_ready` |
| `blocked` | `blocked` |
| `requires_user_confirmation` | `requires_user_confirmation` |

`task_work_status`, `next_action_tag`, `task_body_sha256`, `source_ref`, and `repository` are discovery/provenance guards and are not added to the current `ClaimCandidate` value.

A later `list_claimable()` call combines the validated durable candidates with current runtime `CoordinatorState`. Runtime claim/conflict filtering remains execution-coordinator authority.

## 8. Ordinary role/readiness transitions

The candidate record is explicit authority to *consider* one task/role; projected lifecycle fields still guard whether it may be emitted as ordinary new work.

Supported v1 combinations are:

| Role | Required `task_work_status` | Allowed `next_action_tag` |
|---|---|---|
| `implementer` | `READY_FOR_IMPLEMENTATION` | `SPECIFY`, `IMPLEMENT` |
| `verifier` | `AWAITING_REVIEW` | `VERIFY` |
| `reviewer` | `AWAITING_REVIEW` | `REVIEW` |
| `integrator` | `AWAITING_REVIEW` | `MERGE` |

Any other combination is non-claimable ordinary work and fails closed.

In particular:

- `IMPLEMENTING` is never automatically rediscovered as fresh work merely because no live runtime claim exists;
- `BLOCKED`, `AUDITED`, `WORK_ORDER_READY`, `NEEDS_AUDIT`, `NEEDS_REAUDIT`, `PARKED`, and `DONE` are not ordinary new candidates;
- recovery/resume/takeover is a separate future contract and must reason about prior execution authority explicitly.

## 9. Human and sensitive-action boundary

`requires_user_confirmation=true` always excludes autonomous ordinary claimability.

Candidate authoring MUST set it to `true` whenever continuation still depends on:

- explicit user decision or Human Gate;
- release or deploy approval;
- publication with external effect;
- credential/session/permission changes;
- destructive deletion or shared-history rewrite;
- security-sensitive action;
- another difficult-to-reverse action requiring explicit confirmation under devflow safety policy.

The candidate projection does not weaken downstream safety gates. A runtime claim obtained from a candidate never grants permission to perform those protected operations.

`next_action_tag=USER_DECISION` is always contradictory with `requires_user_confirmation=false` and fails closed. A repository-specific Human Gate that is represented outside the canonical tag vocabulary must be projected with `requires_user_confirmation=true`; the discovery consumer must not guess it from prose.

## 10. Control-level and multi-track semantics

Repository-level Control state is not flattened into candidate state.

A single Control may summarize multiple local tracks with different readiness, such as a blocked security track and an independently executable UI track. Therefore:

- overall Control `Work Status` and free-form `Active Work` are not used to manufacture or veto individual records solely by repository-level status;
- each candidate is bound to one exact owning task body and carries its own role/readiness/blocker/user-gate projection;
- multiple candidate records are allowed when they point to distinct task/role pairs;
- the same `(task, role)` pair MUST NOT appear more than once;
- contradictory duplicate records invalidate the entire block rather than choosing one arbitrarily.

Repository State still applies at the Control level: a managed repository not in `ACTIVE` state emits no ordinary candidates in v1.

## 11. Conflict-key validation

Conflict keys use Protocol v1 classes only:

```text
repo:<owner/repo>
component:<owner/repo>:<component>
path-group:<owner/repo>:<logical-group>
contract:<stable-contract-name>
schema:<stable-schema-name>
workflow:<stable-workflow-name>
```

Rules:

- keys must be explicit strings in the projection and already durably justified by the owning task/control context;
- duplicates are invalid;
- whole-repository keys are exceptional and must not be injected by default;
- no consumer may infer keys from changed paths, file proximity, branch names, repository identity, PR diffs, or labels;
- omission means the empty tuple.

## 12. Deterministic validation algorithm

For each managed repository, a read-only consumer performs:

1. locate exactly one open `[REPO] <repository>` Control under existing devflow bootstrap rules;
2. verify Control `Repository State=ACTIVE`;
3. locate the candidate block by exact markers;
4. if absent, emit no candidates and no source error;
5. validate exact single block, JSON syntax, schema version, unknown-field prohibition, `source_ref`, and `repository`;
6. reject duplicate `(task, role)` records;
7. for each record, fetch the exact owning Issue named by `task`;
8. verify the object is an Issue, not a PR, is open, and belongs to the same managed repository;
9. compute the canonical body digest and compare it to `task_body_sha256`;
10. validate role/work-status/next-action combination from the hash-bound reviewed projection;
11. validate `entry_ref`, booleans, optional conflict keys, and Human/User gate consistency;
12. map the record to `ClaimCandidate`;
13. pass only validated candidates to the existing runtime `list_claimable()` projection.

The discovery adapter is GET/read-only. It does not edit Control or owning Issue bodies, create claims, rank candidates, or choose a winner.

## 13. Fail-closed matrix

| Condition | Result |
|---|---|
| candidate block absent | valid Control; zero discoverable candidates |
| valid block with empty `candidates` | zero candidates |
| duplicate/partial/reversed marker | source invalid; emit none from Control |
| malformed JSON | source invalid; emit none |
| unsupported schema version | source invalid; emit none |
| unknown field | source invalid; emit none |
| `source_ref` != containing Control | source invalid; emit none |
| `repository` != Control repository | source invalid; emit none |
| repository state != `ACTIVE` | no ordinary candidates |
| duplicate `(task, role)` | source invalid; emit none |
| task repository mismatch | record invalid |
| owning Issue missing/closed | record invalid |
| source object is PR | record invalid |
| body digest mismatch | stale record; do not emit |
| unsupported role/state/action combination | record invalid |
| `scope_ready=false` | may remain diagnostic input; never claimable |
| `blocked=true` | may remain diagnostic input; never claimable |
| `requires_user_confirmation=true` | may remain diagnostic input; never claimable |
| `USER_DECISION` + confirmation false | contradiction; record invalid |
| `IMPLEMENTING` with no runtime claim | not ordinary candidate; recovery path only |
| invalid/missing `entry_ref` | record invalid |
| invalid/duplicate conflict key | record invalid |
| conflict keys omitted | empty tuple; never infer |
| stale historical references outside the explicit block | ignored |

Consumers MAY expose diagnostics such as `not_discoverable`, `invalid_source`, `stale_projection`, `guard_blocked`, and `user_gate`, but diagnostics must never change the authority result.

## 14. Representative live-state fixtures

The following current shapes are conformance fixtures, not hard-coded repository exceptions.

### 14.1 Fresh bounded implementation

`jev-audit#17`-style work may be projected as an implementer candidate only when its Control explicitly publishes a record for that exact Issue/body digest with `READY_FOR_IMPLEMENTATION`, `IMPLEMENT`, `scope_ready=true`, and no blocker/Human Gate.

Status or Next Action alone remains insufficient.

### 14.2 SCA Human Gate

Structured-Cell-Automaton work awaiting interactive browser/perceived-latency judgement is not an autonomous ordinary candidate. A projection, if retained for diagnostics, must set `requires_user_confirmation=true` and therefore cannot be emitted to ordinary claimable work.

### 14.3 kotonomani Human Gate

Content/source classification and production Voice selection remain Human Gates. Technical render completion does not make that acceptance work autonomously claimable.

### 14.4 kinotch-api user decision

A `BLOCKED` credential/release-related task with `USER_DECISION` is not an ordinary candidate. Prior rollout authorization cannot be inferred as current authorization.

### 14.5 Micro-Chordbot multi-track Control

A blocked security/history track does not automatically erase the possibility of a separately projected UI track. Conversely, the UI track does not make the blocked security task claimable. Each projected candidate names one exact owning Issue and body digest; `Active Work` prose is not flattened.

### 14.6 dev_agent interrupted/externally waiting work

`IMPLEMENTING` with no current runtime claim is not fresh ordinary work. Provider/runtime waits and interrupted execution require later recovery/resume semantics, not ordinary rediscovery.

### 14.7 execution-coordinator prerequisite wait

`AUDITED / WAIT` with no repository-local implementation authority publishes no ordinary candidate until an owning task is explicitly created and projected.

### 14.8 historical preserved deltas

Closed/no-adoption recovery handoffs and stale preservation branches are not candidates unless a new current owning Issue intentionally reopens work and is explicitly projected.

## 15. Authoring lifecycle

### 15.1 Create

A candidate record is added to a Control only after an agent/human has inspected the owning task's current durable body and intentionally decided that machine discovery for the named role is appropriate. The body digest and projected guards are recorded at the same time.

### 15.2 Refresh

When the owning Issue body changes, the existing record becomes stale automatically. It remains non-discoverable until a deliberate Control refresh recomputes the digest and revalidates readiness/gate/conflict metadata.

This prevents a machine candidate from silently surviving a material scope, acceptance, blocker, or safety-boundary edit.

### 15.3 Disable

Removing the record, clearing the candidate array, or allowing the body digest to become stale disables ordinary discovery without invalidating the owning Issue.

### 15.4 Completion

Closed/DONE tasks are never ordinary candidates. Historical candidate entries should normally be removed during the next material Control update, but stale historical text outside the machine block has no authority.

### 15.5 Recovery

`IMPLEMENTING` recovery is intentionally outside this contract. A future recovery contract must use execution generation/lease/expected-state evidence rather than treating a missing live claim as permission to create a fresh one.

## 16. Migration policy

No bulk rewrite is required.

Existing managed Controls without the block remain valid and simply publish no machine-discoverable candidate. Existing repository-local Issues require no template change to remain valid.

Initial adoption should be bounded:

1. implement and verify the devflow block validator/template guidance;
2. implement the execution-coordinator read-only adapter against deterministic fixtures;
3. pilot one or a few current non-sensitive candidates, such as a fresh bounded implementation task;
4. expand only when operational evidence justifies it.

Do not add candidate records to Human-Gate, security/credential, release/deploy, destructive, stale historical, or recovery-only work merely to increase coverage.

## 17. Required later implementation slices

Acceptance of this specification does not itself authorize runtime discovery, automatic scheduling, or claim submission.

### 17.1 devflow validator/template slice

A separate bounded devflow change should add:

- optional `Execution Candidates` block guidance to the Repository Control template;
- a deterministic parser/validator for exact markers and schema v1;
- canonical owning-Issue body digest helper;
- tests for malformed/duplicate/stale/contradictory blocks and the live-state fixture classes;
- optional read-only MCP exposure of validated projection data;
- no reverse Project authority and no Project-generated candidate edits.

### 17.2 execution-coordinator discovery/normalization slice

After the devflow contract is accepted, create exactly one bounded repository-local execution-coordinator Issue that:

- reads only the explicit Control block as candidate-source authority;
- fetches the exact tasks named by the block;
- verifies canonical body digests and guards;
- maps records to current `ClaimCandidate` values;
- preserves per-source diagnostics;
- passes the result through existing `list_claimable()` runtime filtering;
- remains read-only and does not rank, claim, schedule, or mutate durable Issues.

Any provisional parser that derives candidates from headings/free-form Issue prose must be re-audited and either adapted or superseded; it cannot become canonical merely because it landed first.

### 17.3 later slices

The following remain separate:

- priority/dependency-frontier ranking;
- capability/environment matching;
- automatic claim submission;
- controller offers and agent negotiation;
- repo-monitor projection;
- richer expected-state/failure-evidence contracts;
- recovery/takeover discovery.

## 18. Security and safety boundary

This contract is permission-minimizing:

- candidate publication is explicit opt-in;
- stale owning-task bodies invalidate projections automatically;
- user/Human/sensitive gates exclude autonomy;
- runtime claims do not grant release/deploy/publication/credential/session/permission/destructive/security-sensitive authority;
- unknown or contradictory state fails closed;
- no credentials, raw secrets, session tokens, or unnecessary personal identifiers belong in candidate records.

## 19. Versioning

Marker name and `schema_version` jointly define the contract version.

A v1 consumer:

- accepts exactly one `DEVFLOW_EXECUTION_CANDIDATES_V1` block;
- requires `schema_version=1`;
- rejects unknown authority-bearing fields;
- does not reinterpret future marker versions;
- does not fall back to prose inference when v1 parsing fails.

Any change that alters field meaning, authority, lifecycle guards, digest semantics, or fail-closed behavior requires an accepted contract revision.

## 20. Acceptance and verification direction

Issue #125 is satisfied only after this design is reviewed and accepted through the normal devflow PR boundary.

The specification change itself is docs-only. Acceptance requires:

1. exact-current-head devflow verification;
2. formal independent Review v2 on the exact candidate head;
3. review-readiness and unresolved-thread checks;
4. confirmation that no runtime adapter, scheduling, claim mutation, or bulk migration is bundled into the specification PR;
5. normal merge only after the specification review gate is satisfied.

After merge, #125 may close as the accepted durable-source authority and the later execution-coordinator discovery/normalization Issue may be created from this contract.
