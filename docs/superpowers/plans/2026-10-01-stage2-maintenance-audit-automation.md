# Stage 2 Maintenance Audit Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the cross-repository consistency knowledge exercised through `devflow#249` into a deterministic GitHub Actions maintenance auditor that detects and triages bounded drift automatically, preserves existing devflow authority, and permits only separately gated low-risk sync-check repairs.

**Architecture:** Extend the accepted Development Reconciliation contract rather than creating a second state machine. A pure Python audit engine classifies immutable exact-source observations; a separate GitHub adapter collects live evidence; deterministic triage maps findings to existing reconciliation dispositions and tracking/supply decisions; a narrowly allowlisted sync-check executor re-reads exact identity immediately before any mutation. GitHub Actions starts read-only/manual, then gains scheduled read-only audit/triage only after the real portfolio pilot passes. Runtime claim/lease authority remains in execution-coordinator and runnable supply remains governed by `devflow#209` and accepted Repository Control candidate projections.

**Tech Stack:** Python 3 standard library (`dataclasses`, `hashlib`, `json`, `re`, `urllib.request`), `unittest`, GitHub REST API, GitHub Actions, existing devflow Issue/Control/candidate contracts.

**Spec:** `docs/spec/DEVELOPMENT_RECONCILIATION.md` Section 10 as introduced by `devflow#264` / PR #265, plus `devflow#215/#232`; execution of Task 1 is blocked until S2.1 is accepted on `main` and S2.2 is explicitly released.

## Global Constraints

- S2.2 implementation MUST NOT begin until `devflow#264` / PR #265 is merged, post-main verified, directly affected surfaces are reconciled, and `devflow#232` releases S2.2.
- Reuse canonical Development Reconciliation dispositions: `AUTO_ADVANCE`, `NEEDS_REVIEWER`, `NEEDS_RECOVERY`, `NEEDS_HUMAN`, `WAIT_EXTERNAL`, `NEEDS_EVIDENCE`, `NO_ACTION`; finding names are diagnostic metadata only.
- Exact authoritative readback wins over GitHub search/index output; search may discover a candidate but never establish closure, readiness or mutation authority.
- Required-source failure, contradiction, identity mismatch or insufficient freshness fails closed; it is never silently classified as clean.
- Owning Issues/Work Orders remain durable task truth; Repository Controls remain cross-repository summaries/projections; GitHub Project and chat are never task authority.
- No second queue/database, provider scheduler, semantic/LLM scheduler, claim/lease system or permanent worker-per-class pool.
- No runnable demand from Issue age, labels, branch existence, search similarity, provider/model identity, idle workers, clean scans or a desire to keep workers busy.
- Stage-2 scheduled runs are read-only audit/triage in the initial accepted version. Sync-check mutation is never enabled merely because a schedule exists.
- The initial S2.4 mutation allowlist is one concrete machine-readable projection repair: withdraw a stale `DEVFLOW_EXECUTION_CANDIDATES_V1` entry after its exact owning task is proven terminal/non-runnable and no stronger gate/producer conflict exists. Human-readable Control prose, README and Current State semantic rewriting stay outside automatic mutation.
- Every mutation executor re-reads the exact Control body and owning task identity immediately before write, compares expected freshness/digest, preserves all unrelated body bytes, performs a post-write readback, and is idempotent on the second run.
- `devflow#249` is regression-fixture provenance/backstop only; it is not runtime task truth and is not polled as an authority source by the auditor.
- Cross-repository GitHub credential creation/rotation/storage/permission changes are Human/security-gated. The implementation may consume an already-approved read credential but MUST NOT create or alter one.
- No release/deploy/publication external effect, credential/session/permission/IAM change, destructive/shared-history operation, Human/device/security gate bypass, or RDC.

## Review Focus

- Search/index says an Issue is open while exact Issue read says closed: exact read must govern and the search disagreement must never keep stale work runnable.
- One required repository/source is unavailable while all others are clean: portfolio result must preserve that failure as `NEEDS_EVIDENCE`, not report portfolio clean.
- A live trusted producer owns the same bounded surface: audit may report `ACTIVE_PRODUCER_YIELD`, but triage must not create/relax supply or mutate the surface.
- A semantic-prose drift suspicion has no machine-provable desired text: result must remain `NEEDS_EVIDENCE`/triage-only and never enter sync-check mutation.
- A sync-check plan is prepared, then the Control body or owner freshness changes before execution: executor must refuse mutation and return to observation rather than applying the stale plan.

---

## Preflight Gate: accept S2.1 before implementation

This is an execution precondition, not a code task.

- [ ] Re-read `devflow#264`, PR #265, `devflow#232`, `devflow#215`, Control #16 and accepted `main`.
- [ ] Require a qualifying different-system/model current-head Formal Review on PR #265, review-readiness GREEN, expected-head merge, post-main verify, and affected-surface reconciliation.
- [ ] Require `devflow#232` to name S2.2 as the first unfinished released unit.
- [ ] If PR #265 changes the Section-10 contract from the version this plan was written against, update this plan before Task 1 rather than silently implementing the old draft.

### Task 1: S2.2 pure read-only audit engine and #249 regression fixtures

**Files:**
- Create: `tools/maintenance_audit.py`
- Create: `tests/test_maintenance_audit.py`
- Create: `tests/fixtures/maintenance_audit/clean.json`
- Create: `tests/fixtures/maintenance_audit/stale-control-owner-terminal.json`
- Create: `tests/fixtures/maintenance_audit/active-producer-yield.json`
- Create: `tests/fixtures/maintenance_audit/reviewer-gate.json`
- Create: `tests/fixtures/maintenance_audit/human-gate.json`
- Create: `tests/fixtures/maintenance_audit/source-unavailable.json`
- Create: `tests/fixtures/maintenance_audit/semantic-projection-suspected.json`
- Create: `tests/fixtures/maintenance_audit/search-stale-exact-terminal.json`
- Modify: `tools/development_reconciler.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Modify `tools.development_reconciler` to export `DISPOSITIONS: tuple[str, ...]` containing exactly the accepted Section-3 vocabulary; do not change existing PR reconciliation behavior.
- Produce `REPORT_SCHEMA = "maintenance-audit-report.v1"`.
- Produce `AuditContractError(ValueError)`.
- Produce `normalize_observation(value: object) -> dict[str, object]`.
- Produce `classify_repository(value: object) -> dict[str, object]`.
- Produce `classify_portfolio(values: list[object]) -> list[dict[str, object]]` sorted by repository identity.
- Each report contains: `schema_version`, `report_id`, `repository`, `control_ref`, `observed_at`, `disposition`, `reason_codes`, `finding_classes`, `owner_class`, `evidence_refs`, optional `next_transition`, and `recheck_trigger`.
- `report_id` is SHA-256 over canonical repository/object identities, freshness bindings, finding classes and transition identity; `observed_at` is explicitly excluded from logical identity.

- [ ] **Step 1: Write RED tests for canonical disposition reuse and strict evidence validation**

Add tests named:
- `test_maintenance_engine_reuses_development_reconciliation_dispositions`
- `test_missing_required_source_fails_closed`
- `test_identity_mismatch_fails_closed`
- `test_duplicate_control_fails_closed`
- `test_untrusted_control_fails_closed`
- `test_report_identity_ignores_observation_timestamp`
- `test_report_identity_changes_when_authoritative_revision_changes`

Assertions must prove no Stage-2-only disposition vocabulary is introduced.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -W error -m unittest tests.test_maintenance_audit -v`
Expected: FAIL because `tools.maintenance_audit` and/or `development_reconciler.DISPOSITIONS` do not exist.

- [ ] **Step 3: Implement the minimal pure observation normalizer/report identity**

Implement only strict shape/identity/freshness normalization and stable report identity. No GitHub I/O and no mutation methods.

- [ ] **Step 4: Write RED rule tests from accepted #249 cases**

Load the fixture files and assert:
- clean/accepted future-spec state -> `NO_ACTION` with no synthetic transition;
- exact terminal owner while Control projection remains active -> `AUTO_ADVANCE` + diagnostic `CONTROL_ACTIVE_WORK_TERMINAL` and a proposed bounded sync-check transition, but no mutation;
- active trusted producer -> `NO_ACTION` + `ACTIVE_PRODUCER_YIELD`;
- explicit different-reviewer gate -> `NEEDS_REVIEWER` + `REVIEW_GATE_YIELD`;
- Human/device/security gate -> `NEEDS_HUMAN` + `HUMAN_GATE_YIELD`;
- unreadable/ambiguous source -> `NEEDS_EVIDENCE` + `SOURCE_UNAVAILABLE_OR_AMBIGUOUS`;
- semantic prose suspicion without deterministic desired value -> `NEEDS_EVIDENCE` + `SEMANTIC_PROJECTION_SUSPECTED`;
- stale search result plus exact terminal source -> exact source governs; search state is diagnostic only.

- [ ] **Step 5: Implement deterministic audit rules**

Rules operate only on normalized explicit fields. Do not inspect free-form similarity, Issue age, provider/model identity, labels or idle-worker state.

- [ ] **Step 6: Add compile coverage and run focused/full regression**

Modify `.github/workflows/project-sync-tests.yml` compile check to include `tools/maintenance_audit.py`.

Run: `python -W error -m unittest tests.test_maintenance_audit -v`
Expected: PASS.

Run: `python -W error -m unittest discover -v`
Expected: PASS with zero failures/errors and unchanged existing reconciliation behavior.

- [ ] **Step 7: Commit Task 1**

Commit: `feat: add read-only maintenance audit engine (#266)`

### Task 2: S2.2 exact GitHub collector, CLI, and manual read-only Action

**Files:**
- Create: `tools/maintenance_github.py`
- Create: `scripts/maintenance_audit.py`
- Create: `tests/test_maintenance_github.py`
- Create: `.github/workflows/maintenance-audit.yml`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Produce `GitHubReadError(RuntimeError)` that never embeds token values.
- Produce `GitHubReadTransport(token: str, api_base: str = "https://api.github.com")` with read-only methods for exact repository, Issue, PR, check/review and default-branch observations required by Task 1.
- Produce `collect_repository(transport, repository: str, control_ref: str, observed_at: str) -> dict[str, object]`.
- Produce `collect_portfolio(transport, controls: list[dict[str, object]], observed_at: str) -> list[dict[str, object]]`.
- CLI commands: `repository --repository owner/name --control N` and `portfolio`; both print canonical JSON and may write `--output PATH`.
- CLI exit code 0 means the audit executed and produced a report, even when findings exist; source/transport/contract failure returns non-zero and a machine-readable error envelope.

- [ ] **Step 1: Write RED transport tests with fake HTTP/read transport**

Cover pagination, exact issue re-read, PR/head/check review binding, 404/403/rate-limit failure, redaction, duplicate Control discovery, and source-unavailable preservation.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -W error -m unittest tests.test_maintenance_github -v`
Expected: FAIL because collector/transport modules do not exist.

- [ ] **Step 3: Implement the smallest read-only GitHub adapter and CLI**

Follow existing standard-library HTTP/error/redaction patterns from repository bootstrap/project sync. No POST/PATCH/PUT/DELETE methods exist in `GitHubReadTransport`.

- [ ] **Step 4: Write RED workflow contract tests**

Extend `tests/test_maintenance_github.py` to assert `.github/workflows/maintenance-audit.yml` initially has:
- `workflow_dispatch` only; no `schedule` yet;
- `contents: read`, with no repository-write permission in the read-only job;
- checkout/setup-python pinned consistently with current devflow workflows;
- default mode `audit` only;
- portfolio execution requires an already-configured `MAINTENANCE_AUDIT_TOKEN` secret and fails clearly when absent rather than falling back to incomplete cross-repo data;
- no secret value is printed into summary/artifact output.

- [ ] **Step 5: Implement the manual Action and machine outputs**

The workflow writes `maintenance-audit-report.json`, uploads it as an artifact, and appends only aggregate counts + finding references to `$GITHUB_STEP_SUMMARY`. Do not comment on #249 or create Issues on every run.

Single-repository `kinoko34077/devflow` diagnostic mode may use `${{ github.token }}`. Portfolio mode may consume `MAINTENANCE_AUDIT_TOKEN` only when it already exists; token creation/rotation/permission setup stays outside automation.

- [ ] **Step 6: Run focused/full tests and compile checks**

Run: `python -W error -m unittest tests.test_maintenance_audit tests.test_maintenance_github -v`
Expected: PASS.

Run: `python -W error -m unittest discover -v`
Expected: PASS.

Compile: `python -m py_compile tools/maintenance_audit.py tools/maintenance_github.py scripts/maintenance_audit.py`
Expected: PASS.

- [ ] **Step 7: Commit Task 2**

Commit: `feat: add manual maintenance audit action (#266)`

### Task 3: S2.3 deterministic triage and no-task-inflation policy

**Files:**
- Create: `tools/maintenance_triage.py`
- Create: `tests/test_maintenance_triage.py`
- Modify: `scripts/maintenance_audit.py`
- Modify: `.github/workflows/maintenance-audit.yml`

**Interfaces:**
- Produce immutable `TriageDecision(action: str, report_id: str, disposition: str, work_class: str | None, owner_ref: str | None, reason_codes: tuple[str, ...])`.
- Produce `triage(report: dict[str, object]) -> TriageDecision`.
- Closed local action vocabulary: `NO_TRACK`, `ROUTE_EXISTING_GATE`, `RECORD_NONRUNNABLE_FINDING`, `PUBLISH_EXISTING_OWNER`, `PLAN_SYNC_CHECK`. This is an execution decision vocabulary, not a Development Reconciliation disposition.
- `PUBLISH_EXISTING_OWNER` requires an already-existing exact owning Issue/Work Order that independently satisfies accepted candidate criteria; triage never manufactures a new owning task from a scan alone.

- [ ] **Step 1: Write RED no-inflation tests**

Assert:
- clean/future-spec/active-producer reports -> `NO_TRACK`;
- `NEEDS_REVIEWER`, `NEEDS_HUMAN`, `WAIT_EXTERNAL` -> `ROUTE_EXISTING_GATE`, never maintenance implementation supply;
- source-unavailable or semantic ambiguity -> `RECORD_NONRUNNABLE_FINDING`, never runnable supply;
- allowlisted deterministic drift with existing owner -> `PLAN_SYNC_CHECK` or `PUBLISH_EXISTING_OWNER` according to whether the action is machine-repairable;
- repeated unchanged `report_id` yields the same decision;
- changed authoritative evidence creates a new decision identity.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -W error -m unittest tests.test_maintenance_triage -v`
Expected: FAIL because triage module does not exist.

- [ ] **Step 3: Implement pure triage**

Do not perform GitHub writes in this module. Preserve canonical disposition and reason codes verbatim in the decision.

- [ ] **Step 4: Add CLI `triage` mode and artifact output**

`python scripts/maintenance_audit.py portfolio --triage` emits the audit report plus triage decisions. The GitHub Action remains read-only and does not publish/repair yet.

- [ ] **Step 5: Run focused/full regression**

Run: `python -W error -m unittest tests.test_maintenance_audit tests.test_maintenance_triage tests.test_maintenance_github -v`
Expected: PASS.

Run: `python -W error -m unittest discover -v`
Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Commit: `feat: add deterministic maintenance triage (#266)`

### Task 4: S2.4 bounded sync-check executor for stale machine-readable candidate projection

**Files:**
- Create: `tools/maintenance_sync_check.py`
- Create: `tests/test_maintenance_sync_check.py`
- Modify: `scripts/maintenance_audit.py`

**Interfaces:**
- Produce immutable `SyncCheckPlan(kind: str, repository: str, control_ref: str, owner_ref: str, expected_control_body_sha256: str, expected_owner_body_sha256: str, candidate_task_ref: str, report_id: str)`.
- Initial and only accepted `kind`: `WITHDRAW_STALE_CONTROL_CANDIDATE`.
- Produce `build_sync_check_plan(report, control_snapshot, owner_snapshot) -> SyncCheckPlan | None`.
- Produce `execute_sync_check(plan: SyncCheckPlan, transport: SyncCheckTransport) -> SyncCheckResult`.
- `SyncCheckTransport` exposes exact readback plus one bounded Control-body update; it has no arbitrary Issue-close, PR-merge, README/Current-State edit, credential or repository-admin methods.
- Candidate projection editor changes only the exact `DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN/END` JSON block and preserves every byte outside that marker pair.

- [ ] **Step 1: Write RED planning tests for the one-item allowlist**

Plan exists only when the exact owner is terminal/non-runnable, the stale candidate still exists, report disposition/transition matches the accepted contract, and producer/Human/reviewer/external/security gates are absent. All other findings return no plan.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -W error -m unittest tests.test_maintenance_sync_check -v`
Expected: FAIL because sync-check module does not exist.

- [ ] **Step 3: Implement pure projection editing and plan creation**

Strictly validate marker count/order/schema/repository identity. Unknown/malformed projection data fails closed; never rebuild the whole Control from partial parsed fields.

- [ ] **Step 4: Write RED executor tests for re-observation and idempotency**

Assert:
- unchanged Control+owner identity -> one bounded write + post-write readback;
- Control body digest moved -> `NEEDS_EVIDENCE`, zero writes;
- owner body/state moved -> `NEEDS_EVIDENCE`, zero writes;
- new Human/reviewer/external/producer gate -> no write;
- second execution after successful withdrawal -> already-applied/no-op;
- unrelated Control prose and other candidate entries are byte-for-byte preserved;
- semantic prose finding can never produce this plan.

- [ ] **Step 5: Implement executor with immediate exact re-read**

Mutation occurs only after the final guards pass. A failed or unconfirmed update returns to observation; no retry loop applies a stale plan.

- [ ] **Step 6: Expose manual `sync-check --apply` CLI only**

The GitHub Actions scheduled/manual audit job does not invoke `--apply`. The manual apply path requires a write-capable already-approved token and explicit operator invocation; credential setup is not automated.

- [ ] **Step 7: Run focused/full regression**

Run: `python -W error -m unittest tests.test_maintenance_sync_check -v`
Expected: PASS.

Run: `python -W error -m unittest discover -v`
Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Commit: `feat: add bounded maintenance sync check (#266)`

### Task 5: S2.5 existing-owner supply integration through accepted Control/#209 authority

**Files:**
- Create: `tools/maintenance_supply.py`
- Create: `tests/test_maintenance_supply.py`
- Modify: `scripts/maintenance_audit.py`
- Modify: `.github/workflows/maintenance-audit.yml`
- Create: `docs/operations/MAINTENANCE_AUDIT.md`

**Interfaces:**
- Produce `build_existing_owner_candidate(decision, owner_snapshot, control_snapshot) -> dict[str, object] | None` using the accepted candidate envelope/work-class contract.
- Produce `reconcile_existing_owner_supply(existing_projection, desired_candidate) -> dict[str, object]` returning desired projection plus superseded identities.
- Supply integration may publish/withdraw only an already-existing owner whose exact body/state independently satisfies accepted candidate admission and freshness rules.
- Publisher execution identity is included so a candidate added/relaxed by the current attempt is tagged/omitted from consumption in that same attempt, preserving 3C.
- No automatic creation of a new owning Issue in Stage-2 v1.

- [ ] **Step 1: Write RED publication/withdrawal tests**

Cover:
- existing exact owner + `work_class=sync-check` -> deterministic candidate envelope;
- no owner -> no candidate and no Issue creation request;
- stale owner digest/status -> no candidate;
- Human/reviewer/external/security gate -> no candidate;
- same evidence -> stable candidate identity/no duplicate;
- owner readiness/freshness change -> stale publication withdrawn;
- publisher cannot consume the candidate in the same execution attempt.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -W error -m unittest tests.test_maintenance_supply -v`
Expected: FAIL because maintenance supply module does not exist.

- [ ] **Step 3: Implement pure existing-owner supply builder/reconciler**

Reuse accepted work-class/candidate fields. Do not create a new candidate schema or infer role/capabilities from provider/model identity.

- [ ] **Step 4: Add bounded publication adapter to the CLI/workflow**

Publication writes only the relevant machine-readable Repository Control candidate projection and records a compact transition on `devflow#209` only when the supply set materially changes. Clean/repeated runs do not append comments.

Scheduled mode still does not execute sync-check mutation or consume newly published supply.

- [ ] **Step 5: Write/verify operator documentation**

`docs/operations/MAINTENANCE_AUDIT.md` documents:
- authority/read order;
- audit/triage/supply/sync-check separation;
- credential boundary;
- report/artifact format;
- manual sync-check apply path;
- failure/recovery behavior;
- no-task-inflation and 3C rules;
- scheduled mode is read-only audit/triage + bounded existing-owner supply reconciliation only.

- [ ] **Step 6: Run focused/full regression**

Run: `python -W error -m unittest tests.test_maintenance_supply tests.test_maintenance_triage tests.test_maintenance_sync_check -v`
Expected: PASS.

Run: `python -W error -m unittest discover -v`
Expected: PASS.

- [ ] **Step 7: Commit Task 5**

Commit: `feat: integrate maintenance findings with existing supply (#266)`

### Task 6: S2.6 real portfolio pilot against #249-derived classes

**Files:**
- No new production file unless the pilot exposes a concrete defect.
- Update owning Stage-2 Issue/progress surfaces created after S2.1 acceptance.
- Update PR evidence for the implementation branch.

**Interfaces:**
- Consumes Tasks 1–5 with schedule still disabled.
- Produces one reproducible real audit/triage pilot artifact and one bounded sync-check dry-run/optional manual-apply proof.

- [ ] **Step 1: Obtain/confirm an approved cross-repository read credential**

If `MAINTENANCE_AUDIT_TOKEN` or an equivalent already-approved least-privilege read credential does not exist, stop at the Human/security boundary and record the exact required permission scope. Do not create/rotate/store credentials automatically.

- [ ] **Step 2: Run one manual portfolio audit/triage Action**

Pilot must include at least:
- one clean/intentional-open repository;
- one live producer/gated repository that must yield;
- one historical or controlled stale-projection fixture-equivalent that produces a deterministic finding;
- one source-unavailable simulation/test proving portfolio failure is not hidden.

Record workflow run ID, artifact identity, repository count, disposition/finding counts, and exact evidence refs.

- [ ] **Step 3: Compare machine output to bounded manual exact-fetch audit**

Manually exact-fetch only the pilot sample, not the whole portfolio. Acceptance requires no classification disagreement on the sample and zero synthetic task/candidate creation.

- [ ] **Step 4: Exercise sync-check dry-run, then one real apply only if a currently valid allowlisted candidate exists**

If no real allowlisted drift exists, do not manufacture one in live GitHub. Use the deterministic integration test as mutation proof and record `NO_LIVE_APPLY_CANDIDATE` for the pilot.

If one exists, require immediate re-read guards, one mutation, post-write confirmation and second-run no-op.

- [ ] **Step 5: Re-read runtime/supply after publication**

Verify the publisher did not consume its own changed supply and execution-coordinator claims remain unchanged unless a later independent consumer legitimately claims work.

- [ ] **Step 6: Record pilot disposition on `devflow#232/#215/#249`**

#249 receives only a compact handoff/regression-coverage checkpoint; detailed implementation evidence stays with the Stage-2 owner/PR.

### Task 7: S2.7 verification/review and S2.8 scheduled read-only acceptance

**Files:**
- Modify: `.github/workflows/maintenance-audit.yml`
- Modify only if accepted state changes: `.devflow/WORKFLOW.yaml`, `AGENTS.md`, `docs/operations/MAINTENANCE_AUDIT.md`

**Interfaces:**
- Consumes accepted pilot from Task 6.
- Produces scheduled GitHub Actions audit/triage with no automatic sync-check apply.

- [ ] **Step 1: Add the schedule only after the S2.6 pilot is accepted**

Add once-daily cron `23 18 * * *` (03:23 JST) to `.github/workflows/maintenance-audit.yml`.

Scheduled execution is fixed to read-only exact portfolio audit + deterministic triage + bounded existing-owner supply reconciliation. It MUST NOT invoke manual `sync-check --apply`.

- [ ] **Step 2: Add concurrency/failure fencing**

Use one portfolio concurrency group with `cancel-in-progress: false`. A source/credential/API failure makes the run non-clean and preserves a typed artifact/summary; a failed scan never withdraws unrelated supply merely because observation is incomplete.

- [ ] **Step 3: Run exact-head full verification**

Run locally/CI: `python -W error -m unittest discover -v` and compile checks for all new modules/scripts.
Expected: PASS.

Require the repository Required PR gate GREEN on the exact implementation head.

- [ ] **Step 4: Perform Formal Review on exact head**

Review focus must include the five global Review Focus cases, credential redaction, cross-repo source failure, schedule read-only guarantee, no-task-inflation, 3C, expected-identity sync-check fencing and regression behavior.

Require a qualifying different-system/model current-head Review if devflow review policy classifies the control-plane/authority change as requiring one. Do not self-satisfy such a gate.

- [ ] **Step 5: Merge only after all current gates pass**

Use expected-head guarded merge under existing authorization/revert policy. No release/deploy/publication external effect or credential/permission mutation is implied by merge.

- [ ] **Step 6: Post-main verification and direct affected-surface reconciliation**

Require post-main `verify`, then reconcile the finite directly affected set: Stage-2 owning Issue, `devflow#232`, `devflow#215`, Control #16, `devflow#209`, operations doc, and `devflow#249` compact automation-handoff checkpoint. Do not perform a global cleanup sweep.

- [ ] **Step 7: S2.8 acceptance**

Accept Stage 2 only when:
- scheduled read-only audit/triage runs from accepted main;
- real pilot matched bounded manual exact-fetch truth;
- required-source failure does not appear clean;
- active producer/Human/reviewer gates are yielded to;
- unchanged reruns do not create duplicate tasks/comments/supply;
- existing-owner supply is withdrawn when owner freshness/readiness changes;
- sync-check manual apply is exact-identity guarded and idempotent;
- no second queue/state machine/claim authority exists;
- execution-coordinator remains sole runtime claim authority.

Then and only then may `devflow#232/#215` evaluate Stage-3 release under their existing evidence gate.

## Plan Self-Review Result

- **Spec coverage:** S2.2 through S2.8 are each mapped to one or more independently testable Tasks; S2.1 is an explicit preflight dependency, not reimplemented here.
- **Step granularity:** each implementation task has an explicit RED test, focused GREEN verification, full regression and commit boundary; real-pilot/acceptance tasks contain only external integration steps.
- **Type consistency:** audit report -> `TriageDecision` -> optional `SyncCheckPlan` / existing-owner candidate is one-way; canonical Development Reconciliation disposition is preserved at every boundary.
- **Review Focus coverage:** exact-vs-search, source failure, live producer yield, semantic ambiguity and stale-plan re-observation each have a named test/task owner.
- **Proportion/YAGNI:** initial scheduled mode does not auto-apply sync-check; S2.4 supports exactly one machine-readable candidate-withdrawal mutation class; no new task database, health dashboard, scheduler or LLM semantic auditor is added.
