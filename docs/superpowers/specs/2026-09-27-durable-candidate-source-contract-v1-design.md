# Durable Candidate Source Contract v1

Status: proposed for devflow Issue #125  
Parent: devflow #105  
Protocol authority: devflow #106 / merged PR #108  
Runtime consumer: `kinoko34077/execution-coordinator`

## 1. Purpose

Execution Coordination Protocol v1 separates durable GitHub task truth from ephemeral runtime claim authority. `execution-coordinator` can filter normalized `ClaimCandidate` values, but devflow needs one deterministic source that identifies which exact owning Issue/Work Order may be considered for one execution role without scraping free-form prose or creating a second assignment database.

This contract defines an opt-in, machine-readable **hash-bound projection in the managed repository's devflow Repository Control Issue**. Each projection record points to one exact owning repository Issue and is bound to the exact durable Issue body revision that was reviewed when the record was published.

The contract answers only:

> Has the repository's canonical devflow Control deliberately published one exact task/role as a current ordinary execution candidate, and is that projection still bound to the durable task revision and safety guards that were reviewed?

It does not rank candidates, match capabilities, schedule workers, create claims, recover interrupted `IMPLEMENTING` work, or authorize release/deploy/publication/security-sensitive operations.

## 2. Authority model

The existing authority split remains:

1. the owning repository Issue / Work Order remains detailed durable task authority;
2. devflow remains cross-repository policy and Repository Control authority;
3. the Control candidate block is a **derived, hash-bound execution-discovery projection**, not a detailed task store;
4. `ClaimCandidate` remains derived runtime input only;
5. execution-coordinator Issue #3 remains ephemeral execution state only;
6. GitHub Project remains derived display only.

The projection cannot make stale owning state claimable. If the owning Issue body changes after publication, the body digest no longer matches and the record fails closed until deliberately refreshed.

Free-form `Active Work`, repository-local prose outside the owning Issue body, Issue age, branch existence, PR existence, labels, Project fields, chat history, and stale summaries are never sufficient candidate authority.

### 2.1 No self-publication during selection

Discovery/selection is read-only.

A worker/session consuming candidate sources MUST NOT add, remove, refresh, or relax the candidate record that would make itself eligible as part of the same discovery/selection attempt. Candidate publication or refresh is a separate durable Control mutation that completes before a later discovery cycle evaluates the result.

This is a procedural authority boundary, not a cryptographic identity claim. The same agent technology may author and later consume a record in separate operations, but a single selection operation cannot manufacture its own eligibility.

## 3. Selected representation and alternatives

### 3.1 Selected: Repository Control hash-bound projection

A Repository Control is already the unique cross-repository bootstrap/index surface for one managed repository. A consumer can locate exactly one open `[REPO] <repository>` Control, inspect one explicit machine block, then fetch only the owning Issues named by that block.

This supports heterogeneous repository-local Issue formats and multi-track repositories without parsing `Active Work` prose.

### 3.2 Why not require a marker in every local Issue

A local marker would preserve locality but would impose a new shared body format across heterogeneous repositories and would still require a discovery enumeration strategy before the consumer knows which local Issues matter.

### 3.3 Why not use a separate registry/database

A separate registry would simplify enumeration but would risk becoming a second durable assignment truth. The existing Repository Control already supplies the cross-repository projection boundary needed by v1.

## 4. Canonical representation

A Control MAY contain exactly one JSON block between these exact markers:

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
      "conflict_keys": [],
      "work_order_ref": "kinoko34077/devflow#105"
    }
  ]
}
<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->
```

The block is opt-in:

- no block: valid Control, zero machine-discoverable ordinary candidates;
- one valid block: its records may be validated;
- duplicate, partial, reversed, malformed, unsupported, stale, or contradictory block: fail closed;
- an empty `candidates` array explicitly publishes no ordinary candidates;
- consumers never reconstruct substitute records from surrounding prose.

## 5. Owning task revision and body digest

`task_body_sha256` binds each projection record to the exact owning Issue body inspected during publication.

Canonical digest algorithm:

1. fetch the owning Issue through GitHub API;
2. require an open Issue rather than a pull request;
3. take its `body` string; `null` is treated as the empty string;
4. normalize CRLF (`\r\n`) and lone CR (`\r`) to LF (`\n`);
5. do not trim whitespace and do not otherwise normalize Unicode;
6. UTF-8 encode the resulting string;
7. compute SHA-256;
8. serialize as `sha256:` plus 64 lowercase hexadecimal characters.

A missing or whitespace-only owning body is not sufficient durable scope for an ordinary candidate and is rejected.

Issue comments are intentionally excluded from the digest so routine progress/evidence comments do not invalidate discovery. This creates an explicit authoring rule for candidate-enabled tasks:

> Any durable change to scope, acceptance, lifecycle readiness, blocker state, Human/User gate, sensitive-operation boundary, or other fact that could change ordinary candidate eligibility MUST be reconciled into the owning Issue body and/or the Control candidate record before that change is treated as current machine-discovery authority.

A comment may carry discussion, evidence, review detail, or progress. A candidate-relevant decision recorded only in a comment is not sufficient to leave an old permissive candidate record authoritative; the authoring/coordination workflow must reconcile the body/record first. Until reconciliation, automation must not treat the unreconciled comment as permission to broaden autonomy.

The digest is a freshness binding, not a signature or trust proof.

## 6. Block schema

### 6.1 Required outer fields

`schema_version`
: Integer. MUST equal `1`.

`source_ref`
: Exact `kinoko34077/devflow#N` reference to the Control containing the block. It MUST identify that exact open Control.

`repository`
: Exact `owner/repository` identity managed by the containing Control. It MUST match the Control's canonical `Repository` field.

`candidates`
: Array of zero or more candidate records.

Unknown outer fields are rejected in v1.

### 6.2 Required candidate fields

`task`
: Exact `owner/repository#issue_number`. It MUST identify an owning Issue in the same managed repository as the outer `repository`.

`task_body_sha256`
: Canonical digest from section 5. Mismatch means stale projection and no emission.

`task_work_status`
: Reviewed **task-specific projection** of the current durable lifecycle phase for this candidate. It uses the devflow Work Status vocabulary but does not require the repository-local Issue to expose a standardized Work Status heading.

`next_action_tag`
: Reviewed **task-specific projection** of the current action required for this candidate, without brackets/prose. It uses the accepted action vocabulary defined in section 8.

`role`
: One of `implementer`, `reviewer`, `verifier`, `integrator`.

`entry_ref`
: Explicit canonical `https://github.com/...` URL used to bootstrap the role. It MUST identify the same owning repository. Consumers do not search for a substitute entry.

`scope_ready`
: Boolean indicating whether role-specific scope and acceptance are sufficiently fixed for ordinary consideration.

`blocked`
: Boolean indicating whether task-specific durable state currently prohibits autonomous continuation for this role.

`requires_user_confirmation`
: Boolean indicating whether a Human/User/sensitive-action gate currently prohibits autonomous continuation for this role.

Unknown candidate fields are rejected except the optional fields below.

### 6.3 Optional candidate fields

`conflict_keys`
: Array of unique Protocol v1 conflict keys. Omission equals `[]`. Consumers never infer keys from paths, repository identity, branch names, PR diffs, labels, or file proximity.

`work_order_ref`
: Exact `kinoko34077/devflow#N` reference to the governing cross-repository Work Order when one exists. Omission means no governing Work Order is asserted for this candidate. If present, the referenced devflow Issue MUST be open, MUST identify a `[WORK ORDER]` under current devflow conventions, and MUST NOT be rediscovered by reverse prose/link scraping. A closed/DONE Work Order cannot authorize fresh ordinary work.

### 6.4 Projection interpretation

The candidate fields are reviewed projection values bound to `task_body_sha256`. They are not produced by heuristic local-body parsing.

The owning Issue remains detailed task authority. `source_ref` provides Repository Control provenance, `work_order_ref` provides optional governing cross-repository provenance, and `task` names the detailed owning entry. The Control projection supplies only the bounded machine-readable execution-discovery view needed by this protocol.

Publication/refresh must inspect the exact owning body and current relevant devflow/safety context. Hash equality proves only that the body has not changed since projection; it does not prove that the projection was semantically correct. Normal Issue-first authoring, review, and the fail-closed checks in this specification remain required.

## 7. Cross-record consistency

The block is validated as a set, not only record-by-record.

- `(task, role)` MUST be unique.
- All records sharing the same `task` MUST carry the same current `task_body_sha256`.
- All records sharing the same `task` MUST carry the same `task_work_status`.
- If either shared value differs, every record for that task is invalid and none is emitted.
- `next_action_tag`, `scope_ready`, `blocked`, `requires_user_confirmation`, `conflict_keys`, and `work_order_ref` MAY differ by role only when the difference is intentionally role-specific and satisfies this contract. If one durable task is governed by one cross-repository Work Order, role records SHOULD use the same `work_order_ref`.

This prevents one durable task from simultaneously being projected as fresh implementation work and review/integration work under contradictory lifecycle phases.

## 8. Ordinary role/readiness transitions

Supported v1 combinations are:

| Role | Required `task_work_status` | Allowed `next_action_tag` |
|---|---|---|
| `implementer` | `READY_FOR_IMPLEMENTATION` | `SPECIFY`, `IMPLEMENT` |
| `verifier` | `AWAITING_REVIEW` | `VERIFY` |
| `reviewer` | `AWAITING_REVIEW` | `REVIEW` |
| `integrator` | `AWAITING_REVIEW` | `MERGE` |

Any other combination fails closed for ordinary new discovery.

In particular:

- `IMPLEMENTING` is never rediscovered as fresh work merely because no runtime claim exists;
- `BLOCKED`, `AUDITED`, `WORK_ORDER_READY`, `NEEDS_AUDIT`, `NEEDS_REAUDIT`, `PARKED`, and `DONE` are not ordinary candidate phases;
- recovery/resume/takeover is a separate contract and must reason about previous execution authority.

The projected status/action values are candidate-source data. Repository-level Control `Work Status` is not blindly flattened across multiple local tracks.

## 9. Current Control safety guards

The candidate block lives in the Repository Control, but the Control also has canonical repository-level fields that remain current safety guards.

A consumer MUST verify:

- exactly one current open `[REPO] <repository>` Control exists;
- Control `Repository` matches the block `repository`;
- Control `Repository State` is `ACTIVE`;
- the canonical Control `Next Action` section does not contain `[USER_DECISION]`;
- the canonical Control `Next Action` section does not contain the literal compatibility token `[HUMAN_GATE]`.

`[HUMAN_GATE]` is a conservative compatibility veto for current managed handoffs; it is not added to `.devflow/WORKFLOW.yaml` canonical action vocabulary by this contract.

A repository-level user/Human gate therefore vetoes all ordinary candidates until the Control summary is reconciled. This can temporarily reduce parallelism in an ambiguous multi-track repository, but it prevents a stale candidate record from bypassing an explicit current human boundary. A later protocol revision may add finer per-track cross-repository guard semantics if operational evidence justifies it.

Control `Work Status` and free-form `Active Work` are not used to manufacture individual candidate records. A repository-level `BLOCKED` summary alone does not identify which track is blocked; candidate-specific lifecycle truth remains in the explicit records, while explicit repository-level user/Human gates remain global vetoes.

## 10. Human and sensitive-action boundary

`requires_user_confirmation=true` always excludes autonomous ordinary claimability.

Candidate publication MUST set it true whenever continuation still depends on:

- explicit user decision or Human Gate;
- release or deploy approval;
- publication with external effect;
- credential/session/permission change;
- destructive deletion or shared-history rewrite;
- security-sensitive action;
- another difficult-to-reverse action requiring confirmation under devflow policy.

A runtime claim never grants permission to perform these protected operations.

`next_action_tag=USER_DECISION` is always contradictory with `requires_user_confirmation=false` and invalid. `USER_DECISION` is not an allowed ordinary action combination in section 8, so such a record is never emitted as ordinary work.

Repository-specific Human Gates that are not canonical action tags must be represented by `requires_user_confirmation=true`; the consumer does not scrape arbitrary task prose for gate words. The current Control-level compatibility veto in section 9 independently prevents a visible `[HUMAN_GATE]` summary from being bypassed.

## 11. Multi-track semantics

A single Control may summarize multiple local tracks. The candidate block therefore MAY carry multiple records for different exact tasks/roles.

- A blocked security/history task and an independently executable UI task are distinct records.
- `Active Work` prose is not flattened into records.
- overall Control Work Status is not treated as a task identifier.
- same-task records still obey section 7 cross-record lifecycle consistency.
- repository-level USER_DECISION/HUMAN_GATE remains a conservative global veto under section 9.

This permits multi-track discovery when the Control is not globally human-gated while failing closed when the cross-repository summary itself says user judgement is the next repository-level boundary.

## 12. Conflict-key validation

Allowed Protocol v1 classes remain:

```text
repo:<owner/repo>
component:<owner/repo>:<component>
path-group:<owner/repo>:<logical-group>
contract:<stable-contract-name>
schema:<stable-schema-name>
workflow:<stable-workflow-name>
```

Rules:

- keys must be explicit and durably justified;
- duplicates are invalid;
- whole-repository keys are exceptional rather than default;
- omission means empty tuple;
- consumers never infer keys from implementation proximity or metadata.

## 13. ClaimCandidate mapping

After source, Control, task, digest, set-consistency, lifecycle, provenance, entry, and safety validation succeeds:

| Projection field | `ClaimCandidate` |
|---|---|
| `task` | `task` |
| `role` | `role` |
| `entry_ref` | `entry_ref` |
| `conflict_keys` or omitted | `conflict_keys` / `()` |
| `scope_ready` | `scope_ready` |
| `blocked` | `blocked` |
| `requires_user_confirmation` | `requires_user_confirmation` |

`task_work_status`, `next_action_tag`, `task_body_sha256`, `source_ref`, `repository`, and `work_order_ref` are discovery/provenance guards rather than new `ClaimCandidate` fields.

Compatible records with `scope_ready=false`, `blocked=true`, or `requires_user_confirmation=true` MAY be normalized for diagnostics, but existing `list_claimable()` must exclude them. Invalid/stale/contradictory records are not normalized into authoritative candidates.

## 14. Deterministic validation algorithm

For one managed repository:

1. locate exactly one open `[REPO] <repository>` Control using existing devflow bootstrap rules;
2. validate `Repository`, `Repository State=ACTIVE`, and the current Control human-gate vetoes in section 9;
3. locate the candidate block by exact markers;
4. if absent, return zero candidates without source error;
5. validate exact single block, JSON syntax, schema version, unknown-field prohibition, `source_ref`, and `repository`;
6. validate unique `(task, role)` and section 7 cross-record consistency;
7. for each distinct task, fetch the exact owning Issue;
8. verify same repository, open Issue, not PR, and non-empty durable body;
9. compute canonical body digest and compare every record for that task;
10. validate role/status/action combinations;
11. validate optional `work_order_ref` structurally when present;
12. validate `entry_ref`, booleans, conflict keys, and sensitive/Human gates;
13. map valid records to `ClaimCandidate`;
14. pass normalized candidates to existing runtime `list_claimable()` filtering.

The discovery adapter is GET/read-only. It does not mutate Controls or owning Issues, publish candidate records, rank work, choose a winner, or submit claims.

## 15. Fail-closed matrix

| Condition | Result |
|---|---|
| candidate block absent | valid Control; zero candidates |
| valid block with empty candidates | zero candidates |
| duplicate/partial/reversed marker | source invalid; emit none from Control |
| malformed JSON / unsupported schema / unknown field | source invalid; emit none |
| `source_ref` mismatch | source invalid; emit none |
| repository mismatch | source invalid; emit none |
| Repository State != `ACTIVE` | zero ordinary candidates |
| Control Next Action contains `[USER_DECISION]` | zero ordinary candidates |
| Control Next Action contains `[HUMAN_GATE]` | zero ordinary candidates |
| duplicate `(task, role)` | source invalid; emit none |
| same task has inconsistent digest or lifecycle status | all records for that task invalid |
| task repository mismatch | record invalid |
| owning Issue missing/closed/PR/empty body | record invalid |
| body digest mismatch | stale record; do not emit |
| unsupported role/status/action | record invalid |
| invalid optional Work Order provenance | record invalid |
| `scope_ready=false` | diagnostic candidate allowed; never claimable |
| `blocked=true` | diagnostic candidate allowed; never claimable |
| `requires_user_confirmation=true` | diagnostic candidate allowed; never claimable |
| USER_DECISION + confirmation false | contradiction; record invalid |
| IMPLEMENTING with no runtime claim | no ordinary candidate; recovery only |
| invalid/missing entry | record invalid |
| invalid/duplicate conflict key | record invalid |
| conflict keys omitted | empty tuple; never infer |
| stale references outside explicit block | ignored |

Diagnostic names such as `not_discoverable`, `invalid_source`, `stale_projection`, `guard_blocked`, and `user_gate` are implementation details and never relax authority results.

## 16. Representative live-state fixtures

### 16.1 Fresh bounded implementation

`jev-audit#17` itself does not need a standardized Work Status field. Its devflow Control may deliberately publish an implementer record for that exact Issue/body digest with projected `READY_FOR_IMPLEMENTATION`, `IMPLEMENT`, `scope_ready=true`, and no blocker/Human Gate. If that task is governed by a cross-repository Work Order, the record also carries the explicit `work_order_ref`; otherwise it is omitted.

Status or Next Action prose alone remains insufficient; the explicit hash-bound record is required.

### 16.2 SCA Human Gate

Structured-Cell-Automaton work awaiting interactive judgement is non-autonomous. A candidate-specific record must carry `requires_user_confirmation=true`; additionally, a visible repository-level Control `[HUMAN_GATE]` vetoes all ordinary candidates until reconciled.

### 16.3 kotonomani Human Gate

Content/source classification and production Voice selection remain Human Gates. Technical render completion does not make that acceptance work autonomously claimable.

### 16.4 kinotch-api user decision

Credential/release-related work with a current user-decision boundary is not ordinary autonomous work. A Control `[USER_DECISION]` vetoes ordinary candidates and prior rollout authorization cannot be inferred as current permission.

### 16.5 Micro-Chordbot multi-track Control

A blocked security/history task and an independent UI track are separate candidate records. The UI track may remain discoverable only if the Control is not globally marked with a current USER_DECISION/HUMAN_GATE. Automation never parses `Active Work` prose to decide which track a gate belongs to.

### 16.6 dev_agent interrupted work

`IMPLEMENTING` with no current runtime claim is not fresh ordinary work. Recovery requires a later contract using generation/lease/expected-state evidence.

### 16.7 execution-coordinator prerequisite wait

A repository with no active owning implementation authority publishes no ordinary candidate. AUDITED/WAIT summaries do not manufacture work.

### 16.8 historical preserved deltas

Closed/no-adoption recovery handoffs and stale branches are not candidates unless a new current owning Issue deliberately reopens work and is explicitly projected.

## 17. Authoring lifecycle

### 17.1 Publish

Publication is a deliberate devflow Control mutation after an agent/human inspects the current owning task body, governing Work Order when present, relevant safety state, and intended role.

Publication is not part of discovery/selection. A later read-only selection cycle consumes the committed record.

### 17.2 Refresh

Refresh is required when:

- owning Issue body changes;
- projected role/status/action/readiness/blocker/user-gate/conflict metadata changes;
- governing Work Order relationship/state changes;
- relevant safety authority changes;
- the candidate entry point changes.

The publisher recomputes the digest and revalidates the record. If uncertain, remove/disable the record rather than preserve a permissive stale projection.

### 17.3 Disable

Remove the record, clear the array, or leave it stale. All three prevent ordinary discovery; removing/clearing is preferred when the track is intentionally no longer discoverable.

### 17.4 Completion

Closed/DONE work is never ordinary candidate work. Historical candidate entries should be removed during the next material Control update, but stale text outside the machine block has no authority.

### 17.5 Recovery

`IMPLEMENTING` recovery, lease loss, generation takeover, and interrupted session admission are outside this contract.

## 18. Migration policy

No bulk rewrite is required.

Existing Controls without the block remain valid and publish no machine-discoverable candidate. Existing local Issues require no common template change.

Initial adoption should be bounded:

1. accept this source contract;
2. add a devflow validator/template helper;
3. conform execution-coordinator read-only discovery;
4. pilot one or a few current non-sensitive candidate records;
5. expand only after operational evidence.

Do not add candidate records merely for coverage to Human-Gate, security/credential, release/deploy, destructive, stale historical, or recovery-only work.

## 19. Required later slices

### 19.1 devflow validator/template

A separate bounded change should add:

- optional candidate-block guidance to Repository Control template;
- deterministic block parser/validator;
- canonical owning-body digest helper;
- validation of cross-record consistency, Work Order provenance, and Control global gates;
- tests for malformed/duplicate/stale/contradictory blocks and live fixtures;
- optional read-only MCP exposure of validated projection data;
- no Project-to-Issue reverse authority.

### 19.2 execution-coordinator discovery/normalization

Only after this contract and the devflow validator boundary are accepted, conform execution-coordinator #28 so it:

- reads only explicit Control candidate blocks as candidate-source authority;
- fetches exact tasks named by the block;
- verifies body digests, set consistency, Work Order provenance, lifecycle, entry and safety guards;
- maps records to current `ClaimCandidate` values;
- preserves per-source diagnostics;
- passes normalized candidates through existing `list_claimable()`;
- remains read-only and does not rank, schedule, publish source records, or submit claims.

The provisional free-form Issue heading parser must be adapted, superseded, or normally reverted; it cannot remain canonical source authority.

### 19.3 later independent slices

Keep separate:

- priority/dependency-frontier ranking;
- capability/environment matching;
- automatic claim submission;
- controller offers/agent negotiation;
- repo-monitor projection;
- richer expected-state/failure-evidence contracts;
- recovery/takeover discovery.

## 20. Security and safety boundary

- candidate publication is explicit opt-in;
- discovery/selection cannot self-publish eligibility;
- stale task bodies invalidate records;
- explicit current Control user/Human gates veto ordinary candidates;
- candidate-specific sensitive gates exclude autonomy;
- runtime claims never grant release/deploy/publication/credential/session/permission/destructive/security-sensitive authority;
- incomplete/conflicting evidence fails closed;
- credentials, secrets, session tokens, and unnecessary personal identifiers never belong in candidate records.

## 21. Versioning

A v1 consumer:

- accepts exactly one `DEVFLOW_EXECUTION_CANDIDATES_V1` block;
- requires `schema_version=1`;
- rejects unknown authority-bearing fields;
- does not reinterpret future versions;
- never falls back to prose inference when parsing/validation fails.

Changes to field meaning, authority, role/lifecycle compatibility, provenance, body-digest semantics, safety gates, or fail-closed behavior require an accepted contract revision.

## 22. Acceptance and verification direction

Issue #125 is satisfied only after this written design is accepted through the normal devflow PR boundary.

The spec change is docs-only. Acceptance requires:

1. exact-current-head devflow verification;
2. a fresh current-head Formal Review v2 with no unresolved blocking finding;
3. review-readiness and unresolved-thread checks;
4. confirmation that no runtime adapter, scheduling, claim mutation, Project reverse authority, or bulk migration is bundled;
5. normal merge under the standing reversible-change policy.

After merge, #125 may return to `DONE`, #107 may leave `NEEDS_REAUDIT`, and execution-coordinator #28 may resume from this exact contract.