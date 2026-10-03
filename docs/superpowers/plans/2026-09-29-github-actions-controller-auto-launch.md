# GitHub Actions Controller Auto-launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one bounded controller-first GitHub Actions path in `kinoko34077/execution-coordinator` that selects at most one accepted managed task, acquires the existing serialized claim, establishes a Claude Code session through GitHub OIDC, acknowledges only after that context exists, performs one bounded implementation cycle, and leaves recoverable GitHub evidence without creating a second authority.

**Architecture:** Keep `devflow` as policy/spec authority and `execution-coordinator` as the sole runtime claim authority. A central `execution-coordinator` workflow performs read-only portfolio ranking, emits one offer, preflights a human-configured cross-repository GitHub App token, checks out the target, validates the launcher profile, claims into `CLAIMED`, creates a tool-less Claude bootstrap session, acknowledges into `RUNNING`, resumes that same Claude session for a bounded file-editing pass, then deterministically commits/pushes/opens a draft PR and releases or fails the claim. Ordinary ChatGPT remains on #190/#202; Codex and event-driven wake remain deferred.

**Tech Stack:** Python 3.11 standard library + existing execution-coordinator modules; GitHub Actions; `actions/checkout`; `actions/create-github-app-token`; Anthropic `claude-code-base-action`; GitHub REST/`gh`; `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-29-github-actions-controller-auto-launch-design.md` (devflow#223 / PR #224)

## Global Constraints

- Adoption remains `PILOT`; this plan does not promote `REQUIRED_FOR_AUTONOMOUS`.
- One controller cycle originates at most one offer and attempts at most one claim; no candidate-2 fallthrough after a claim rejection.
- v1 wake sources are scheduled polling plus manual `workflow_dispatch`; event-driven wake is deferred.
- v1 provider is Claude / Claude Code authenticated with GitHub OIDC Workload Identity Federation; Codex is deferred.
- `execution-coordinator` Issue #3 remains the sole claim/lease/generation/fencing authority.
- Success order is `offer -> ACCEPT -> claim -> CLAIMED -> provider context -> acknowledge -> RUNNING -> work`.
- `LAUNCH_UNAVAILABLE => release`; `LAUNCH_FAILED => fail`; ambiguous launch => `WAITING:PROVIDER`; confirmed live from WAITING uses `resume`, not `acknowledge`.
- Normal offer churn remains Actions-run-local; only significant/recovery-relevant outcomes become durable Issue evidence.
- Human/User/release/deploy/publication/security/credential/session/permission/destructive/shared-history gates remain unchanged.
- Credential, GitHub App, Anthropic federation-rule, service-account and permission setup are Human-gated prerequisites; implementation may consume but never create or broaden them.
- External Actions must be full-SHA pinned. Initial audited pins for the implementation branch: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`, `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97`, `actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1`, `anthropics/claude-code-base-action@dd171826d0197ac293cd459b506790de5119f573`. Re-read those exact commits before merge; changing a pin requires explicit PR evidence, not a floating tag.
- v1 provider work is intentionally bounded to the existing 15-minute lease: the controller job has `timeout-minutes: 12`, no auto-launch lease-renew loop, and no normal path may rely on ownership beyond `lease_until`. Hard runner loss leaves the claim to existing expiry/recovery rather than attempting an unsafe compensating release.
- v1 auto-launch supports `Role.IMPLEMENTER` only. Other roles are omitted before offer with typed evidence and are future bounded extensions.
- Claude's work phase gets repository file tools only (`Read,Glob,Grep,Edit,Write`); it receives no GitHub write token and no Bash/network tool. Git commit/push/PR/comment operations are deterministic workflow steps after Claude returns.
- Cross-repository writes use a separate human-configured GitHub App installation token scoped to the selected target repository; do not reuse or broaden `COORDINATOR_READ_TOKEN`.

## File Structure

### `kinoko34077/execution-coordinator`

- Modify `src/execution_coordinator/execution_request.py` — add the versioned CLAIMED-bound request mode and ambiguous launch outcome without weakening the accepted RUNNING-bound path.
- Modify `src/execution_coordinator/agent.py` — add safe reconstruction of an already-live claim between GitHub Actions steps.
- Create `src/execution_coordinator/portfolio_runtime.py` — extract reusable portfolio ranking/requirements composition from the current chat-bootstrap path.
- Modify `src/execution_coordinator/bootstrap_pickup.py` — delegate portfolio composition to `portfolio_runtime.py`; existing #202 behavior must remain byte-for-byte equivalent at its public result boundary.
- Create `src/execution_coordinator/controller_offer.py` — pure controller offer selection and typed accept/decline/defer contract.
- Create `src/execution_coordinator/auto_launch.py` — claim-only preparation plus launch-outcome/runtime-transition orchestration.
- Create `src/execution_coordinator/actions_controller.py` — GitHub Actions CLI entrypoint, context files, target/preflight/prompt/finalization commands.
- Create `.github/workflows/controller-auto-launch.yml` — scheduled/manual central controller + two-stage Claude session execution.
- Create `tests/test_portfolio_runtime.py`.
- Modify `tests/test_execution_request.py`.
- Modify `tests/test_agent.py`.
- Create `tests/test_controller_offer.py`.
- Create `tests/test_auto_launch.py`.
- Create `tests/test_actions_controller.py`.
- Modify `tests/test_workflow_contract.py`.
- Modify `project/docs/CURRENT_STATE.md` only after the implementation is accepted/merged; task progress stays in the owning Issue/PR.

## Review Focus

1. **Delayed/ambiguous provider bootstrap:** a missing or mismatched Claude `session_id` must never acknowledge or start work; it must reconcile as ambiguous/failed under current claim generation.
2. **Cross-repo credential absence/insufficient permission:** missing GitHub App or Anthropic WIF configuration must stop before claim where knowable and produce `REQUIRES_USER_AUTHORITY`; no fallback to broader tokens.
3. **Overlapping schedule + manual wake:** two cycles selecting the same task may both offer, but the serialized claim lane must produce at most one owner and the loser must not fall through to another candidate.
4. **Hard runner death / timeout:** because the job may disappear before terminal cleanup, no design may assume `finally` always runs; the remaining claim must be safely recoverable by normal lease expiry/fencing.
5. **Untrusted or stale task evidence:** an offer generated from stale candidate/source/fingerprint or a target that changes before claim must fail closed before repository mutation, even if the target checkout/provider are otherwise available.

---

### Task 1: Version the CLAIMED-bound ExecutionRequest contract

**Files:**
- Modify: `src/execution_coordinator/execution_request.py`
- Modify: `tests/test_execution_request.py`

**Interfaces:**
- Consumes: existing `CapabilityMatch`, `ClaimAuthority`, `BootstrapContext`, `DispatchOutcome`, `WorkerDispatchAdapter`.
- Produces: `AUTO_LAUNCH_EXECUTION_REQUEST_SCHEMA_VERSION = "execution-request.autolaunch.v1"`; `build_auto_launch_execution_request(match, authority, bootstrap, *, request_id, now) -> ExecutionRequest`; `LaunchStatus.AMBIGUOUS`; `DispatchOutcome.ambiguous(...)`.

- [ ] **Step 1: Write failing tests for dual request modes**

Add tests asserting:
- existing `build_execution_request(...)` still requires `ExecutionState.RUNNING`;
- `build_auto_launch_execution_request(...)` requires `ExecutionState.CLAIMED`;
- both modes preserve exact task/role/worker/fingerprint/source/freshness/capability/environment binding;
- a stale auto-launch request is rejected by `dispatch_execution_request`.

- [ ] **Step 2: Run the focused request tests and verify failure**

Run: `python -m unittest tests.test_execution_request -v`
Expected: FAIL because the auto-launch schema/builder does not exist.

- [ ] **Step 3: Implement the minimum versioned request extension**

Change `ClaimAuthority` validation so it can represent `CLAIMED` or `RUNNING`, but enforce the legal state/schema pair inside request construction/validation:
- `execution-request.v1` => `RUNNING` only;
- `execution-request.autolaunch.v1` => `CLAIMED` only.

Do not relax the existing `build_execution_request` contract.

- [ ] **Step 4: Add failing tests for ambiguous provider results**

Assert `DispatchOutcome.ambiguous(request_id=..., reason=...)`:
- has status `LAUNCH_AMBIGUOUS`;
- carries no worker/session identity;
- carries explicit reconciliation evidence;
- cannot be confused with accepted/unavailable/failed.

- [ ] **Step 5: Implement ambiguous outcome support and rerun tests**

Run: `python -m unittest tests.test_execution_request -v`
Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/execution_coordinator/execution_request.py tests/test_execution_request.py
git commit -m "feat: add claimed-bound auto-launch request contract"
```

### Task 2: Extract reusable portfolio runtime composition

**Files:**
- Create: `src/execution_coordinator/portfolio_runtime.py`
- Modify: `src/execution_coordinator/bootstrap_pickup.py`
- Create: `tests/test_portfolio_runtime.py`
- Modify: `tests/test_bootstrap_pickup.py`

**Interfaces:**
- Consumes: `enumerate_managed_frontier`, `parse_portfolio_metadata`, `rank_managed_frontier`, `CandidateRequirements`, current trusted Control snapshots.
- Produces: `PortfolioRuntimeRead`; `read_portfolio_runtime(control_documents, *, issue_reader, state_reader, worker_id, now) -> PortfolioRuntimeRead` with exact `frontier`, `ranked`, `requirements`, and omission/failure evidence; no claim or provider behavior.

- [ ] **Step 1: Write failing tests for complete and incomplete portfolio composition**

Cover:
- complete companion metadata yields the same ranked ordinary candidates and exact `CandidateRequirements` currently serialized by `gather_evidence`;
- missing/duplicate/stale metadata fails closed;
- recovery candidates remain separate;
- read is GET-only and creates no claim.

- [ ] **Step 2: Run focused portfolio tests and verify failure**

Run: `python -m unittest tests.test_portfolio_runtime -v`
Expected: FAIL because `portfolio_runtime.py` does not exist.

- [ ] **Step 3: Implement `PortfolioRuntimeRead` and `read_portfolio_runtime(...)` by moving, not duplicating, the existing portfolio composition logic**

Keep candidate ranking/source/freshness semantics owned by the existing modules. This file only composes them.

- [ ] **Step 4: Refactor `bootstrap_pickup.gather_evidence` portfolio scope to serialize the new reusable result**

Do not change repository-scoped v1 behavior or public classifier evidence fields.

- [ ] **Step 5: Run regression tests**

Run: `python -m unittest tests.test_portfolio_runtime tests.test_bootstrap_pickup tests.test_portfolio_metadata tests.test_ranking tests.test_capability -v`
Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/execution_coordinator/portfolio_runtime.py src/execution_coordinator/bootstrap_pickup.py tests/test_portfolio_runtime.py tests/test_bootstrap_pickup.py
git commit -m "refactor: expose reusable portfolio runtime read"
```

### Task 3: Add pure controller-offer negotiation

**Files:**
- Create: `src/execution_coordinator/controller_offer.py`
- Create: `tests/test_controller_offer.py`

**Interfaces:**
- Consumes: `PortfolioRuntimeRead`, `CandidateRequirements`, `WorkerProfile`, `match_ranked_frontier`, `Role`.
- Produces:
  - `CONTROLLER_OFFER_SCHEMA_VERSION = "controller-offer.v1"`;
  - `ControllerOffer` bound to task, role, candidate fingerprint/source, priority/rank evidence, required capabilities/environment and risk/authority fields available from accepted evidence;
  - `OfferResponseCode` using Protocol v1 values `ACCEPTED`, `DECLINED_CAPABILITY`, `DECLINED_CONFLICT`, `DEFERRED_BUSY`, `BLOCKED_DEPENDENCY`, `REQUIRES_USER_AUTHORITY`;
  - `select_controller_offer(read, *, supported_roles=frozenset({Role.IMPLEMENTER})) -> ControllerOffer | None`;
  - `evaluate_controller_offer(offer, worker_profile, *, current_read, provider_ready, human_gate) -> tuple[OfferResponseCode, CapabilityMatch | None]`.

- [ ] **Step 1: Write failing selection tests**

Assert:
- only the first deterministic ranked `IMPLEMENTER` candidate becomes an offer;
- unsupported roles are omissions, not claim attempts;
- no eligible ordinary candidate returns `None`;
- selection performs no mutation.

- [ ] **Step 2: Write failing response/revalidation tests**

Assert:
- exact capability/environment match returns `ACCEPTED` plus exactly one `CapabilityMatch`;
- stale fingerprint/source, dependency change, live conflict or Human Gate cannot return `ACCEPTED`;
- missing provider/Human configuration returns `REQUIRES_USER_AUTHORITY` where human setup is required;
- capability mismatch returns `DECLINED_CAPABILITY`;
- no response creates claim authority.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `python -m unittest tests.test_controller_offer -v`
Expected: FAIL because controller offer types/functions do not exist.

- [ ] **Step 4: Implement the pure offer module using existing ranking/matching functions rather than reimplementing policy**

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_controller_offer -v`
Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/execution_coordinator/controller_offer.py tests/test_controller_offer.py
git commit -m "feat: add controller offer negotiation"
```

### Task 4: Implement claim-only auto-launch lifecycle and safe step reattachment

**Files:**
- Modify: `src/execution_coordinator/agent.py`
- Create: `src/execution_coordinator/auto_launch.py`
- Modify: `tests/test_agent.py`
- Create: `tests/test_auto_launch.py`

**Interfaces:**
- Consumes: `AgentSession`, `GitHubStateStore`/validated `CoordinatorState`, `CapabilityMatch`, `ExecutionRequest`, `DispatchOutcome`, `WaitReason.PROVIDER`.
- Produces:
  - `AgentSession.from_current_claim(gateway, claim, *, expected_task, expected_role, expected_worker_id) -> AgentSession`;
  - `AutoLaunchKeys` with deterministic operation keys;
  - `ClaimedAutoLaunch` serializable context containing attempt/task/role/worker/claim/generation/request/candidate identity;
  - `claim_for_auto_launch(match, gateway, bootstrap, *, request_id, keys, now) -> tuple[ClaimedAutoLaunch, ExecutionRequest]`;
  - `apply_launch_outcome(context, outcome, *, gateway, current_state, keys, evidence_ref) -> AutoLaunchTransition`;
  - `resume_confirmed_provider(context, *, gateway, current_state, keys) -> AutoLaunchTransition`.

- [ ] **Step 1: Write failing tests for `AgentSession.from_current_claim`**

Require exact task/role/worker/claim/generation matching and a live unexpired claim. Reject stale/mismatched snapshots before any mutation.

- [ ] **Step 2: Implement safe reattachment and run `tests.test_agent`**

Run: `python -m unittest tests.test_agent -v`
Expected: PASS.

- [ ] **Step 3: Write failing lifecycle tests**

Prove:
- claim-only preparation leaves `CLAIMED` and builds the auto-launch request without acknowledge;
- ACCEPTED bootstrap with matching provider session => `acknowledge -> RUNNING`;
- UNAVAILABLE => `release` and no live claim;
- FAILED => `fail` and no live claim;
- AMBIGUOUS => `wait(PROVIDER)` and claim remains lease-bound;
- confirmed-live ambiguous state uses `resume`, not `acknowledge`;
- stale generation between provider return and transition is fenced;
- two racing preparations produce at most one claim and the loser does not try candidate 2.

- [ ] **Step 4: Run focused lifecycle tests and verify failure**

Run: `python -m unittest tests.test_auto_launch -v`
Expected: FAIL because `auto_launch.py` does not exist.

- [ ] **Step 5: Implement the lifecycle module using `AgentSession` operations for every authority mutation**

No provider code belongs here.

- [ ] **Step 6: Run lifecycle + engine regression tests**

Run: `python -m unittest tests.test_auto_launch tests.test_agent tests.test_engine tests.test_agent_wait_resume_transport tests.test_agent_transport_fencing -v`
Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/execution_coordinator/agent.py src/execution_coordinator/auto_launch.py tests/test_agent.py tests/test_auto_launch.py
git commit -m "feat: orchestrate claimed auto-launch lifecycle"
```

### Task 5: Add the Actions-side controller command and deterministic target handoff

**Files:**
- Create: `src/execution_coordinator/actions_controller.py`
- Create: `tests/test_actions_controller.py`

**Interfaces:**
- Consumes: Tasks 1-4, existing GitHub readers/state gateway, devflow checkout, accepted Control/Issue evidence.
- Produces CLI subcommands:
  - `prepare-offer` — read portfolio, create at most one `ControllerOffer`, write `offer.json`, emit `target_repository`, `target_issue`, `has_offer`;
  - `accept-and-claim` — after target checkout/preflight, build observed `WorkerProfile`, re-read/revalidate offer, claim only, write `launch-context.json` and `execution-request.json`, emit intended Claude UUID/worker identity;
  - `reconcile-bootstrap` — classify Claude bootstrap outputs and apply ACCEPTED/FAILED/AMBIGUOUS transition;
  - `finalize-work` — on RUNNING work completion/failure, create bounded task evidence and terminal `release`/`fail` decision without marking the durable Issue complete itself.

- [ ] **Step 1: Write failing CLI/service tests with fake readers/gateway/filesystem**

Cover Review Focus 1-5, plus:
- no offer => exit 0/no mutation;
- target repo is derived only from the selected exact task reference;
- stale offer between `prepare-offer` and `accept-and-claim` => no claim;
- missing GitHub App/WIF preflight marker => `REQUIRES_USER_AUTHORITY`, no claim;
- generated provider session ID is UUID-shaped and bound into worker/request identity;
- prompt file includes owning task scope/acceptance, exact claim/generation/base SHA/branch, and explicit prohibitions on push/PR/release/deploy/credential changes;
- provider work prompt never contains secrets/tokens.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m unittest tests.test_actions_controller -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement `prepare-offer` and `accept-and-claim`**

Use one context directory (default `.controller-auto-launch/`) containing only non-secret JSON/text. Derive branch name deterministically as `agent/controller-<issue-number>-<attempt8>` and pin the target base SHA before claim.

- [ ] **Step 4: Implement `reconcile-bootstrap` and `finalize-work`**

Provider bootstrap classification rules:
- success + exact expected `session_id` => ACCEPTED;
- explicit terminal execution record proving the expected session ended before work => FAILED;
- missing/mismatched/uncertain session evidence => AMBIGUOUS;
- known configuration unavailable before provider invocation should have been caught pre-claim; if it occurs after claim, map to UNAVAILABLE only when evidence proves no provider session started.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_actions_controller -v`
Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/execution_coordinator/actions_controller.py tests/test_actions_controller.py
git commit -m "feat: add Actions controller command surface"
```

### Task 6: Add the bounded central GitHub Actions + Claude OIDC workflow

**Files:**
- Create: `.github/workflows/controller-auto-launch.yml`
- Modify: `tests/test_workflow_contract.py`

**Interfaces:**
- Consumes: `actions_controller` CLI; human-configured GitHub App + Anthropic WIF variables; exact target repository from `offer.json`.
- Produces: schedule/manual controller cycle; scoped target checkout; two-stage Claude context/work execution; deterministic push/draft-PR/Issue evidence; terminal runtime transition.

- [ ] **Step 1: Write failing workflow-contract tests**

Assert the workflow contains:
- `schedule` and `workflow_dispatch`, and no event-driven wake;
- `timeout-minutes: 12` on the single controller job;
- `concurrency` with `cancel-in-progress: false`;
- minimum central permissions including `contents: read`, `actions: write`, `id-token: write`;
- all external Actions pinned to the exact SHAs in Global Constraints;
- target GitHub App token created only after an offer exists and scoped to that target repository with only required permissions (`contents: write`, `pull-requests: write`, `issues: write`);
- target checkout uses the scoped app token with `persist-credentials: false` so Claude never inherits Git credentials;
- Claude WIF uses repository variables `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID` and never accepts a static Anthropic API/OAuth secret in this workflow;
- first Claude step is a tool-less one-turn bootstrap (`--tools ""`, `--max-turns 1`, expected `--session-id`);
- `reconcile-bootstrap` runs before the actual work step;
- actual work step runs only when runtime state is RUNNING and resumes the exact bootstrap session;
- actual work tools are exactly `Read,Glob,Grep,Edit,Write`, with no Bash/network/GitHub token passed to the Claude step;
- deterministic post-work steps, not Claude, handle git commit/push/draft PR/Issue comment;
- cleanup/finalization uses `if: always()` where GitHub permits it, but tests do not assume cleanup runs after hard job termination.

- [ ] **Step 2: Run workflow-contract tests and verify failure**

Run: `python -m unittest tests.test_workflow_contract -v`
Expected: FAIL because `controller-auto-launch.yml` does not exist.

- [ ] **Step 3: Implement the workflow through claim + tool-less Claude bootstrap**

Human-gated configuration names:
- repository variable `AUTONOMOUS_GITHUB_APP_CLIENT_ID`;
- repository secret `AUTONOMOUS_GITHUB_APP_PRIVATE_KEY`;
- repository variables `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID`.

If any required configuration is absent, terminate before claim and emit the typed Human-gate result.

- [ ] **Step 4: Implement acknowledge + resumed bounded Claude work**

Use the tool-less bootstrap only to establish the expected Claude session. After `reconcile-bootstrap` moves the claim to RUNNING, invoke the same pinned base action again with `--resume <session-id>` and the generated task prompt. Do not expose the target GitHub App token to this step.

- [ ] **Step 5: Implement deterministic target integration**

After successful Claude work:
- inspect the target worktree deterministically;
- if there is a diff, configure bot commit identity, commit, push `agent/controller-...`, open/update one draft PR linked to the owning Issue, and append one concise Issue checkpoint;
- if there is no diff, append bounded evidence and release without inventing completion;
- on provider/work failure after RUNNING, record bounded evidence and `fail` the runtime claim;
- never merge, release or deploy.

- [ ] **Step 6: Run workflow + full regression tests**

Run: `python -m unittest tests.test_workflow_contract tests.test_actions_controller tests.test_auto_launch tests.test_execution_request tests.test_bootstrap_pickup -v`
Expected: PASS.

Run: `python -m unittest discover -s tests -q`
Expected: full suite PASS.

Run: `python -m compileall -q src tests`
Expected: exit 0.

- [ ] **Step 7: Commit Task 6**

```bash
git add .github/workflows/controller-auto-launch.yml tests/test_workflow_contract.py
git commit -m "feat: add bounded Claude auto-launch workflow"
```

### Task 7: Exact-head verification, Human-gated live pilot, and reconciliation

**Files:**
- Modify after acceptance only: `project/docs/CURRENT_STATE.md`
- Update durable evidence: the single repository-local implementation Issue, PR, devflow#223/#188/#105/#107 as their state actually changes.

**Interfaces:**
- Consumes: merged implementation candidate from Tasks 1-6; human-provided GitHub App/WIF configuration.
- Produces: exact-head CI/review evidence, bounded real pilot evidence, clean final runtime, reconciled canonical state.

- [ ] **Step 1: Run exact-head CI and Formal Review on the implementation PR**

Required before merge:
- full `verify` success on exact PR head;
- Formal Review under current devflow policy;
- unresolved blocking findings = 0;
- no credential/permission mutation performed by the worker.

- [ ] **Step 2: Stop at the Human Gate if GitHub App or Anthropic WIF configuration is absent**

Do not create/rotate/store/expand credentials or permissions. Record the exact missing identifiers/permissions on the owning implementation Issue and wait for user-side setup.

- [ ] **Step 3: After Human-approved configuration exists, run one manual `workflow_dispatch` dry/no-work cycle**

Expected:
- no candidate => successful no-op, or incompatible candidate => typed decline/defer;
- no runtime claim leak;
- no target mutation.

- [ ] **Step 4: Run one bounded real implementer pilot against accepted managed candidate supply**

Prove from live evidence:
- at most one offer;
- claim enters CLAIMED before provider bootstrap;
- tool-less Claude bootstrap returns the expected session identity;
- acknowledge happens only after bootstrap success;
- work resumes the same session only after RUNNING;
- deterministic branch/PR evidence is created if there is a diff;
- terminal release/fail leaves no unexplained claim;
- no Human/release/deploy/security boundary is crossed.

- [ ] **Step 5: Run a race pilot using schedule/manual overlap or two manual dispatches**

Expected: exactly one claim owner for the same task/role; the loser stops without candidate-2 fallthrough.

- [ ] **Step 6: Merge only after current authorization and verification; run post-merge Verify**

The change is reversible by normal revert PR. Do not perform release/deploy.

- [ ] **Step 7: Reconcile accepted current state**

Update `project/docs/CURRENT_STATE.md`, devflow Control #107, devflow#223 and #188 only for accepted changes. Re-evaluate parent #105 PARK state against all remaining intentional deferrals; do not change #189 `PILOT`.

- [ ] **Step 8: Commit documentation reconciliation if repository current state changed**

```bash
git add project/docs/CURRENT_STATE.md
git commit -m "docs: record accepted controller auto-launch state"
```

## Self-Review Result

- Spec coverage: D1-D5, ordinary ChatGPT/manual compatibility, Claude OIDC, CLAIMED-before-launch, typed D4 reconciliation, offer durability, Human Gates and PARK-release conditions each map to Tasks 1-7.
- Hidden implementation boundary resolved: central Actions cannot use its ordinary `GITHUB_TOKEN` for arbitrary target-repo writes, so v1 requires a separate Human-configured GitHub App installation token scoped per selected repo. This is a plan-level execution prerequisite, not a new durable authority.
- D3 transport resolved without allowing work before acknowledge: Claude runs a first tool-less one-turn session bootstrap, then the claim is acknowledged, then the same session is resumed for actual work.
- Lease safety resolved for v1 without adding another scheduler/heartbeat subsystem: the whole controller job is bounded to 12 minutes under the existing 15-minute lease. Longer autonomous cycles/renewal are a future bounded extension after pilot evidence.
- Provider tool exposure is bounded: Claude receives file tools only; deterministic GitHub mutations happen outside the provider step with the target-scoped app token.
- Type consistency checked across plan: `ControllerOffer` -> `CapabilityMatch` -> `ClaimedAutoLaunch` -> `ExecutionRequest` -> `DispatchOutcome` -> `AutoLaunchTransition`.
