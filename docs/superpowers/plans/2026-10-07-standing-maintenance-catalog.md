# Standing Maintenance Catalog + Idle Fallback Audit Supply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a predefined, deterministic, resumable maintenance/audit fallback lane that can supply useful work after ordinary runnable/recovery work is exhausted without manufacturing synthetic tasks or creating a second claim authority.

**Architecture:** devflow remains the policy/aggregation authority and execution-coordinator remains the sole runtime claim authority. A strict machine-readable Common Baseline plus repository-local catalog resolves to audit slots; a pure selector scores eligible slots from durable Ledger/history evidence; a standing repository Ledger Issue becomes the exact existing owner for lightweight maintenance publication; existing Control candidate projection and execution-coordinator claim/acknowledge are reused unchanged. Broad chat pickup invokes this maintenance cycle only after the accepted bootstrap returns no ordinary work, and 3C is preserved by re-running discovery with a new execution-attempt identity after publication.

**Tech Stack:** Python 3 standard library, `unittest`, existing GitHub REST transport helpers, GitHub Actions, existing devflow Repository Control candidate/portfolio projections. No new runtime database and no new third-party Python dependency in v1.

**Spec:** `docs/superpowers/specs/2026-10-07-standing-maintenance-catalog-design.md`

## Global Constraints

- Common baseline canon lives at `docs/spec/maintenance/common-baseline.v1.yaml`.
- Repository-specific catalog canon lives at `.devflow/maintenance.yaml`.
- v1 YAML files use the JSON-compatible YAML 1.2 subset and are parsed with Python `json`; this keeps the format valid YAML while preserving closed-schema parsing without adding a dependency.
- Catalog schema identifier is `maintenance-catalog.v1`; unknown major versions fail closed as `NEEDS_EVIDENCE / SCHEMA_UNSUPPORTED`.
- Audit depths remain exactly `CONTROL`, `STANDARD`, `DEEP`.
- Risk values remain exactly `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- Slot lifecycle values are exactly `ACTIVE`, `MERGED`, `SUPERSEDED`, `RETIRED`.
- Finding classes are exactly `DEFECT`, `RISK`, `DRIFT`, `COVERAGE_GAP`, `IMPROVEMENT`.
- Finding confidence values are exactly `CONFIRMED`, `PROBABLE`, `UNVERIFIED`, `FALSE_POSITIVE`.
- Rollout values are exactly `DISABLED`, `PILOT`, `ENABLED`.
- execution-coordinator remains the only runtime claim/lease/generation/fencing authority.
- No maintenance work starts before serialized claim + acknowledge.
- Same publication attempt may not consume the candidate it published; the worker must begin a new discovery attempt to satisfy 3C.
- Existing Stage-2 scheduled audit/triage stays read-only; no scheduled write-capable publisher is introduced in this plan.
- Release/deploy/publication, credential/session/permission/IAM mutation, destructive/shared-history action, and other protected security changes remain Human-gated.
- No new Issue per lightweight audit; standing Ledger + comments are the default.
- A run promotes to a bounded Issue before DEEP work, mutation, durable Finding ownership, blocker/Human Gate, multi-step handoff, or independent Acceptance.
- Catalog definition, durable history, and derived projection remain separate authorities.
- Initial automatic rollout remains PILOT; devflow is first, execution-coordinator second.

## Review Focus

- A malformed or unknown-version repository catalog must fail closed without falling back to guessed/default maintenance work; Task 1 adds explicit malformed/unknown-version tests.
- Same repository/scope/lens/depth plus equivalent fingerprint inside cooldown must not become eligible solely because the worker is idle; Task 2 adds exact duplicate-suppression tests.
- Partial publication where Ledger activation succeeds but Control publication fails must remain recoverable and must not produce duplicate work on retry; Task 5 adds failure-fencing/reconciliation tests.
- A worker that publishes maintenance supply must not consume it in the same execution attempt; Task 5/7 add 3C tests covering publish then fresh-attempt pickup.
- Repository-scoped broad work must not silently widen to the whole fleet when the target repository has no useful maintenance; Task 7 adds explicit scope-preservation tests.

---

### Task 1: Canonical Common Baseline and repository catalog loader

**Files:**
- Create: `docs/spec/maintenance/common-baseline.v1.yaml`
- Create: `docs/spec/schemas/maintenance-catalog.v1.schema.json`
- Create: `tools/maintenance_catalog.py`
- Create: `tests/test_maintenance_catalog.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Consumes: filesystem paths and JSON-compatible YAML text.
- Produces:
  - `load_common_baseline(path: Path | str) -> CommonBaseline`
  - `load_repository_catalog(path: Path | str, baseline: CommonBaseline) -> RepositoryCatalog`
  - `resolve_catalog(baseline: CommonBaseline, catalog: RepositoryCatalog) -> tuple[ResolvedSlot, ...]`
  - `canonical_catalog_digest(baseline: CommonBaseline, catalog: RepositoryCatalog) -> str`
  - frozen dataclasses `CommonBaseline`, `RepositoryCatalog`, `ResolvedSlot`, `Scope`
  - exception `MaintenanceCatalogError`

- [ ] **Step 1: Write failing schema/loader tests in `tests/test_maintenance_catalog.py`**

Tests must assert:
- Common Baseline loads the 12 accepted common lenses.
- Repository catalog references exactly one baseline schema/version.
- unknown `schema_version` raises `MaintenanceCatalogError`;
- unknown top-level field raises;
- duplicate `slot_id` raises;
- duplicate active `coverage_key` + identical scope/lens is rejected unless one record is lifecycle `MERGED`/`SUPERSEDED`;
- `RETIRED` does not resolve as runnable;
- repository override cannot remove all Security coverage;
- unknown Risk/Depth/lifecycle/scope kind raises;
- same logical content yields the same `sha256:` catalog digest independent of object key order.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

    python -W error -m unittest tests.test_maintenance_catalog -v

Expected: FAIL because `tools.maintenance_catalog` and baseline/schema do not exist.

- [ ] **Step 3: Implement the strict loader/model in `tools/maintenance_catalog.py`**

Implementation constraints:
- read UTF-8 text then `json.loads` it; JSON is the accepted v1 subset of YAML 1.2;
- reject duplicate keys using `object_pairs_hook`;
- reject unknown fields explicitly rather than silently ignoring them;
- normalize/sort set-like arrays before digesting;
- never read run history from the catalog;
- do not import GitHub or network code.

- [ ] **Step 4: Add the canonical Common Baseline**

Encode exact initial defaults from the approved spec:
- lenses: Correctness, Edge Cases, Reliability / Recovery, Security, State Integrity / Concurrency, Spec / Implementation Drift, Test Quality, Resource Management, Dependency / External Assumptions, Error Handling, Observability, Lifecycle / Issue / PR / Session consistency;
- cadence days:
  - LOW: general 90, security 90, deep 180;
  - MEDIUM: general 60, security 45, deep 120;
  - HIGH: general 30, security 21, deep 60;
  - CRITICAL: general 14, security 7, deep 30;
- cooldown hours:
  - LOW 168;
  - MEDIUM 72;
  - HIGH 24;
  - CRITICAL 6;
- external freshness:
  - FAST 1 day;
  - NORMAL 7 days;
  - SLOW 30 days;
- selector weights from the design spec.

- [ ] **Step 5: Run targeted tests and full regression**

Run:

    python -W error -m unittest tests.test_maintenance_catalog -v
    python -W error -m unittest discover -v
    python -m py_compile tools/maintenance_catalog.py

Expected: PASS.

- [ ] **Step 6: Extend Required PR gate paths/compile check**

Update `.github/workflows/project-sync-tests.yml` so changes under:
- `docs/spec/maintenance/**`
- `docs/spec/schemas/maintenance-catalog.v1.schema.json`
- `.devflow/maintenance.yaml`

trigger the Required PR gate, and compile `tools/maintenance_catalog.py`.

- [ ] **Step 7: Commit**

    git add docs/spec/maintenance/common-baseline.v1.yaml docs/spec/schemas/maintenance-catalog.v1.schema.json tools/maintenance_catalog.py tests/test_maintenance_catalog.py .github/workflows/project-sync-tests.yml
    git commit -m "feat: add maintenance catalog contract (#363)"

---

### Task 2: Pure deterministic maintenance selector

**Files:**
- Create: `tools/maintenance_selector.py`
- Create: `tests/test_maintenance_selector.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Consumes:
  - `tuple[ResolvedSlot, ...]` from Task 1;
  - `tuple[RunEvidence, ...]`;
  - `SelectionContext`.
- Produces:
  - frozen dataclasses `AuditFingerprint`, `RunEvidence`, `SelectionContext`, `ScoreBreakdown`, `SelectionResult`;
  - `score_slot(slot: ResolvedSlot, context: SelectionContext, history: tuple[RunEvidence, ...]) -> ScoreBreakdown | None`;
  - `select_maintenance(slots: tuple[ResolvedSlot, ...], context: SelectionContext, history: tuple[RunEvidence, ...]) -> SelectionResult | None`;
  - `canonical_fingerprint(value: Mapping[str, object]) -> str`.

- [ ] **Step 1: Write RED selector tests**

Pin:
- NEVER_RUN = +40;
- overdue = +20;
- >2x overdue = additional +10;
- unexecuted Lens +15;
- justified deeper coverage +15;
- relevant source/config change +25;
- HIGH +15 / CRITICAL +25;
- finding re-audit +20;
- security-sensitive change/event +30;
- stale external/dependency evidence +20;
- immediate same-repository penalty -10;
- materially similar recent coverage -20;
- exact same repo/scope/lens/depth/equivalent fingerprint without bypass = ineligible;
- cooldown bypass for source change, security event, finding verification, incomplete evidence, recovery, explicit user request;
- equal score tie-break exactly follows Risk -> oldest equivalent run -> never-run -> repository spread -> lexical repo+slot;
- input ordering does not change result;
- repository-scoped context never returns another repository;
- portfolio scope can select another repository;
- all candidates filtered returns `None` rather than fabricating work.

- [ ] **Step 2: Verify RED**

    python -W error -m unittest tests.test_maintenance_selector -v

Expected: FAIL because selector does not exist.

- [ ] **Step 3: Implement pure scoring/selection**

No GitHub/network/time lookup inside the module. Current time and prior repository selection are explicit inputs so tests are deterministic.

- [ ] **Step 4: Verify GREEN and regressions**

    python -W error -m unittest tests.test_maintenance_selector -v
    python -W error -m unittest discover -v
    python -m py_compile tools/maintenance_selector.py

Expected: PASS.

- [ ] **Step 5: Add compile path and commit**

    git add tools/maintenance_selector.py tests/test_maintenance_selector.py .github/workflows/project-sync-tests.yml
    git commit -m "feat: add deterministic maintenance selector (#363)"

---

### Task 3: Standing Maintenance Ledger and run-record contract

**Files:**
- Create: `tools/maintenance_ledger.py`
- Create: `tests/test_maintenance_ledger.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Produces:
  - constants `ACTIVE_RUN_BEGIN`, `ACTIVE_RUN_END`, `RUN_COMMENT_SENTINEL`;
  - frozen dataclasses `ActiveRun`, `RunRecord`;
  - `extract_active_run(body: str, repository: str) -> ActiveRun | None`;
  - `replace_active_run(body: str, active: ActiveRun | None) -> tuple[str, bool]`;
  - `render_run_comment(record: RunRecord) -> str`;
  - `parse_run_comment(body: str) -> RunRecord | None`;
  - `next_generation(history: tuple[RunRecord, ...], repository: str, slot_id: str) -> int`;
  - `ledger_work_status(body: str) -> str | None`.

**Canonical owner shape:**
- one open Issue titled exactly `[MAINTENANCE] Audit Ledger` in each participating repository;
- Ledger body carries ordinary Issue sections plus at most one machine active-run block;
- run history lives in trusted comments;
- active-run block includes `run_id`, `slot_id`, `generation`, `catalog_digest`, `fingerprint`, `depth`, `coverage_key`, `selected_at`, `publisher_attempt_id`, `score_breakdown`.

- [ ] **Step 1: Write RED Ledger parser/render tests**

Assert:
- zero/one active-run block accepted;
- duplicate/reversed/malformed marker fails closed;
- repository mismatch fails;
- unknown field fails;
- rendering identical active run is no-op;
- clearing active run is deterministic;
- run comment round-trips;
- unrecognized comment returns `None`;
- generation increments only for the same repository+slot;
- active run requires Work Status `READY_FOR_IMPLEMENTATION`;
- no active run requires non-runnable status such as `AUDITED`.

- [ ] **Step 2: Verify RED**

    python -W error -m unittest tests.test_maintenance_ledger -v

- [ ] **Step 3: Implement pure Ledger contract**

Use canonical JSON inside markers. Do not include credentials, claim IDs, or provider identity in the durable run payload.

- [ ] **Step 4: Verify GREEN and full regression**

    python -W error -m unittest tests.test_maintenance_ledger -v
    python -W error -m unittest discover -v
    python -m py_compile tools/maintenance_ledger.py

- [ ] **Step 5: Commit**

    git add tools/maintenance_ledger.py tests/test_maintenance_ledger.py .github/workflows/project-sync-tests.yml
    git commit -m "feat: define maintenance ledger contract (#363)"

---

### Task 4: GitHub collector and read-only catalog selection CLI

**Files:**
- Modify: `tools/maintenance_github.py`
- Modify: `scripts/maintenance_audit.py`
- Create: `tests/test_maintenance_catalog_github.py`
- Modify: `tests/test_maintenance_github.py`
- Modify: `tests/test_maintenance_audit_workflow.py`
- Modify: `.github/workflows/maintenance-audit.yml`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Add `GitHubReadTransport.get_repository_file(repository: str, path: str, ref: str | None = None) -> dict[str, object]`.
- Add `collect_maintenance_catalog(repository: str, control_ref: str, transport: GitHubReadTransport) -> CatalogObservation`.
- Add `collect_maintenance_history(repository: str, ledger_issue: int, transport: GitHubReadTransport) -> tuple[RunRecord, ...]`.
- Add CLI subcommand:

    python scripts/maintenance_audit.py select-maintenance ...

- Output schema: `maintenance-selection.v1`.
- Selection output includes repository, slot_id, run generation, depth, catalog_digest, fingerprint, score breakdown, Ledger ref, and `eligible: true/false`.

- [ ] **Step 1: Write failing GitHub-collection tests**

Cover:
- exact default-branch catalog read;
- missing catalog -> `NO_CATALOG`, not guessed work;
- malformed catalog -> `NEEDS_EVIDENCE`;
- missing/multiple Ledger Issue -> typed evidence failure during PILOT, never auto-create in read-only mode;
- only OWNER/MEMBER/COLLABORATOR Ledger comments count as run history;
- external source observation may contribute fingerprint/freshness without changing code SHA.

- [ ] **Step 2: Write failing CLI/workflow tests**

Add manual/read-only workflow mode `maintenance-select`.
It may read cross-repository state and upload a selection artifact but must have no write permission and must not publish supply.

- [ ] **Step 3: Verify RED**

    python -W error -m unittest tests.test_maintenance_catalog_github tests.test_maintenance_github tests.test_maintenance_audit_workflow -v

- [ ] **Step 4: Implement collector and CLI**

Reuse existing exact-source/fail-closed GitHub transport patterns. Do not make search/index state authoritative.

- [ ] **Step 5: Verify GREEN/regression**

    python -W error -m unittest tests.test_maintenance_catalog_github tests.test_maintenance_github tests.test_maintenance_audit_workflow -v
    python -W error -m unittest discover -v
    python -m py_compile scripts/maintenance_audit.py tools/maintenance_github.py tools/maintenance_catalog.py tools/maintenance_selector.py tools/maintenance_ledger.py

- [ ] **Step 6: Commit**

    git add tools/maintenance_github.py scripts/maintenance_audit.py tests/test_maintenance_catalog_github.py tests/test_maintenance_github.py tests/test_maintenance_audit_workflow.py .github/workflows/maintenance-audit.yml .github/workflows/project-sync-tests.yml
    git commit -m "feat: select catalog maintenance read-only (#363)"

---

### Task 5: Catalog-backed supply publication through the standing Ledger owner

**Files:**
- Modify: `tools/maintenance_supply.py`
- Modify: `scripts/maintenance_audit.py`
- Modify: `tests/test_maintenance_supply.py`
- Modify: `tests/test_maintenance_github.py`
- Modify: `tests/test_maintenance_audit_workflow.py`
- Modify: `.github/workflows/maintenance-audit.yml`

**Interfaces:**
- Add:
  - `build_catalog_maintenance_candidate(selection: SelectionResult, ledger_snapshot: Mapping[str, object], control_snapshot: Mapping[str, object]) -> dict[str, object] | None`;
  - CLI `publish-maintenance`;
  - CLI `withdraw-maintenance`.
- Reuse existing `DEVFLOW_EXECUTION_CANDIDATES_V1` and `DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1`.
- Candidate `task` is the exact standing Ledger Issue ref.
- `work_class` is `audit`.
- Slot specificity is bound in the Ledger active-run block and therefore in the exact Ledger body digest used by the candidate.
- Conflict keys include at least the repository and bounded slot/scope key.
- One lightweight active maintenance claim per repository is sufficient for v1; disjoint intra-repository parallel audit remains deferred.

- [ ] **Step 1: Write RED publication tests**

Assert:
- no Ledger Issue -> no publication;
- Ledger not trusted/open -> no publication;
- Ledger body status not `READY_FOR_IMPLEMENTATION` -> no publication;
- active-run slot/catalog digest/fingerprint mismatch -> no publication;
- Control not trusted/ACTIVE -> no publication;
- Human/reviewer/external/security gate suppresses publication;
- candidate task/entry_ref bind exactly to Ledger Issue;
- candidate body digest binds the exact active-run body;
- existing candidate fingerprint contract remains byte-compatible with execution-coordinator;
- publisher attempt identity is preserved;
- same logical active run is idempotent;
- new generation supersedes old Ledger candidate;
- withdrawal removes only that Ledger task candidate.

- [ ] **Step 2: Add 3C tests**

A candidate with `publisher_execution_attempt_id == current attempt` must remain ineligible to the same bootstrap attempt; a new attempt ID may consume it after fresh evidence.

- [ ] **Step 3: Add partial-publication failure tests**

Simulate:
1. exact Ledger activation succeeds;
2. Control publication CAS fails.

Expected:
- Ledger active run remains durable/recoverable;
- retry re-reads Ledger exact body and republishes the same logical run instead of creating a new generation;
- no blind retry against stale Control body;
- no duplicate candidate.

Also simulate Control publication success followed by Ledger readback mismatch; expected fail closed and leave a durable reconciliation-required result.

- [ ] **Step 4: Verify RED**

    python -W error -m unittest tests.test_maintenance_supply tests.test_maintenance_github tests.test_chat_worker_bootstrap -v

- [ ] **Step 5: Implement publication/withdrawal**

Write order:
1. fresh exact Ledger read;
2. expected-body fenced Ledger activation;
3. exact readback;
4. fresh exact Control read;
5. expected-body fenced candidate publication;
6. exact readback;
7. output publication result.

No scheduled write path is enabled.

- [ ] **Step 6: Add manual workflow modes**

Add explicit `workflow_dispatch` modes:
- `maintenance-publish`
- `maintenance-withdraw`

They consume only preconfigured write authority. Do not create/rotate/broaden credentials.

- [ ] **Step 7: Verify GREEN/regression**

    python -W error -m unittest tests.test_maintenance_supply tests.test_maintenance_github tests.test_chat_worker_bootstrap tests.test_maintenance_audit_workflow -v
    python -W error -m unittest discover -v

- [ ] **Step 8: Commit**

    git add tools/maintenance_supply.py scripts/maintenance_audit.py tests/test_maintenance_supply.py tests/test_maintenance_github.py tests/test_chat_worker_bootstrap.py tests/test_maintenance_audit_workflow.py .github/workflows/maintenance-audit.yml
    git commit -m "feat: publish catalog maintenance supply (#363)"

---

### Task 6: Maintenance completion, durable run history, and resumable active-run recovery

**Files:**
- Modify: `tools/maintenance_ledger.py`
- Modify: `tools/maintenance_github.py`
- Modify: `scripts/maintenance_audit.py`
- Create: `tests/test_maintenance_run_lifecycle.py`
- Modify: `tests/test_maintenance_supply.py`

**Interfaces:**
- Add CLI `complete-maintenance`.
- Add `complete_run(active: ActiveRun, result: Mapping[str, object]) -> RunRecord`.
- Result status values:
  - `CLEAN`
  - `FINDINGS`
  - `RECONCILED`
  - `BLOCKED`
  - `SUPERSEDED`
  - `NEEDS_REAUDIT`.
- Add `assess_active_run_for_resume(...)-> ResumeAssessment` with `RESUME`, `SUPERSEDE`, `NEEDS_EVIDENCE`.

- [ ] **Step 1: Write RED lifecycle tests**

Cover:
- successful lightweight completion appends one trusted Run comment, clears active-run block, moves Ledger out of `READY_FOR_IMPLEMENTATION`, withdraws candidate, and preserves history;
- completion is idempotent for same Run ID;
- finding result may record references but does not create a new Issue automatically;
- DEEP/mutation/blocker condition returns `PROMOTE_REQUIRED` before substantive continuation;
- interrupted active run is not replaced by another slot;
- long-interrupted run with unchanged volatile evidence resumes same run;
- materially changed fingerprint yields `NEEDS_REAUDIT`/new generation, not silent resume;
- accepted historical checks are not automatically replayed.

- [ ] **Step 2: Verify RED**

    python -W error -m unittest tests.test_maintenance_run_lifecycle -v

- [ ] **Step 3: Implement lifecycle helpers/CLI**

Completion write order:
1. fresh Ledger/control/candidate read;
2. append run-record comment;
3. clear active-run body under expected digest;
4. withdraw Control candidate under fresh expected digest;
5. exact readback.

If candidate withdrawal fails after durable completion, return reconciliation-required state; do not erase the completed comment.

- [ ] **Step 4: Verify GREEN/regression**

    python -W error -m unittest tests.test_maintenance_run_lifecycle tests.test_maintenance_supply -v
    python -W error -m unittest discover -v

- [ ] **Step 5: Commit**

    git add tools/maintenance_ledger.py tools/maintenance_github.py scripts/maintenance_audit.py tests/test_maintenance_run_lifecycle.py tests/test_maintenance_supply.py
    git commit -m "feat: complete and resume maintenance runs (#363)"

---

### Task 7: Broad chat-worker fallback integration without changing bootstrap-v1 semantics

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/operations/CHAT_WORKER_INTEGRATION.md`
- Modify: `docs/operations/MAINTENANCE_AUDIT.md`
- Modify: `docs/spec/CHAT_WORKER_BOOTSTRAP.md`
- Modify: `.devflow/WORKFLOW.yaml`
- Modify: `tests/test_workflow_contract.py`
- Create: `tests/test_maintenance_chat_fallback_contract.py`

**Interfaces:**
- Existing `chat_worker_bootstrap.classify()` remains unchanged.
- The fallback is an outer operational loop:
  1. run normal bootstrap;
  2. only on ordinary `NO_ELIGIBLE_WORK`, inspect maintenance rollout/catalog;
  3. select legitimate maintenance;
  4. if publication is needed, publish under attempt A and stop attempt A;
  5. start attempt B with a new `execution_attempt_id`;
  6. normal bootstrap sees the published candidate;
  7. serialized claim + acknowledge;
  8. execute the exact Ledger active run.
- Repository-scoped broad instruction never broadens to portfolio scope automatically.

- [ ] **Step 1: Write RED contract tests**

Assert docs/workflow contract contain:
- `standing_maintenance` policy section;
- rollout values DISABLED/PILOT/ENABLED;
- generic broad pickup fallback order;
- repository-scoped no-widen rule;
- 3C requires new attempt after publication;
- true NO_ELIGIBLE_WORK only after maintenance exhaustion;
- current bootstrap-v1 result vocabulary remains unchanged.

- [ ] **Step 2: Verify RED**

    python -W error -m unittest tests.test_maintenance_chat_fallback_contract tests.test_workflow_contract tests.test_chat_worker_bootstrap -v

- [ ] **Step 3: Update canonical docs/workflow**

Do not add a new bootstrap disposition or reason code. Keep the fallback outside the v1 classifier.

- [ ] **Step 4: Verify GREEN/regression**

    python -W error -m unittest tests.test_maintenance_chat_fallback_contract tests.test_workflow_contract tests.test_chat_worker_bootstrap -v
    python -W error -m unittest discover -v

- [ ] **Step 5: Commit**

    git add AGENTS.md docs/operations/CHAT_WORKER_INTEGRATION.md docs/operations/MAINTENANCE_AUDIT.md docs/spec/CHAT_WORKER_BOOTSTRAP.md .devflow/WORKFLOW.yaml tests/test_workflow_contract.py tests/test_maintenance_chat_fallback_contract.py
    git commit -m "docs: integrate maintenance fallback into broad pickup (#363)"

---

### Task 8: devflow PILOT catalog and standing Ledger onboarding

**Files:**
- Create: `.devflow/maintenance.yaml`
- Modify: `tests/test_maintenance_catalog.py`
- GitHub Issue: create/reuse one `[MAINTENANCE] Audit Ledger` in `kinoko34077/devflow`.

**Interfaces:**
- Repository catalog references the shared baseline and sets rollout `PILOT`.
- Initial repository Risk Profile: `HIGH` because devflow controls cross-repository workflow/supply/security gates.
- Initial repository-specific slots:
  - `control.consistency`
  - `session.staleness`
  - `supply.claim-consistency`
  - `spec.current-state-drift`
  - `security.workflow-permissions`
  - `dependency.actions-pins`.

- [ ] **Step 1: Add RED test requiring devflow pilot catalog to validate**

    python -W error -m unittest tests.test_maintenance_catalog -v

Expected: FAIL until catalog exists and validates.

- [ ] **Step 2: Create the devflow catalog**

Use JSON-compatible YAML syntax and only repo-specific values/overrides; do not copy the Common Baseline.

- [ ] **Step 3: Create/reuse the standing Ledger Issue**

The Ledger body is a durable owner template with no active run and Work Status `AUDITED`. Do not create multiple Ledger Issues.

- [ ] **Step 4: Verify catalog and full suite**

    python -W error -m unittest tests.test_maintenance_catalog -v
    python -W error -m unittest discover -v

- [ ] **Step 5: Commit repository catalog**

    git add .devflow/maintenance.yaml tests/test_maintenance_catalog.py
    git commit -m "chore: onboard devflow maintenance pilot (#363)"

---

## Execution replan — pre-pilot accepted-main gate

**Recorded:** 2026-10-07  
**Disposition:** `CHANGE_PATH`

The implemented maintenance collector intentionally resolves both the shared Common Baseline and repository Catalog from each repository's **default-branch head**. Therefore the live Task 9 selector cannot consume the Task 8 catalog while PR #366 remains unmerged without adding a special branch-ref bypass. Adding such a bypass only for the pilot would weaken the exact accepted-source contract and create a path that normal operation does not use.

Accordingly, move the implementation acceptance boundary before live pilot execution:

1. finish Tasks 1–8 on PR #366;
2. require exact-head Required PR gate;
3. require Formal Review and a different reviewer because this change materially changes devflow source-of-truth / supply authority semantics;
4. merge PR #366 under expected-head fencing;
5. run post-main Required verification;
6. only then execute Task 9 against the real default-branch Catalog;
7. continue Task 10 and Task 11 under PILOT.

This changes execution order only. It does **not** waive any Task 9–11 acceptance criterion, does not broaden rollout beyond PILOT, and does not treat merge as pilot acceptance.

### Pre-pilot acceptance gate

- [ ] PR #366 exact head Required PR gate GREEN
- [ ] PR body declares `Formal review required: yes`
- [ ] PR body declares `Different reviewer required: yes`
- [ ] qualifying different-reviewer Review Provenance v2 targets the exact current head
- [ ] review-readiness GREEN
- [ ] expected-head guarded merge
- [ ] post-main Required verification GREEN
- [ ] #363 checkpoint advances to Task 9 on accepted main

---

### Task 9: End-to-end devflow pilot through selection -> publication -> fresh-attempt claim

**Files:**
- No new product files expected; findings may create bounded repair Issues.
- Durable evidence: devflow#363 plus the devflow `[MAINTENANCE] Audit Ledger`.
- Runtime evidence: execution-coordinator claim state.

**Interfaces:**
- Uses Tasks 1-8 exactly as published.

- [ ] **Step 1: Run read-only selection**

Expected:
- one deterministic selected slot;
- score breakdown recorded;
- no write/claim.

- [ ] **Step 2: Publish selected run under execution attempt A**

Expected:
- exact Ledger active-run block;
- exact Control candidate;
- 3C publisher attempt bound;
- no runtime claim created.

- [ ] **Step 3: Prove same-attempt exclusion**

Normal bootstrap with attempt A must omit the candidate as `PUBLISHED_BY_THIS_ATTEMPT`.

- [ ] **Step 4: Start fresh attempt B and claim**

Expected:
- normal bootstrap selects the Ledger candidate;
- execution-coordinator serialized claim succeeds;
- acknowledge succeeds;
- worker reads exact active-run block before work.

- [ ] **Step 5: Complete one lightweight Run**

Expected:
- trusted run comment written;
- active run cleared;
- candidate withdrawn;
- runtime claim released;
- next selection rotates away from materially identical coverage.

- [ ] **Step 6: Exercise promotion path**

Select/construct a safe bounded case that requires DEEP or mutation. Verify the Ledger points to one bounded Issue and detailed progress moves there instead of duplicating authority.

- [ ] **Step 7: Exercise interruption/resume**

Interrupt one active run after a checkpoint, then resume from a successor worker/attempt. Verify completed evidence is not replayed without a drift trigger.

- [ ] **Step 8: Exercise true NO_ELIGIBLE_WORK**

Use controlled fresh evidence so every devflow pilot slot is ineligible and verify the final outer loop returns NO_ELIGIBLE_WORK rather than inventing work.

- [ ] **Step 9: Record pilot evidence and reconcile #363**

Do not broaden rollout yet.

---

### Task 10: execution-coordinator PILOT onboarding

**Files in `kinoko34077/execution-coordinator`:**
- Create: `.devflow/maintenance.yaml`
- GitHub Issue: create/reuse `[MAINTENANCE] Audit Ledger`.
- No execution-coordinator runtime code change is expected.

**Interfaces:**
- Reuses devflow Common Baseline and existing claim runtime.
- Initial Risk Profile: `CRITICAL` for claim/provider/security-sensitive scopes, with component overrides where lower risk is justified.
- Initial repository-specific slots should cover:
  - claim/lease/generation/fencing integrity;
  - provider failure/timeout/ambiguous outcome;
  - resource cleanup;
  - reviewer provenance;
  - security credential transport boundary;
  - Current State/runtime claim consistency.

- [ ] **Step 1: Open a repository-local onboarding Issue**

Use execution-coordinator Control and local canon; do not implement from devflow#363 alone.

- [ ] **Step 2: Add catalog + Ledger under dedicated branch/PR**

Validate against devflow baseline/schema.

- [ ] **Step 3: Run exact-head tests/review required by execution-coordinator policy**

No provider E2E, OAuth/login, credential/session/permission mutation, release/deploy/publication.

- [ ] **Step 4: Run bounded maintenance selection/claim/completion pilot**

Prove the same devflow path works cross-repository without adding a second runtime mechanism.

- [ ] **Step 5: Record evidence back to devflow#363**

Do not set fleet rollout ENABLED yet.

---

### Task 11: Pilot acceptance, rollback proof, and rollout decision packet

**Files:**
- Modify: `docs/operations/MAINTENANCE_AUDIT.md`
- Modify: `docs/superpowers/specs/2026-10-07-standing-maintenance-catalog-design.md` only if pilot establishes a necessary accepted specification correction.
- Durable owner: devflow#363.

**Interfaces:**
- No new runtime interface; this task decides whether the accepted implementation satisfies pilot criteria.

- [ ] **Step 1: Build the pilot evidence matrix**

Must show evidence for:
- deterministic selection;
- explainable score;
- no duplicate claim;
- Ledger-only completion;
- Ledger -> bounded Issue promotion;
- interrupted resume;
- Finding -> normal work re-ranking;
- alternate Lens rotation;
- justified DEEP;
- same-audit suppression;
- external freshness with unchanged code SHA;
- repository bias penalty;
- portfolio selection;
- true NO_ELIGIBLE_WORK;
- no duplicate canon;
- no weakened Human/security gate.

- [ ] **Step 2: Exercise rollback gate**

Set pilot repository rollout to DISABLED, withdraw maintenance supply, preserve catalog/history, and verify normal work/recovery bootstrap remains unchanged.

- [ ] **Step 3: Re-enable PILOT and rerun one read-only selection**

Verify reversible rollout state.

- [ ] **Step 4: Run full regression and Required gate**

    python -W error -m unittest discover -v

Expected: PASS; Required PR gate GREEN.

- [ ] **Step 5: Obtain required Formal Review / different reviewer according to live devflow policy**

Do not treat user design approval as a substitute for required code review evidence.

- [ ] **Step 6: Reconcile durable state**

Update:
- devflow#363;
- affected Repository Controls;
- Ledger/current run state;
- Current State/spec only where accepted state changed;
- #209 only if its supply contract is actually accepted/changed.

- [ ] **Step 7: Produce rollout decision packet**

Possible outcomes:
- keep PILOT;
- expand PILOT to more managed repositories;
- enable broader automatic maintenance supply.

Do not promote to fleet-wide ENABLED merely because the code is merged.
