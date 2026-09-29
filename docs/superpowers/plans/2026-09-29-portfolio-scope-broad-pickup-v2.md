# Portfolio-scope Broad Pickup v2 Implementation Plan

> **For agents:** Execute task-by-task with TDD and checkpoint each durable milestone on devflow#208.

**Goal:** Accept portfolio-scope broad pickup (`target_repository = null`) without weakening repository-scoped v1, using explicit fresh scheduling metadata and exact worker requirements to select at most one cross-repository candidate.

**Architecture:** Keep `DEVFLOW_EXECUTION_CANDIDATES_V1` as the admission/freshness authority. Add a separate `DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1` Control block whose role records are bound to the existing candidate by `task`, `role`, `task_body_sha256`, and `candidate_fingerprint`. The block carries only scheduling metadata (urgency/dependency/readiness/ready_at), exact capability/environment requirements, and an explicit freshness window. Live Control `Priority` remains canonical and is read directly rather than duplicated. Repository-scoped chat bootstrap remains v1-compatible; portfolio classification uses the already-reserved null target, full managed frontier evidence, Control-specific hard gates, rank-class ordering, and worker-scoped deterministic rotation. Runtime claim/ack remains execution-coordinator authority.

**Tech Stack:** Python stdlib/unittest, JSON Schema documents, Markdown specifications, execution-coordinator Python package, GitHub Issues/PRs/Actions.

---

### Task 1: Accept the devflow portfolio metadata + selection contract

**Files:**
- Create: `docs/spec/PORTFOLIO_PICKUP_V2.md`
- Create: `docs/spec/schemas/execution-portfolio-metadata.v1.schema.json`
- Modify: `docs/spec/CHAT_WORKER_BOOTSTRAP.md`
- Modify: `tests/test_chat_worker_bootstrap.py`

**Contract decisions:**
- Existing `DEVFLOW_EXECUTION_CANDIDATES_V1` stays byte/semantic compatible; unknown fields remain rejected there.
- A Control may opt into portfolio scheduling with exactly one companion block:
  `DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN/END`.
- Each metadata record identifies exactly one existing `(task, role)` and includes its `task_body_sha256` plus current `candidate_fingerprint`.
- Record fields: `task`, `role`, `task_body_sha256`, `candidate_fingerprint`, `controller_urgency`, `dependency_ready`, `dependency_order`, `readiness_class`, `ready_at`, `required_capabilities`, `required_environment`, `observed_at`, `fresh_until`.
- Control priority is read from the exact live trusted Control; it is not duplicated in the companion record.
- Missing/duplicate/stale/mismatched companion evidence makes the portfolio frontier incomplete; portfolio selection fails closed instead of using the repo-scoped fallback.
- Recovery demand remains a separate track and is never converted to ordinary ranked fresh work.
- Worker spread uses `(coordinator_worker_id, task_ref, execution_attempt_id)` only after hard filters and rank-class selection.

**TDD:** Add tests first for portfolio selection, rank-class spread/order independence, Control hard gates, repo-scoped regression, and schema/marker contract. Run focused tests and observe failures caused by reserved portfolio behavior/missing schema.

### Task 2: Implement devflow reference classifier portfolio semantics

**Files:**
- Modify: `tools/chat_worker_bootstrap.py`
- Modify: `docs/spec/CHAT_WORKER_BOOTSTRAP.md`
- Modify: schema/spec artifacts from Task 1 as required by tests.

**Behavior:**
- Preserve the exact existing repository-scoped path.
- For null target: require `agents_md_read`, complete frontier and coordinator state; map each candidate repository to exactly one trusted open Control; apply repository state/Human/external gates per candidate; apply existing candidate hard filters; choose recovery/reviewer/implementer track; choose minimum rank class; rotate deterministically inside that class by SHA-256; submit/result-bind at most one candidate.
- Do not infer rank or requirements from prose/provider identity.

**Verification:** focused bootstrap tests, then full devflow suite and `git diff --check`.

### Task 3: Accept devflow PR before runtime consumption

- Commit the plan/contract/classifier/tests on `chatgpt/df208-portfolio-v2-recovery`.
- Push and open a devflow PR referencing #208.
- Run exact-head CI and Formal Review under current review policy.
- Merge only if verified/review-clean and no new hard gate appears; post-merge verify current main.
- Reconcile #208 checkpoint. Do not publish/consume scheduling metadata before the contract is accepted.

### Task 4: Implement execution-coordinator portfolio evidence/runtime

**Files (expected, exact set after live current-main read):**
- `src/execution_coordinator/discovery.py` or new bounded metadata parser module
- `src/execution_coordinator/bootstrap_pickup.py`
- `src/execution_coordinator/ranking.py` / `capability.py` only if a tested helper is needed
- corresponding tests

**TDD:**
- RED: companion metadata parser rejects duplicate/malformed/stale/source/body/fingerprint mismatch.
- RED: portfolio gather fails closed without complete metadata, emits explicit rank/requirements when complete, preserves recovery separation and claim-conflict omission.
- RED: CLI accepts portfolio scope without changing repository-scoped behavior; one rejected claim ends cycle.
- GREEN minimally; full suite/static/compile/diff checks.

Open/verify/review/merge execution-coordinator PR only after devflow contract is accepted. Reconcile devflow Control #107 after accepted main advances.

### Task 5: Publish live metadata then run bounded Stage 3 in a separate attempt

- Publish metadata only for current live candidate lanes using exact current task-body digests/fingerprints and explicit empty/non-empty requirement arrays; do not manufacture work.
- Verify an independent read sees a complete cross-repository frontier over at least two repositories.
- End/release the publishing attempt (3C).
- Start a new consumer discovery attempt; select at most one eligible candidate, claim/ack or record the exact rejection, never fall through to candidate 2.
- Release any pilot claim and verify runtime `claims: {}`.
- Reconcile #207/#198/#208 and relevant Controls. Do not bypass different-reviewer, Human, security, publication, credential, permission, release or deploy gates.

### Acceptance trace

This plan closes #208 acceptance by mapping: null target -> portfolio contract; all live Controls -> managed frontier; companion metadata -> explicit ranking/dependency/requirements; Control + record freshness -> fail closed; request identity/attempt -> worker spread; execution-coordinator -> serialized single claim; separate recovery track; separate publication/consumption attempt; exact-head CI/review/post-merge evidence; final claims `{}`.
