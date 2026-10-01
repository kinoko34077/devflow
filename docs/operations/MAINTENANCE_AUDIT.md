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

The accepted Stage-2 schedule runs once daily at `23 18 * * *` UTC (03:23 JST) and is read-only audit/triage only. The audit job uses one repository-scoped `maintenance-audit-${{ github.repository }}` concurrency group with `cancel-in-progress: false`.

It does not:

- invoke `sync-check --apply`;
- invoke `publish-supply --apply`;
- create Issues;
- merge PRs;
- rewrite semantic prose;
- create claims;
- alter credentials or permissions.

Any later automatic publisher or mutation path requires a separately accepted bounded contract change.
