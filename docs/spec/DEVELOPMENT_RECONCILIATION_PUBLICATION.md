# Development Reconciliation Work Publication Contract

Status: Canonical specification owned by devflow#159  
Authority: devflow cross-repository workflow specification  
Parent decision contract: `DEVELOPMENT_RECONCILIATION.md` / `development-reconciliation.v1`  
Schema: `development-reconciliation-work.v1`

## 1. Purpose

This contract defines the machine-readable work-demand envelope produced when the accepted Development Reconciler proves that another bounded execution role is required.

The initial supported roles are:

- `reviewer` for an unsatisfied explicit different-reviewer requirement;
- `recovery` for an accepted stale/interrupted-session recovery boundary.

A publication is **demand, not assignment**. It does not claim work, choose a worker/provider, create a lease, advance durable task completion, or replace execution-coordinator runtime authority.

## 2. Authority boundary

The authority chain is:

```text
owning Issue / Work Order durable truth
-> validated development-reconciliation.v1 result
-> development-reconciliation-work.v1 publication
-> unique devflow Repository Control projection
-> later accepted consumer such as execution-coordinator
-> serialized runtime claim/lease/generation authority
```

The publication MUST NOT be manufactured from Project fields, labels, branch existence, chat text, title heuristics, or free-form prose.

The publication layer introduces no private queue database. Active demand is a deterministic projection of current accepted evidence into the unique trusted `[REPO] <repository>` Control. Re-evaluation may retain the same logical publication, supersede it, or remove it when demand no longer exists.

## 3. Common envelope

Every publication has these fields:

```json
{
  "schema_version": "development-reconciliation-work.v1",
  "publication_id": "sha256:<logical-evidence-digest>",
  "task_ref": "owner/repository#7",
  "task_body_sha256": "sha256:<owning-body-digest>",
  "entry_ref": "https://github.com/owner/repository/issues/7",
  "role": "reviewer",
  "disposition": "NEEDS_REVIEWER",
  "reason_codes": ["DIFFERENT_REVIEWER_REQUIRED"],
  "scope": "bounded role acceptance scope",
  "requires_user_confirmation": false,
  "observed_at": "2026-09-28T05:00:00Z",
  "freshness": {
    "source_contract_version": "development-reconciliation.v1",
    "task_body_sha256": "sha256:<owning-body-digest>"
  },
  "context": {}
}
```

Required invariants:

- `task_ref` and `entry_ref` identify the same exact owning Issue;
- `task_body_sha256` is the exact body freshness binding used by the publication;
- `disposition` is copied from the accepted Reconciler vocabulary, never invented here;
- `reason_codes` preserve the reconciler reason evidence;
- `requires_user_confirmation` is `false` for a publishable reviewer/recovery record; an active Human Gate suppresses publication rather than producing autonomous work demand;
- `observed_at` is a timezone-aware RFC-3339 timestamp and records observation time but does not participate in logical deduplication identity.

Incomplete, malformed, stale, contradictory, unsupported or identity-mismatched required evidence fails closed and MUST NOT be converted into a publication.

## 4. Reviewer context

A reviewer publication is valid only when:

- disposition is exactly `NEEDS_REVIEWER`;
- accepted policy explicitly requires a different reviewer;
- the PR number and exact current head SHA are known;
- no Human/confirmation gate suppresses automation.

Context:

```json
{
  "pr_number": 12,
  "pr_head_sha": "<40-hex exact head>"
}
```

An ordinary PR for which implementer-authored Formal Review is sufficient under devflow#111 MUST NOT emit reviewer work merely because a Formal Review exists or because the task is P1/MEDIUM.

A head change changes logical publication identity. Once the qualifying different-reviewer gate is satisfied, the desired publication becomes absent and the prior record is superseded.

## 5. Recovery context

A recovery publication is valid only when:

- disposition is exactly `NEEDS_RECOVERY`;
- devflow#158 has already established the stale/interrupted boundary under #142/#144 semantics;
- predecessor Session identity, checkpoint and first safe next action are explicit;
- recovery transition is one of:
  - `RECOVERY_ASSESSMENT`;
  - `SUCCESSOR_ELIGIBILITY_EVALUATION`;
- relevant durable artifact references are explicit when they exist;
- no Human/confirmation gate suppresses automation.

Context:

```json
{
  "predecessor_session_id": "session-7",
  "checkpoint": "implementation committed",
  "next_action": "run the repository regression suite",
  "recovery_transition": "RECOVERY_ASSESSMENT",
  "artifact_refs": ["refs/heads/work/7"]
}
```

The publication does not rewrite the predecessor Session Record and does not itself perform takeover. A successor worker creates its own Session Record after the accepted allocation/claim boundary.

## 6. Logical identity and idempotency

`publication_id` is the SHA-256 of canonical JSON containing the logical evidence identity:

- schema version;
- source reconciliation contract version;
- task reference;
- owning-task body digest;
- entry reference;
- role;
- disposition;
- normalized reason codes;
- bounded scope;
- role-specific context.

`observed_at` is intentionally excluded. Re-observing unchanged logical evidence therefore yields the same publication ID.

A change to exact PR head, owning-task body digest, recovery checkpoint/context, disposition, role or bounded scope produces a different publication ID.

## 7. Supersession

For one `(task_ref, role)` pair, reconciliation against current evidence produces at most one desired logical publication.

- same `publication_id` -> retain; duplicate delivery is a no-op;
- different desired ID -> retain the new publication and mark older publications for that `(task_ref, role)` superseded;
- no desired publication -> supersede all prior active publications for that `(task_ref, role)`;
- publications for other tasks/roles remain untouched.

Supersession is derived from current authority. It is not evidence that a worker completed the published work.

## 8. Canonical Repository Control projection

The machine-readable GitHub publication surface is a dedicated block in the unique trusted devflow Repository Control for the owning repository.

Markers:

```text
<!-- DEVFLOW_RECONCILIATION_WORK_V1_BEGIN -->
<canonical JSON>
<!-- DEVFLOW_RECONCILIATION_WORK_V1_END -->
```

Payload:

```json
{
  "schema_version": "development-reconciliation-work.v1",
  "repository": "owner/repository",
  "publications": []
}
```

Rules:

- zero marker pairs means no active reconciliation work publication;
- exactly one marker pair is allowed;
- duplicate, reversed, malformed, unknown-field or repository-mismatched projection evidence fails closed;
- publication IDs inside one projection are unique;
- every publication `task_ref` belongs to the projected repository;
- replacement is deterministic and idempotent;
- when no active publications remain, the dedicated block is removed rather than retained as stale queue state;
- this block is separate from the accepted `DEVFLOW_EXECUTION_CANDIDATES_V1` admission projection. A reconciliation publication does not become an execution candidate until the separately gated downstream adoption path explicitly consumes it.

The Control remains a cross-repository projection. The owning Issue/Work Order remains detailed durable task truth.

## 9. Consumer boundary

`execution-coordinator#49` may later adopt this schema only after its own Control/audit gates and explicit devflow release are satisfied.

A consumer MUST:

- read only the trusted unique Repository Control publication projection;
- validate exact task/source/freshness identity;
- preserve role-specific demand without inventing new reconciliation semantics;
- preserve publication/consumption separation from devflow#125;
- preserve Human/confirmation vetoes;
- preserve serialized claim/lease/generation authority as the only atomic execution ownership decision.

The schema intentionally contains no provider, selected worker, claim ID, lease, assignment, scheduler score, or provider-launch instruction.

## 10. Implementation mapping

Reference implementation:

- `tools/reconciliation_publication.py`
- `tests/test_reconciliation_publication.py`
- `tests/test_reconciliation_publication_validation.py`
- `tests/test_reconciliation_publication_projection.py`

The implementation derives/deduplicates role demand and deterministically renders, parses, replaces or removes the canonical Repository Control projection. Actual execution-coordinator role adoption remains the separately gated responsibility of execution-coordinator#49.

## Related authority

- devflow#155 — Development Reconciliation Loop parent
- devflow#156 — accepted deterministic Reconciler contract
- devflow#157 — accepted PR/review/merge reconciliation
- devflow#158 — accepted stale/interrupted-session assessment
- devflow#159 — this publication slice
- devflow#111 — conditional different-reviewer policy
- devflow#125 — candidate publication/consumption separation and freshness authority
- execution-coordinator#49 — downstream runtime adoption, separately gated
