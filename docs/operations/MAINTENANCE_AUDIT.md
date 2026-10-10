# Maintenance Audit Operations

## Authority

Stage-2 maintenance automation is governed by:

1. `AGENTS.md`;
2. the target open `[REPO] <repository>` Control;
3. the exact owning Issue/Work Order;
4. `docs/spec/DEVELOPMENT_RECONCILIATION.md` Section 10;
5. `devflow#215/#232` rollout state;
6. `devflow#209` for runnable supply publication;
7. execution-coordinator for runtime claim/lease/generation authority.

`devflow#249` is regression provenance/backstop only. It is not a runtime source of task truth.

## Modes

### Audit

`maintenance-audit.yml` mode `audit` is read-only.

It performs exact-source collection, deterministic audit classification, and optional deterministic triage. It may produce:

- `maintenance-audit-report.json`;
- GitHub Actions Job Summary output;
- an uploaded workflow artifact.

The audit job never edits Issues, Controls, README/Current State prose, claims, credentials, or repository settings.

### Triage

Triage consumes one maintenance audit report and maps it to the existing Development Reconciliation disposition plus one local execution decision. It never creates a second lifecycle and never manufactures an owning Issue.

Clean state, accepted future state, and active-producer yield do not create runnable work.

### Sync-check

The sole Stage-2 v1 mutation kind is:

`WITHDRAW_STALE_CONTROL_CANDIDATE`

A sync-check plan requires exact Control/owner identity, exact body-digest freshness, a terminal/non-runnable owner, the candidate still present, and no stronger producer/Human/security/reviewer/external gate.

The executor immediately re-reads exact Control and owner state before mutation, performs at most one expected-identity guarded Control-body write, re-reads after the write, and performs no stale retry loop.

Write execution is available only through an explicit manual CLI invocation:

`python scripts/maintenance_audit.py sync-check ... --apply`

The scheduled/read-only audit job never invokes this path.

### Existing-owner supply publication

Stage-2 v1 may publish only an already-existing owning Issue whose exact body/state independently satisfies the accepted candidate-source contract.

Publication reuses both existing Control projections:

- `DEVFLOW_EXECUTION_CANDIDATES_V1` for admission/freshness;
- `DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1` for scheduling metadata including `work_class`.

No new candidate schema, task database, or owner Issue is created.

The publisher records its execution-attempt identity outside the canonical candidate blocks so a later consumer can enforce 3C publication/consumption separation. A publisher must not consume a candidate it added or relaxed in the same execution attempt.

Manual publication is exposed as:

`python scripts/maintenance_audit.py publish-supply ... --apply`

and as the explicit `workflow_dispatch` mode `publish`. The workflow's default `GITHUB_TOKEN` remains read-only in both jobs; the publish operation receives write authority only from the preconfigured `MAINTENANCE_SUPPLY_TOKEN`. The audit job remains read-only.

A compact `devflow#209` transition comment is emitted only when the machine-readable supply set materially changes. Repeated identical publication is a no-op.

## Standing maintenance as broad-work fallback

Standing maintenance is predefined recurring supply backed by the repository Catalog and the standing `[MAINTENANCE] Audit Ledger`. It is not generated from idle state.

The outer broad-work order is:

```text
recoverable work
-> normal runnable work
-> predefined maintenance
-> alternate/deeper maintenance
-> portfolio maintenance
-> true NO_ELIGIBLE_WORK
```

The existing bootstrap-v1 classifier remains unchanged. Maintenance fallback runs only after ordinary `NO_ELIGIBLE_WORK`; it does not replace `NEEDS_HUMAN`, `WAIT_EXTERNAL`, or `NEEDS_EVIDENCE`.

A **repository-scoped** request remains repository-scoped and **must not** silently widen to portfolio scope. Cross-repository/portfolio maintenance is considered only when the request itself is global/portfolio-scoped.

Decision 3C applies to Catalog-backed supply exactly as it does to other publication. attempt A may select and publish, but must stop after publication. attempt B uses a new `execution_attempt_id` and fresh evidence; attempt A must be omitted as `PUBLISHED_BY_THIS_ATTEMPT`.

A final true `NO_ELIGIBLE_WORK` requires **maintenance exhaustion**: no due/overdue predefined slot, useful unexecuted Lens/Depth, eligible alternate repository within scope, portfolio slot where applicable, or security/external-freshness reason is expected to produce materially new evidence.

### PILOT rollback and re-enable

The rollout gate is reversible and belongs to maintenance eligibility, not to the normal bootstrap classifier.

For a participating repository:

1. changing Catalog `rollout` from `PILOT` to `DISABLED` makes standing maintenance ineligible as `NO_ELIGIBLE_WORK / MAINTENANCE_DISABLED`;
2. any published maintenance candidate is withdrawn through the accepted bounded withdrawal/completion path;
3. the Catalog definition and trusted Ledger/run history are retained rather than deleted or rewritten;
4. normal runnable/recovery bootstrap semantics remain unchanged because maintenance is an outer fallback after the existing bootstrap result;
5. restoring `rollout: PILOT` reuses the retained history and permits a fresh read-only selection under the same deterministic selector rules.

Task 11 controlled regression `test_rollout_disable_reenable_preserves_history_and_restores_selection` exercises the DISABLED -> PILOT round trip against the accepted collector/selector implementation. Existing supply-withdrawal and chat-fallback contract tests independently verify that rollback removes only the maintenance Ledger candidate and does not add a maintenance-specific bootstrap disposition.

### Manual catalog run completion

The accepted `complete-maintenance` CLI is exposed by the explicit
`maintenance-audit.yml` **workflow_dispatch** mode `maintenance-complete`.
It is not scheduled and does not claim, perform, or republish maintenance work.
The action reuses the existing `MAINTENANCE_SUPPLY_TOKEN`, the publisher's
per-repository concurrency group, and the script's exact Ledger/Control
read-before-write/readback checks; the default Actions token stays read-only.

Supply `repository`, `control`, `run_id`, `lens`, `result`, `attempt_id`,
and an `evidence_ref` pointing to a trusted Issue comment on that repository.
For this mode alone, the existing `owner` workflow input carries the bounded
`findings_summary` (required when `result=FINDINGS`). In all other modes,
`owner` retains its documented existing-owner reference meaning. This
explicit alias avoids exceeding GitHub's ten `workflow_dispatch` inputs.

Before dispatch, verify the claim has already been released and the named
run was actually audited under a separate 3C consumer attempt. Do not use
completion to skip claim/release or invent audit evidence.
The action fails closed on malformed inputs and uploads a typed
`maintenance-completion-result` artifact. After SUCCESS, confirm
`applied=true`, `reconciliation_required=false`, a trusted canonical
`devflow-maintenance-run:v1` history comment, cleared Ledger Active Run,
an empty Control candidate/portfolio for the completed run and no
coordinator claim. On partial failure, retain the evidence, reconcile the
exact persisted state and **do not blindly replay** the mutation.
## Credentials

Credential creation, rotation, storage, permission changes, and GitHub App/PAT setup are Human/security-gated.

The implementation may consume already-approved secrets:

- `MAINTENANCE_AUDIT_TOKEN` for cross-repository read-only portfolio audit;
- `MAINTENANCE_SYNC_TOKEN` for explicit manual sync-check apply;
- `MAINTENANCE_SUPPLY_TOKEN` for explicit manual supply publication/withdrawal.

Absence of a required credential is a blocker. The automation must not create, broaden, or replace credentials.

## Failure and recovery

Required-source failure, ambiguity, identity mismatch, or stale freshness returns to `NEEDS_EVIDENCE`; it is never reported as clean.

If a stronger gate appears after planning, mutation is skipped and the corresponding existing disposition is preserved.

If a write is not confirmed by immediate exact readback, the operation stops. No automatic retry loop reuses the stale plan.

## Scheduled path

The accepted Stage-2 schedule runs once daily at `30 13 * * *` UTC (22:30 JST) and is read-only audit/triage only. The audit job uses one repository-scoped `maintenance-audit-${{ github.repository }}` concurrency group with `cancel-in-progress: false`.

It does not:

- invoke `sync-check --apply`;
- invoke `publish-supply --apply`;
- create Issues;
- merge PRs;
- rewrite semantic prose;
- create claims;
- alter credentials or permissions.

Any later automatic publisher or mutation path requires a separately accepted bounded contract change.
