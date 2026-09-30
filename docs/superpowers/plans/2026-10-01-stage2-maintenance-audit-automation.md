# Stage 2 Maintenance Audit Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the manual cross-repository consistency sweep proven in `devflow#249` into a deterministic GitHub-native Stage-2 maintenance producer for bounded audit, triage, sync-check handoff, and existing-authority candidate publication.

**Architecture:** Extend the accepted Development Reconciliation line; do not create a new lifecycle. `devflow` owns exact-evidence collection, pure audit rules and triage. Ordinary runnable maintenance remains an accepted `DEVFLOW_EXECUTION_CANDIDATES_V1` Repository Control projection and is consumed by `execution-coordinator`, which remains the sole claim/lease/fencing authority. Initial automation is read-only by default; semantic prose rewriting and arbitrary durable mutation stay outside the automatic path.

**Tech Stack:** Python standard library, `dataclasses`, `hashlib`, `json`, `urllib.request`, `unittest`, existing devflow candidate/reconciliation contracts, existing execution-coordinator discovery/ranking/portfolio code, GitHub Actions.

**Spec:** accepted `docs/spec/DEVELOPMENT_RECONCILIATION.md` Section 10 after `devflow#264 / PR#265`; staged authority `devflow#215/#232`; regression source `devflow#249`; candidate authority `devflow#125`; supply authority `devflow#209`; execution consumer Control `devflow#107`.

## Global Constraints

- Do not execute S2.2 until S2.1 / `devflow#264` is accepted on `main`; before every slice re-read `devflow/AGENTS.md`, Control #16, `devflow#232`, the slice owner and accepted Section 10.
- Reuse only the existing Development Reconciliation dispositions: `AUTO_ADVANCE`, `NEEDS_REVIEWER`, `NEEDS_RECOVERY`, `NEEDS_HUMAN`, `WAIT_EXTERNAL`, `NEEDS_EVIDENCE`, `NO_ACTION`. Finding names are diagnostic metadata only.
- GitHub Project/search/index/Issue age/labels/branch existence/provider identity/idle-worker state never establish closure, readiness, mutation authority or runnable demand.
- Discovery may locate an object; every fact used by a rule comes from an exact authoritative read with identity plus SHA/digest/revision and observation time.
- Required source failure, duplicate authority, identity mismatch, contradiction or insufficient freshness -> `NEEDS_EVIDENCE`, never clean/no-op.
- Initial execution is read-only. S2.4 may prepare a guarded sync-check request but does not rewrite free-form Control/README/Current State prose automatically.
- No arbitrary Issue closure, PR merge, source-code fix, release/deploy/publication, credential/session/permission/IAM change, destructive/shared-history operation or RDC.
- Candidate source remains the unique Repository Control `DEVFLOW_EXECUTION_CANDIDATES_V1` task-envelope projection bound to exact owning-Issue body SHA-256; `DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1` is companion scheduling/work-class evidence.
- Owning Issue/Work Order remains detailed task truth. No finding creates an Issue merely to keep workers busy.
- Publication and consumption remain separated: a run that creates/adds/relaxes supply cannot consume that changed supply in the same execution attempt.
- `execution-coordinator` remains the runtime authority and Issue #3 is never edited directly by Stage 2.
- Cross-repository live reads/writes may name a required secret/input, but code must not create, inspect, rotate or populate credential values.

## Review Focus

- Search says open while exact fetch says closed -> exact fetch wins.
- One required source is unavailable while all others look clean -> `NEEDS_EVIDENCE`.
- Active trusted producer overlaps suspected drift -> `ACTIVE_PRODUCER_YIELD`, no maintenance supply.
- Semantic-only prose mismatch without machine-determined replacement -> `SEMANTIC_PROJECTION_SUSPECTED` / `NEEDS_EVIDENCE`, no edit.
- Same logical evidence at a later timestamp -> same report ID; changed SHA/digest/owner truth -> different report ID.

---

### Task 1: S2.2 pure audit core and #249 regression fixtures

**Files:**
- Create: `tools/maintenance_audit.py`
- Create: `tests/test_maintenance_audit.py`
- Create: `tests/fixtures/maintenance_audit/*.json`
- Create: `docs/spec/schemas/maintenance-audit-report.v1.schema.json`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- `MAINTENANCE_REPORT_SCHEMA = "maintenance-audit-report.v1"`
- `EvidenceRef(ref: str, revision: str)`
- `MaintenanceReport(repository: str, control_ref: str, observed_at: str, evidence: tuple[EvidenceRef, ...], disposition: str, reason_codes: tuple[str, ...], finding: str | None, owner_class: str, transition: str | None, recheck_trigger: str | None, report_id: str)`
- `evaluate_observation(observation: Mapping[str, object]) -> MaintenanceReport`
- `report_to_dict(report: MaintenanceReport) -> dict[str, object]`
- `report_id` = SHA-256 over repository/control identity + sorted `(ref, revision)` + finding + transition; observation timestamp is excluded.

- [ ] **Step 1: Write RED fixture tests**

Pin at least:
- exact terminal owner + stale Control Active Work -> `AUTO_ADVANCE / CONTROL_ACTIVE_WORK_TERMINAL / SYNC_CONTROL_ROUTING`;
- terminal Next Action target -> `AUTO_ADVANCE / STALE_NEXT_ACTION_TARGET / SYNC_CONTROL_ROUTING`;
- active producer -> `NO_ACTION / ACTIVE_PRODUCER_YIELD`;
- missing different reviewer -> `NEEDS_REVIEWER / REVIEW_GATE_YIELD`;
- Human/security/device gate -> `NEEDS_HUMAN / HUMAN_GATE_YIELD`;
- required source missing/duplicate/ambiguous -> `NEEDS_EVIDENCE / SOURCE_UNAVAILABLE_OR_AMBIGUOUS`;
- semantic-only mismatch -> `NEEDS_EVIDENCE / SEMANTIC_PROJECTION_SUSPECTED`;
- accepted future/spec intentionally open -> `NO_ACTION`;
- stale search hint versus exact terminal truth -> exact truth wins;
- timestamp-only re-observation keeps report ID; authoritative revision change changes it.

- [ ] **Step 2: Run RED**

Run: `python -W error -m unittest tests.test_maintenance_audit -v`  
Expected: FAIL because the module/schema do not exist.

- [ ] **Step 3: Implement the pure evaluator/report schema**

No network calls or GitHub mutations in this module.

- [ ] **Step 4: Add schema-parity tests**

Every fixture output validates; unknown disposition/finding shape and empty authoritative revision fail.

- [ ] **Step 5: Add compile verification and run full suite**

Run focused tests, `python -W error -m unittest discover -v`, and compile `tools/maintenance_audit.py`.

- [ ] **Step 6: Commit/review/merge S2.2 audit-core slice**

Create/reuse a bounded S2.2 owner, exact-head PR gate + Formal Review, merge/post-main verify, then reconcile `#232/#215/#16` before the next slice.

### Task 2: S2.2 exact GitHub collector and read-only CLI

**Files:**
- Create: `tools/maintenance_audit_github.py`
- Create: `scripts/maintenance_audit.py`
- Create: `tests/test_maintenance_audit_github.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- `GitHubReadTransport.get_json(url: str) -> object`
- `collect_repository(transport: GitHubReadTransport, control_ref: str, observed_at: str) -> dict[str, object]`
- `collect_portfolio(transport: GitHubReadTransport, control_refs: Sequence[str], observed_at: str) -> tuple[dict[str, object], ...]`
- CLI: `python scripts/maintenance_audit.py audit [--control kinoko34077/devflow#N ...] [--json-out PATH]`
- CLI reads pre-existing `GITHUB_TOKEN`; missing token is a fail-closed configuration error and token material is never logged.

- [ ] **Step 1: Write RED fake-transport tests**

Cover exact Control, owner Issue, referenced PR/head/check/review/default-branch, trusted Session evidence, source failure preservation and duplicate authority. Search/index is never final authority.

- [ ] **Step 2: Run RED**

Run: `python -W error -m unittest tests.test_maintenance_audit_github -v`.

- [ ] **Step 3: Implement read-only collection**

Use standard-library HTTP. Preserve exact URLs/IDs/body digests/SHA as revisions.

- [ ] **Step 4: Add CLI determinism/no-secret tests**

JSON output sorted by repository; no network mutation; missing token exits non-zero; output contains no credential value.

- [ ] **Step 5: Run focused/full tests and compile**

Compile `tools/maintenance_audit.py`, `tools/maintenance_audit_github.py`, `scripts/maintenance_audit.py` and run full suite.

- [ ] **Step 6: Accept S2.2 collector slice**

No scheduled workflow yet. Merge/reconcile S2.2 before S2.3.

### Task 3: S2.3 deterministic triage without task inflation

**Files:**
- Create: `tools/maintenance_triage.py`
- Create: `tests/test_maintenance_triage.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- `TriageDecision(report_id: str, disposition: str, route: str, work_class: str | None, action: str | None, task_ref: str | None, reason_codes: tuple[str, ...])`
- Internal route values only: `NOOP`, `TRACK_ONLY`, `SYNC_CHECK`, `PUBLISH_EXISTING_OWNER`.
- `triage_report(report: MaintenanceReport, *, existing_owner_ref: str | None) -> TriageDecision`

- [ ] **Step 1: Write RED routing tests**

Clean/future-spec/active producer -> `NOOP`; reviewer/Human/external gate -> existing disposition + no maintenance candidate; source/semantic ambiguity -> `TRACK_ONLY`, and only an already-eligible owner can become `PUBLISH_EXISTING_OWNER` with `work_class="triage"`; deterministic stale projection -> `SYNC_CHECK`, `work_class="sync-check"`, action `RECONCILE_STALE_PROJECTION`; recovery remains on the existing recovery path; no owner -> no synthetic Issue/candidate.

- [ ] **Step 2: Run RED**

Run: `python -W error -m unittest tests.test_maintenance_triage -v`.

- [ ] **Step 3: Implement pure mapper**

No GitHub I/O and no new disposition lifecycle.

- [ ] **Step 4: Add #249 no-inflation regressions**

Clean WAIT, active producer, reviewer gate, Human/device gate and historical/future-spec cases all emit no maintenance supply.

- [ ] **Step 5: Full regression + bounded S2.3 PR acceptance**

Merge/reconcile before S2.4.

### Task 4: S2.4 guarded sync-check planning

**Files:**
- Create: `tools/maintenance_sync_check.py`
- Create: `tests/test_maintenance_sync_check.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- `SyncCheckPlan(report_id: str, repository: str, control_ref: str, finding: str, transition: str, expected_evidence: tuple[EvidenceRef, ...], task_ref: str | None)`
- `plan_sync_check(report: MaintenanceReport, decision: TriageDecision) -> SyncCheckPlan | None`
- `verify_sync_preconditions(plan: SyncCheckPlan, current: MaintenanceReport) -> str` returning exactly `MATCH`, `CHANGED`, or `NO_LONGER_ACTIONABLE`.

- [ ] **Step 1: Write RED allowlist tests**

Only `CONTROL_ACTIVE_WORK_TERMINAL` and `STALE_NEXT_ACTION_TARGET` may initially plan `SYNC_CONTROL_ROUTING`; all gated/producer/semantic/source-unavailable cases return `None`.

- [ ] **Step 2: Write RED freshness tests**

Exact evidence identity -> `MATCH`; any authoritative revision change -> `CHANGED`; now-clean state -> `NO_LONGER_ACTIONABLE`.

- [ ] **Step 3: Implement plan/guard only**

Stage-2 v1 does not automatically rewrite free-form Control prose. The plan is handed to a later authorized worker/candidate. If review selects a concrete machine-owned projection with a safe write contract, add that mutation as a separate bounded child rather than widening S2.4 silently.

- [ ] **Step 4: Full regression + bounded S2.4 PR acceptance**

Record whether direct durable mutation is `NOT_NEEDED` for Stage-2 v1 because guarded supply handoff is sufficient.

### Task 5: S2.5 candidate-source projection using execution-coordinator's accepted codec semantics

This is intentionally cross-repository because `execution-coordinator` owns the accepted parser, `ClaimCandidate` shape and candidate fingerprint algorithm. Do not duplicate those semantics independently in devflow.

**Files — execution-coordinator:**
- Create: `src/execution_coordinator/maintenance_projection.py`
- Create: `tests/test_maintenance_projection.py`
- Modify only if required for exports: `src/execution_coordinator/__init__.py`

**Files — devflow:**
- Create: `tools/maintenance_supply.py`
- Create: `tests/test_maintenance_supply.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces — execution-coordinator:**
- `build_maintenance_task_envelope(*, task: IssueDocument, task_work_status: str, entry_ref: str, conflict_keys: Iterable[str], work_order_ref: str | None) -> dict[str, object]`
- Output is the accepted v1 task envelope: `task`, `task_body_sha256`, `task_work_status`, `entry_ref`, `scope_ready`, `blocked`, `requires_user_confirmation`, optional `conflict_keys`/`work_order_ref`, and `roles=[{"role":"implementer","next_action_tag":"IMPLEMENT"}]`.
- `build_maintenance_portfolio_entry(*, control: IssueDocument, candidate: ClaimCandidate, task_body_sha256: str, work_class: str, observed_at: datetime, fresh_until: datetime, dependency_order: int = 0) -> dict[str, object]`
- The companion entry uses existing `candidate_fingerprint(candidate)`, `ReadinessClass.IMPLEMENT`, exact Control priority, `dependency_ready=True`, required capability/environment tags, and `work_class` exactly `triage` or `sync-check`.
- `replace_maintenance_projection(control_body: str, *, envelope: Mapping[str, object] | None, portfolio_entry: Mapping[str, object] | None) -> str` changes only the accepted candidate/portfolio marker blocks and preserves all other Control text byte-for-byte.

**Interfaces — devflow:**
- `MaintenanceDemand(task_ref: str, report_id: str, work_class: str, action: str)`
- `build_maintenance_demand(decision: TriageDecision, report: MaintenanceReport) -> MaintenanceDemand | None`
- It returns demand only when an existing/reused owner is eligible; it never fabricates the candidate fingerprint or Control envelope itself.

- [ ] **Step 1: Open a separate execution-coordinator owner only after S2.4 proves this concrete publisher gap**

Read Control #107 and repository-local canon first. This child owns codec/rendering only, not supply policy or runtime claim semantics.

- [ ] **Step 2: Write RED round-trip tests in execution-coordinator**

Render a maintenance envelope + portfolio entry into a Control body, then parse it through existing `discovery` and `portfolio_metadata`. Assert exactly one implementer candidate, exact owning-body digest, exact existing `candidate_fingerprint`, `ReadinessClass.IMPLEMENT`, and requested `work_class`. Unrelated Control prose and unrelated candidate envelopes/metadata entries remain unchanged.

- [ ] **Step 3: Add fail-closed tests**

Reject non-`READY_FOR_IMPLEMENTATION` owner, closed/untrusted owner, `requires_user_confirmation`, unsupported work class, stale/mismatched task digest, duplicate `(task, role)`, and any attempt to publish reviewer/recovery through this maintenance codec.

- [ ] **Step 4: Implement minimal pure renderer in execution-coordinator**

No GitHub writes or runtime claims. Reuse existing `discovery.py`, `portfolio_metadata.py`, `ranking.candidate_fingerprint`, `ReadinessClass` and `Role`; do not fork their rules.

- [ ] **Step 5: Implement devflow demand builder**

RED/GREEN tests prove only `PUBLISH_EXISTING_OWNER`/`SYNC_CHECK` decisions with an exact owner emit `MaintenanceDemand`; no owner/gate/recovery/no-op emits none.

- [ ] **Step 6: Cross-repo compatibility verification**

Use the rendered Control fixture as Chat Worker Bootstrap evidence and prove a maintenance-only request selects matching `triage`/`sync-check` while unrelated implementation/formal-review demand is omitted. Accepted S1.12 contradictory role/work-class behavior remains fail-closed.

- [ ] **Step 7: Review/merge/reconcile each repository independently**

execution-coordinator child PR first; post-main verify and Control #107 reconciliation. Then devflow S2.5 PR consumes the accepted codec boundary. Do not stack unaccepted cross-repo branches.

### Task 6: S2.6 real GitHub Actions pilot, S2.7 review, S2.8 acceptance

**Files — devflow:**
- Create: `.github/workflows/maintenance-audit.yml`
- Create: `tests/test_maintenance_audit_workflow.py`
- Modify: `scripts/maintenance_audit.py`

**Workflow contract:**
- `workflow_dispatch` inputs: `mode = audit | publish` (default `audit`) plus optional target Control list.
- Pre-existing secret `MAINTENANCE_AUDIT_TOKEN` is mapped to `GITHUB_TOKEN`; workflow never creates/prints/rotates it.
- `audit`: exact reads -> report JSON + Actions Summary only.
- `publish`: same read/triage + Control candidate/portfolio projection write only for an already-eligible owner and accepted S2.5 codec; no runtime claim and no same-attempt consumption.
- To reuse the accepted renderer without copying it, checkout `kinoko34077/execution-coordinator` at the exact accepted Control #107 Audit SHA into a second path and add its `src` to `PYTHONPATH` for publish mode.

- [ ] **Step 1: Write RED workflow-structure tests**

Require manual dispatch, default read-only mode, least-privilege workflow permissions, no `pull_request_target`, no token echo, no mutation in audit mode, separately gated publish path, and no schedule yet.

- [ ] **Step 2: Implement manual workflow**

Missing credential/source failure -> fail closed and publish nothing.

- [ ] **Step 3: Run real audit pilot over at least three live classes**

1. clean/intentional WAIT;
2. active producer or reviewer/Human-gated repo that must yield;
3. known/staged stale projection or fixture-backed finding that reaches deterministic triage without semantic guessing.

Compare Action results with a fresh manual #249-style exact-read audit. Any mismatch blocks acceptance.

- [ ] **Step 4: Run one real publish/withdraw lifecycle only if eligible demand exists**

Publish an existing-owner maintenance candidate, verify a separate later read sees it, prove the producer attempt cannot consume it, then withdraw/supersede on owner/freshness/readiness change. If no real demand exists, record `NO_REAL_DEMAND`; do not manufacture one.

- [ ] **Step 5: Exact-head verification/review**

Full devflow tests/compile, Required PR gate, Formal Review and any currently required different-system/model review.

- [ ] **Step 6: Merge/post-main verify/reconcile and complete S2.8**

Reconcile slice owner, `#232`, `#215`, Control #16, and `#249` only where cross-repo summary changes. Accept Stage 2 only with clean final runtime claims and no synthetic supply.

- [ ] **Step 7: Schedule is a separate post-pilot bounded change**

After the manual pilot is accepted and the user has configured an approved read-capable credential, add recurring schedule in a separate PR. Scheduled mode defaults to `audit`; scheduled `publish` requires separate accepted evidence.

## PR / ownership split

1. S2.2 audit core + collector (Tasks 1-2; split only if review needs an independent I/O boundary).
2. S2.3 triage (Task 3).
3. S2.4 guarded sync-check planning (Task 4).
4. S2.5 execution-coordinator codec child, then devflow demand integration (Task 5; separate repo-local PRs).
5. S2.6/7 manual Actions pilot + verification (Task 6).
6. S2.8 is acceptance/reconciliation, not a feature PR unless a concrete defect appears.

Every materially distinct slice checkpoints `devflow#232` before the next slice. `devflow#249` remains the broad audit backstop/regression source, not the log sink for every clean Action run.
