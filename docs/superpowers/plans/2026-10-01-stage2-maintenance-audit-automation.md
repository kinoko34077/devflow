# Stage 2 Maintenance Audit Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the manual cross-repository consistency work proven in `devflow#249` into a deterministic, GitHub-native Stage-2 maintenance producer that performs bounded read-only audit, deterministic triage, guarded sync-check planning, and existing-authority supply publication without creating a second task database or claim system.

**Architecture:** Extend the accepted Development Reconciliation line rather than creating a new lifecycle. `devflow` owns a pure Python audit/triage producer and GitHub read adapter; reports reuse the existing Development Reconciliation dispositions, and actionable maintenance demand is projected through the already-accepted Repository Control candidate-source contract for later consumption by `execution-coordinator`. Initial automation is read-only by default; free-form README/Current State rewriting and arbitrary Issue/PR mutation stay outside the automatic path.

**Tech Stack:** Python standard library, `dataclasses`, `hashlib`, `json`, `re`, `urllib.request`, `unittest`, existing devflow Repository Control / candidate-source contracts, GitHub Actions.

**Spec:** `docs/spec/DEVELOPMENT_RECONCILIATION.md` Section 10 after acceptance of `devflow#264 / PR#265`; staged authority `devflow#215/#232`; regression source `devflow#249`; durable candidate authority `devflow#125`; supply authority `devflow#209`.

## Global Constraints

- Do not execute Task 1 until S2.1 / `devflow#264` is accepted on `main`; before every task, re-read `devflow/AGENTS.md`, Control #16, `devflow#232`, the task owner, and accepted Section 10.
- Reuse the existing Development Reconciliation dispositions: `AUTO_ADVANCE`, `NEEDS_REVIEWER`, `NEEDS_RECOVERY`, `NEEDS_HUMAN`, `WAIT_EXTERNAL`, `NEEDS_EVIDENCE`, `NO_ACTION`. Finding names are diagnostic metadata only.
- GitHub Project/search/index/Issue age/labels/branch existence/provider identity/idle-worker state never establish closure, readiness, mutation authority, or runnable demand.
- Discovery may identify a candidate object; exact Issue/PR/Control/branch/check/review readback must establish the fact used by a rule.
- Required source read failure, duplicate authority, identity mismatch, contradictory evidence, or insufficient freshness fails closed as `NEEDS_EVIDENCE`; it is never reported as clean.
- Initial execution is read-only. Automatic durable mutation is not added merely because a stale projection is detected.
- No semantic rewriting of README or Current State prose, arbitrary Issue closure, arbitrary PR merge, source-code fix, release/deploy/publication, credential/session/permission/IAM change, destructive/shared-history operation, or RDC.
- Candidate source remains the unique Repository Control `DEVFLOW_EXECUTION_CANDIDATES_V1` projection bound to exact owning-Issue body SHA-256; owning Issue/Work Order remains detailed durable task truth.
- A run that publishes/adds/relaxes a candidate must not consume that candidate in the same execution attempt (3C separation).
- No finding creates a new Issue merely to keep workers busy. Publish only when an existing/reused durable owner satisfies the accepted tracking boundary; otherwise retain the report as evidence and emit no runnable candidate.
- `execution-coordinator` remains the sole runtime claim/lease/generation/fencing authority; Stage 2 never writes runtime Issue #3 directly.
- Cross-repository live reads require a separately approved read-capable credential when repository visibility demands it. Code/workflow may define the input name, but must not create, inspect, rotate, or populate credential values.

## Review Focus

- Search/index says an Issue is open while exact fetch says closed: exact fetch wins and the report must not preserve stale routing from search.
- One source is unavailable while all other evidence looks clean: the repository result must be `NEEDS_EVIDENCE`, not `NO_ACTION`/clean.
- An active trusted producer overlaps the suspected drift: report `ACTIVE_PRODUCER_YIELD` and emit no maintenance supply.
- A semantic-only prose mismatch is suspected but machine authority does not determine the replacement text: emit `SEMANTIC_PROJECTION_SUSPECTED` / `NEEDS_EVIDENCE`, never an automatic edit.
- Re-observing unchanged evidence at a later timestamp must produce the same logical report/finding identity; changed SHA/digest/owner truth must produce a different identity.

---

### Task 1: S2.2 pure audit core and #249 regression fixtures

**Files:**
- Create: `tools/maintenance_audit.py`
- Create: `tests/test_maintenance_audit.py`
- Create: `tests/fixtures/maintenance_audit/control-active-work-terminal.json`
- Create: `tests/fixtures/maintenance_audit/stale-next-action.json`
- Create: `tests/fixtures/maintenance_audit/active-producer-yield.json`
- Create: `tests/fixtures/maintenance_audit/reviewer-gate-yield.json`
- Create: `tests/fixtures/maintenance_audit/human-gate-yield.json`
- Create: `tests/fixtures/maintenance_audit/source-unavailable.json`
- Create: `tests/fixtures/maintenance_audit/semantic-projection-suspected.json`
- Create: `tests/fixtures/maintenance_audit/future-spec-intentionally-open.json`
- Create: `tests/fixtures/maintenance_audit/search-hint-disagrees-with-exact.json`
- Create: `docs/spec/schemas/maintenance-audit-report.v1.schema.json`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Produces `MAINTENANCE_REPORT_SCHEMA = "maintenance-audit-report.v1"`.
- Produces immutable `EvidenceRef(ref: str, revision: str)`.
- Produces immutable `MaintenanceReport(repository: str, control_ref: str, observed_at: str, evidence: tuple[EvidenceRef, ...], disposition: str, reason_codes: tuple[str, ...], finding: str | None, owner_class: str, transition: str | None, recheck_trigger: str | None, report_id: str)`.
- Produces `evaluate_observation(observation: Mapping[str, object]) -> MaintenanceReport`.
- Produces `report_to_dict(report: MaintenanceReport) -> dict[str, object]` matching `maintenance-audit-report.v1.schema.json`.
- Logical `report_id` is SHA-256 over repository/control identity + sorted evidence `(ref, revision)` + finding + transition; `observed_at` is excluded.

- [ ] **Step 1: Write failing fixture-driven tests**

Tests must pin these outcomes:
- exact terminal owner + stale Control Active Work -> `AUTO_ADVANCE`, finding `CONTROL_ACTIVE_WORK_TERMINAL`, transition `SYNC_CONTROL_ROUTING`;
- exact terminal Next Action target -> `AUTO_ADVANCE`, finding `STALE_NEXT_ACTION_TARGET`, transition `SYNC_CONTROL_ROUTING`;
- trusted active producer -> `NO_ACTION`, finding `ACTIVE_PRODUCER_YIELD`, no transition;
- missing different reviewer -> `NEEDS_REVIEWER`, finding `REVIEW_GATE_YIELD`;
- explicit Human/security/device gate -> `NEEDS_HUMAN`, finding `HUMAN_GATE_YIELD`;
- required source failure/duplicate/identity ambiguity -> `NEEDS_EVIDENCE`, finding `SOURCE_UNAVAILABLE_OR_AMBIGUOUS`;
- semantic-only mismatch -> `NEEDS_EVIDENCE`, finding `SEMANTIC_PROJECTION_SUSPECTED`;
- accepted future/spec intentionally open -> `NO_ACTION`, no runnable transition;
- search hint contradicts exact fetch -> classify from exact fetch and retain search only as non-authoritative evidence note;
- same logical evidence with a later observation timestamp -> same `report_id`;
- any authoritative digest/SHA/terminal-state change -> different `report_id`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -W error -m unittest tests.test_maintenance_audit -v`  
Expected: FAIL because `tools.maintenance_audit` and report schema do not exist.

- [ ] **Step 3: Implement the minimal immutable report/evaluator**

Implement only the normalized pure decision layer. No network calls, Issue creation, candidate publication, branch/PR mutation, or prose editing in this module.

- [ ] **Step 4: Add schema-parity tests**

Assert the JSON Schema accepts every `report_to_dict()` output used by fixtures, rejects an unknown disposition/finding shape, and requires non-empty evidence revisions for every authoritative source.

- [ ] **Step 5: Add compile verification and run full suite**

Modify the Required PR gate compile step to include `tools/maintenance_audit.py`.

Run: `python -W error -m unittest tests.test_maintenance_audit -v`  
Expected: PASS.

Run: `python -W error -m unittest discover -v`  
Expected: PASS with zero failures/errors.

- [ ] **Step 6: Commit and review S2.2 audit-core slice**

Commit message: `feat: add deterministic maintenance audit core (#<S2.2-owner>)`.

Open one bounded S2.2 PR, require exact-head Required PR gate + Formal Review, merge only after current gates pass, then post-main verify and reconcile `#232/#215/#16` before the next task.

### Task 2: S2.2 exact GitHub collector and read-only CLI

**Files:**
- Create: `tools/maintenance_audit_github.py`
- Create: `scripts/maintenance_audit.py`
- Create: `tests/test_maintenance_audit_github.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Produces `GitHubReadTransport` protocol with `get_json(url: str) -> object`.
- Produces `collect_repository(transport: GitHubReadTransport, control_ref: str, observed_at: str) -> dict[str, object]` returning the exact normalized observation consumed by `evaluate_observation()`.
- Produces `collect_portfolio(transport: GitHubReadTransport, control_refs: Sequence[str], observed_at: str) -> tuple[dict[str, object], ...]`.
- CLI: `python scripts/maintenance_audit.py audit [--control kinoko34077/devflow#N ...] [--json-out PATH]`.
- CLI reads a pre-existing `GITHUB_TOKEN` environment variable; absence is a fail-closed configuration error. It never logs the token value.

- [ ] **Step 1: Write failing collector tests with a fake transport**

Cover exact Repository Control read; exact owner Issue read; exact PR state/head read when referenced; exact default-branch SHA read; trusted Session evidence only when explicitly referenced; source failure preserved; duplicate Control/owner ambiguity preserved; search results never used as final authority.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -W error -m unittest tests.test_maintenance_audit_github -v`  
Expected: FAIL because collector/CLI do not exist.

- [ ] **Step 3: Implement read-only collection**

Use standard-library HTTP only. Preserve exact URLs/IDs/SHA/body digests as revisions. Discovery endpoints may enumerate managed Controls, but every fact consumed by `maintenance_audit` must come from an exact object read.

- [ ] **Step 4: Add CLI tests**

Assert `audit` writes deterministic JSON sorted by repository; missing token exits non-zero without network mutation; `--json-out` output contains only report data and no credential material.

- [ ] **Step 5: Run focused/full tests and compile**

Run both maintenance audit test modules, then `python -W error -m unittest discover -v` and `python -m py_compile tools/maintenance_audit.py tools/maintenance_audit_github.py scripts/maintenance_audit.py`.

- [ ] **Step 6: Commit and accept the S2.2 collector slice**

Commit message: `feat: collect exact maintenance audit evidence (#<S2.2-owner>)`.

Do not add scheduled execution yet. Merge/reconcile S2.2 before S2.3 begins.

### Task 3: S2.3 deterministic triage without task inflation

**Files:**
- Create: `tools/maintenance_triage.py`
- Create: `tests/test_maintenance_triage.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Produces immutable `TriageDecision(report_id: str, disposition: str, route: str, work_class: str | None, action: str | None, task_ref: str | None, reason_codes: tuple[str, ...])`.
- Allowed internal `route` values are diagnostic routing only: `NOOP`, `TRACK_ONLY`, `SYNC_CHECK`, `PUBLISH_EXISTING_OWNER`.
- Produces `triage_report(report: MaintenanceReport, *, existing_owner_ref: str | None) -> TriageDecision`.

- [ ] **Step 1: Write failing routing tests**

Assert:
- clean / intentional future-spec / active producer -> `NOOP`, no work class;
- reviewer/Human/external gate -> existing disposition preserved, `NOOP`, no maintenance candidate;
- source unavailable or semantic-only ambiguity -> `TRACK_ONLY`; only when an existing eligible owner is supplied may it become `PUBLISH_EXISTING_OWNER` with `work_class="triage"`;
- deterministic stale projection -> `SYNC_CHECK`, `work_class="sync-check"`, action `RECONCILE_STALE_PROJECTION`;
- `NEEDS_RECOVERY` is not converted into maintenance implementation supply; it remains on the existing recovery publication path;
- missing `existing_owner_ref` never causes Issue creation or a synthetic candidate.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -W error -m unittest tests.test_maintenance_triage -v`.

- [ ] **Step 3: Implement the pure triage mapper**

No GitHub I/O and no new disposition vocabulary. Treat `route` as an implementation routing detail, never durable task state.

- [ ] **Step 4: Add no-inflation regression tests from #249**

Include representative clean WAIT, active producer, different-reviewer gate, Human/device gate, and historical/accepted future-spec cases; all must emit no candidate.

- [ ] **Step 5: Run full regression and accept S2.3**

Add `tools/maintenance_triage.py` to compile verification, run full tests, open the bounded S2.3 PR, complete exact-head review/merge/post-main reconciliation before S2.4.

### Task 4: S2.4 bounded sync-check plan with guarded no-op-by-default execution

**Files:**
- Create: `tools/maintenance_sync_check.py`
- Create: `tests/test_maintenance_sync_check.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Produces immutable `SyncCheckPlan(report_id: str, repository: str, control_ref: str, finding: str, transition: str, expected_evidence: tuple[EvidenceRef, ...], task_ref: str | None)`.
- Produces `plan_sync_check(report: MaintenanceReport, decision: TriageDecision) -> SyncCheckPlan | None`.
- Produces `verify_sync_preconditions(plan: SyncCheckPlan, current: MaintenanceReport) -> str` with exact outcomes `MATCH`, `CHANGED`, `NO_LONGER_ACTIONABLE`.

- [ ] **Step 1: Write RED planning/guard tests**

Only `CONTROL_ACTIVE_WORK_TERMINAL` and `STALE_NEXT_ACTION_TARGET` may produce the initial `SYNC_CONTROL_ROUTING` plan. Human/reviewer/external/producer/semantic/source-unavailable cases return `None`.

- [ ] **Step 2: Write RED freshness tests**

Same report identity/evidence -> `MATCH`; any authoritative SHA/digest/owner/Control change -> `CHANGED`; a now-clean state -> `NO_LONGER_ACTIONABLE`.

- [ ] **Step 3: Implement planning and guard only**

The initial S2.4 implementation MUST NOT rewrite free-form Control prose automatically. It prepares a bounded sync-check request for a later authorized worker and proves the immediate re-observation/identity guard. If a concrete machine-owned projection with a separately accepted safe write contract is selected during S2.4 review, add that write in a new bounded child rather than broadening this task silently.

- [ ] **Step 4: Run full tests and accept S2.4**

Compile/test/review/merge/post-main reconciliation as an independent slice. Record in `#232` whether direct durable mutation remains `NOT_NEEDED` for Stage-2 v1 because supply handoff is sufficient.

### Task 5: S2.5 existing-authority maintenance supply projection

**Files:**
- Create: `tools/maintenance_supply.py`
- Create: `tests/test_maintenance_supply.py`
- Modify only if required for an already-accepted candidate schema parity test: `docs/spec/schemas/chat-worker-bootstrap-evidence.v1.schema.json`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Produces `build_maintenance_candidate(decision: TriageDecision, report: MaintenanceReport, *, task_body_sha256: str, rank_key: Sequence[int | str]) -> dict[str, object] | None`.
- Produces `reconcile_maintenance_candidates(existing: Sequence[Mapping[str, object]], *, task_ref: str, desired: Mapping[str, object] | None) -> dict[str, object]` with `active` and `superseded_fingerprints`.
- Candidate output reuses the accepted fields consumed by Chat Worker Bootstrap: `task_ref`, `role="implementer"`, `action`, optional `work_class` (`triage` or `sync-check`), `fingerprint`, `digest_fresh`, `dependency_ready`, `human_gate`, `external_blocker`, `reviewer_independence_conflict`, `published_by_this_attempt`, `claimability`, `rank_key`, `required_capabilities`, `required_environment`.

- [ ] **Step 1: Write RED candidate tests**

Assert stable fingerprint for unchanged logical report/task digest; different evidence/body digest changes fingerprint; only `triage`/`sync-check` routes create candidates; role is always `implementer`; no candidate is built without an existing owner `task_ref`; Human/reviewer/recovery/no-op cases produce `None`.

- [ ] **Step 2: Write RED 3C/retirement tests**

New publication is marked `published_by_this_attempt=True` in the producing attempt; unchanged desired candidate dedupes; changed fingerprint supersedes prior maintenance candidate for that owner; resolved/non-actionable finding withdraws it; unrelated candidates are preserved.

- [ ] **Step 3: Implement minimal builder/reconciler**

Do not create an Issue, choose a provider, claim work, or invent a second queue. The caller is responsible for writing the accepted Repository Control candidate projection through the existing #125 authority path and for setting `published_by_this_attempt=False` only in a later fresh consumer observation.

- [ ] **Step 4: Add compatibility test through `chat_worker_bootstrap.classify()`**

Construct an exact Stage-2 candidate and prove a maintenance-only request accepts the matching `triage`/`sync-check` class while unrelated implementation/formal-review work is omitted. Contradictory role/work-class evidence must still fail closed under accepted S1.12 behavior.

- [ ] **Step 5: Run full regression and accept S2.5**

No `execution-coordinator` repository change is created unless the accepted consumer actually lacks a required field/behavior. If such a concrete gap appears, stop and create a separate repository-local owner there rather than extending this devflow task across repositories implicitly.

### Task 6: S2.6 real GitHub Actions pilot, S2.7 verification/review, S2.8 acceptance

**Files:**
- Create: `.github/workflows/maintenance-audit.yml`
- Create: `tests/test_maintenance_audit_workflow.py`
- Modify: `scripts/maintenance_audit.py`
- Update durable GitHub progress: the active Stage-2 owner, `devflow#232`, `devflow#215`, Control #16, and `devflow#249` only where their current summary materially changes.

**Interfaces:**
- Workflow manual entry: `workflow_dispatch` with `mode = audit | publish` and optional repeated/encoded Control target input; default `audit`.
- Workflow credential input: pre-existing repository secret `MAINTENANCE_AUDIT_TOKEN` mapped to `GITHUB_TOKEN`; workflow never creates/prints/rotates the value.
- `audit` mode: exact reads -> reports -> Actions Summary + JSON artifact only.
- `publish` mode: same reads/triage plus candidate projection update only for decisions already accepted by S2.5; it performs no runtime claim and cannot consume its new candidate in that run.

- [ ] **Step 1: Write RED workflow-structure tests**

Assert `workflow_dispatch` exists; default mode is read-only `audit`; permissions are least privilege; no `pull_request_target`; no shell echo of token; no Issue/PR mutation step in `audit`; `publish` is separately gated; no schedule yet.

- [ ] **Step 2: Implement manual workflow and JSON/summary output**

Use the CLI from Task 2. Missing credential or unreadable required source must fail closed and produce no publication.

- [ ] **Step 3: Run a bounded real audit pilot**

Exercise at least three live classes from exact evidence:
1. one clean/intentional WAIT repository;
2. one active producer or reviewer/Human-gated repository that must yield;
3. one known/safely staged stale projection fixture or live finding that reaches deterministic triage without semantic guessing.

Compare Action output against a fresh manual #249-style exact-read audit. Any disagreement blocks acceptance and becomes a bounded bug/fix under the Stage-2 owner.

- [ ] **Step 4: Run one bounded publish/withdraw lifecycle if real eligible demand exists**

Publish only an existing-owner maintenance candidate, confirm a separate later read sees it, prove the producing attempt cannot consume it, then resolve/withdraw it when owner/freshness/readiness changes. If no real eligible demand exists, record `NO_REAL_DEMAND` rather than manufacturing one.

- [ ] **Step 5: Exact-head verification and Formal Review**

Run `python -W error -m unittest discover -v`, compile all new modules/scripts, Required PR gate, and current-head Formal Review. Require different-system/model review if the final PR changes shared source-of-truth/automation semantics under current #111 policy.

- [ ] **Step 6: Merge/post-main verification and Stage-2 acceptance**

Merge only after current gates are satisfied; run post-main verify; reconcile owner/#232/#215/#16/#249. Mark S2.8 accepted only when audit/triage/sync-check/supply boundaries are proven, no synthetic work remains, and runtime claims remain clean.

- [ ] **Step 7: Enable recurring schedule only after operational credential/pilot readiness is explicit**

Add the schedule in a separate bounded follow-up change after the real manual pilot is accepted and a read-capable credential is configured by the user. The scheduled mode defaults to `audit`; autonomous `publish` on schedule requires its own accepted evidence and must preserve all Human/security/reviewer gates.

## PR / ownership split

Use one bounded owner/PR per accepted Stage-2 unit rather than one long branch:

1. S2.2 audit core + exact collector (Tasks 1-2; split into two PRs only if review finds the I/O boundary independently rejectable).
2. S2.3 deterministic triage (Task 3).
3. S2.4 guarded sync-check planning (Task 4).
4. S2.5 maintenance supply integration (Task 5).
5. S2.6/7 Actions pilot + verification (Task 6).
6. S2.8 is acceptance/reconciliation, not a feature PR by itself unless reconciliation exposes a concrete defect.

Every slice updates `devflow#232` before entering the next materially distinct unit. `devflow#249` remains a broad backstop/regression source, not the runtime log sink for every clean Actions run.
