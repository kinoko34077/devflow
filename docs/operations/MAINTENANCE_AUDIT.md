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

## Standing Maintenance PILOT acceptance and rollout decision

Task 11 acceptance under `devflow#363` completed the required evidence matrix and reversible rollout proof for the Standing Maintenance Catalog.

Accepted pilot evidence includes:

- devflow Task 9: deterministic/explainable selection, 3C publisher/consumer separation, serialized claim + acknowledge, Ledger-only completion, bounded-Issue promotion, interrupted successor resume without replay, alternate-Lens rotation, and true `NO_ELIGIBLE_WORK` after controlled exhaustion;
- execution-coordinator Task 10: cross-repository publication, duplicate-claim fencing, one bounded `common.correctness / STANDARD` run, candidate withdrawal, and clean final runtime state;
- selector/regression evidence for justified DEEP, same-audit suppression, external freshness with unchanged code SHA, repository-bias penalty, and portfolio selection;
- no duplicate catalog/history/projection authority and no weakening of Human/security/credential/session/permission gates.

Rollback/re-enable proof used `kinoko34077/execution-coordinator`:

- PR #129 changed only catalog rollout `PILOT -> DISABLED`; exact-head Verify `37698646772`, Formal Review `5449379595`, merge `78bb6a930be7b668fcbc8ac42aa569a840c67572`, and post-main Verify `37698886593` were clean;
- with rollout `DISABLED`, read-only maintenance selection returned `NO_ELIGIBLE_WORK / MAINTENANCE_DISABLED`; ordinary `/pickup` remained on the existing normal bootstrap path and returned `NO_ELIGIBLE_WORK / NO_CANDIDATES_PUBLISHED`; Ledger history remained intact and runtime claims remained empty;
- PR #130 restored only `DISABLED -> PILOT`; exact-head Verify `37699092017`, Formal Review CLEAN, merge `2cf67fd5d9bc169f8f7c5f17851dcf323779f5ab`, and post-main Verify `37699167087` were clean;
- after restoration, read-only selector run `37654926004` attempt 4 returned `MAINTENANCE_SELECTED` for `common.dependency-external-assumptions / STANDARD`, score `80`; no Ledger activation, Control candidate publication, or runtime claim was created.

### Rollout decision

The accepted outcome is **expand PILOT, not fleet-wide ENABLED**.

- `devflow` and `execution-coordinator` remain accepted `PILOT` participants.
- The next rollout stage may onboard **at most one additional control-plane repository** through its own repository-local catalog/Ledger/PR/verification path.
- That additional onboarding is separate work and must not be inferred as already enabled by this decision.
- Fleet-wide `ENABLED` remains unauthorized. Broader automatic maintenance supply requires additional repository breadth and accepted evidence under the same Human/security/runtime-authority boundaries.
- A participating repository may be returned to `DISABLED` without deleting its catalog or durable run history; normal work/recovery bootstrap must remain unaffected.

Canonical detailed evidence remains on `devflow#363`; this operations document records the accepted operational state and decision rather than duplicating run-by-run history.
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
