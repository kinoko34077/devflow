# Repository Bootstrap v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic devflow-owned Issue-triggered repository bootstrap path that turns `repository-bootstrap.v1` requests into initialized repositories, initial Issues, and Repository Controls without embedding an LLM or crossing credential setup gates.

**Architecture:** A pure Python core in `tools/repository_bootstrap.py` parses/validates requests and performs idempotent ensure operations through a narrow GitHub adapter. A thin CLI in `scripts/repository_bootstrap.py` is called by a two-job GitHub Actions workflow where non-secret validation/trust gating precedes the secret-bearing provisioning job. Durable protocol lives in devflow docs/spec/workflow; real credential provisioning/E2E remains Human-gated.

**Tech Stack:** Python 3 stdlib (`json`, `urllib`, `base64`, `argparse`, `dataclasses`), `unittest`, GitHub Actions YAML, GitHub REST API.

**Spec:** `docs/superpowers/specs/2026-09-28-repository-bootstrap-v1-design.md`

## Global Constraints

- No LLM inside the executor.
- Request authority is `[REPO CREATE] <name>`; long-lived state authority is `[REPO] <name>`.
- Missing visibility defaults to `private`; public is never inferred by executor.
- Missing licence remains unset.
- V1 requires only `minimal`; do not force Repository Base.
- Only `OWNER|MEMBER|COLLABORATOR` request authors may reach secret-bearing provisioning.
- External bootstrap credentials are never created/changed by this plan.
- No repository deletion, shared-history rewrite, release, deploy, or publication.
- Retry must be idempotent and conflicts fail closed.

## Review Focus

- Existing same-name repository without matching bootstrap provenance must fail before any overwrite.
- A matching retry after repository creation but before Issues/Control must continue rather than duplicate.
- Untrusted or malformed public Issue events must not make the provisioning job eligible for secrets.
- Existing manually edited repository files must not be silently overwritten on later retries outside bootstrap-owned content rules.
- Duplicate Controls or duplicate request-local Issue markers must fail closed rather than choose arbitrarily.

---

### Task 1: Contract parser, validation and deterministic normalization

**Files:**
- Create: `tools/repository_bootstrap.py`
- Create: `tests/test_repository_bootstrap.py`
- Create: `schemas/repository-bootstrap.v1.schema.json`

**Interfaces:**
- Produces: `parse_request_body(body: str) -> dict`, `normalize_request(raw: dict, issue_title: str) -> BootstrapRequest`, `is_trusted_association(value: str) -> bool`, typed `BootstrapRequest` / `InitialIssue` dataclasses and `BootstrapError`.

- [ ] **Step 1: Write failing tests** for safe defaults, explicit public, unknown schema, title mismatch, invalid enums/name/owner, duplicate Issue keys, invalid control/managed combination, and trusted-author associations.
- [ ] **Step 2: Run the tests and confirm RED** because `tools.repository_bootstrap` does not exist.
- [ ] **Step 3: Implement minimal parser/validator/dataclasses** sufficient for those tests.
- [ ] **Step 4: Run targeted tests and then full unit suite; confirm GREEN.**
- [ ] **Step 5: Add JSON Schema document** matching normalized request fields without adding runtime schema dependency.
- [ ] **Step 6: Commit** `feat: add repository bootstrap v1 contract`.

### Task 2: Idempotent bootstrap planner/executor and bounded GitHub adapter

**Files:**
- Modify: `tools/repository_bootstrap.py`
- Modify: `tests/test_repository_bootstrap.py`

**Interfaces:**
- Consumes: `BootstrapRequest` from Task 1.
- Produces: `BootstrapExecutor(api, devflow_api).execute(context) -> BootstrapResult`, bounded `GitHubApi` methods, provenance/Issue marker rendering, `BootstrapFailure` stage/retry metadata.

- [ ] **Step 1: Write failing tests** with a fake API for new repo creation, matching provenance retry, foreign repo collision, seed creation/no-op behavior, marked Issue reuse, duplicate marker conflict, one Control creation/reuse, duplicate Control conflict, and partial failure result.
- [ ] **Step 2: Run tests and confirm RED** on missing executor behavior.
- [ ] **Step 3: Implement minimal ensure-oriented executor** in the order repository -> provenance -> seed -> head -> Issues -> Control -> terminal result.
- [ ] **Step 4: Implement narrow stdlib GitHub REST adapter** only for required endpoints; never expose arbitrary URL operations.
- [ ] **Step 5: Run targeted + full tests and confirm GREEN.**
- [ ] **Step 6: Commit** `feat: implement idempotent repository bootstrap executor`.

### Task 3: Event CLI and secret-fenced GitHub Actions workflow

**Files:**
- Create: `scripts/repository_bootstrap.py`
- Create: `.github/workflows/repository-bootstrap.yml`
- Create: `tests/test_repository_bootstrap_workflow.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Consumes: GitHub Issues event JSON.
- Produces: `validate-event` outputs `valid`, `authorized`, `repository_name`; `execute-event` uses `DEVFLOW_TOKEN` and `REPOSITORY_BOOTSTRAP_TOKEN` after revalidation.

- [ ] **Step 1: Write failing workflow/CLI tests** proving trusted/untrusted event behavior, exact title/body validation, validation job has no bootstrap secret, provisioning depends on validation+authorization, and bootstrap secret is only referenced by provisioning.
- [ ] **Step 2: Run tests and confirm RED.**
- [ ] **Step 3: Implement CLI validation/execute commands** with fail-closed missing-token behavior.
- [ ] **Step 4: Implement workflow** triggered by `issues: [opened, edited, reopened]`; validation first, provisioning second; devflow `GITHUB_TOKEN` permissions limited to contents read/issues write.
- [ ] **Step 5: Extend required PR gate paths and compile check** to cover bootstrap modules/workflow/docs.
- [ ] **Step 6: Run targeted + full tests and compile checks; confirm GREEN.**
- [ ] **Step 7: Commit** `feat: add trusted issue-triggered repository bootstrap workflow`.

### Task 4: Canonical operations / agent guidance integration

**Files:**
- Create: `docs/operations/REPOSITORY_BOOTSTRAP.md`
- Modify: `AGENTS.md`
- Modify: `.devflow/WORKFLOW.yaml`
- Modify: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
- Add/modify tests if existing policy tests require exact canonical phrases.

**Interfaces:**
- Produces: durable rules telling future agents how to create a request and where the Human credential gate sits.

- [ ] **Step 1: Add any policy tests that fail before docs/workflow changes** where machine-readable behavior is expected.
- [ ] **Step 2: Confirm RED** for missing canonical bootstrap declarations.
- [ ] **Step 3: Write operations doc** with request template, lifecycle, retry/conflict handling, credential setup boundary, and post-bootstrap routing.
- [ ] **Step 4: Update AGENTS/spec/WORKFLOW** so explicit user requests for a new repository route through `repository-bootstrap.v1` when operationally available, while live `[REPO]` Control remains the subsequent entry point.
- [ ] **Step 5: Run full unit suite + compile check and confirm GREEN.**
- [ ] **Step 6: Commit** `docs: integrate repository bootstrap into devflow canon`.

### Task 5: Exact-head review, PR, and reconciliation

**Files:**
- No new product files unless review finds a defect.
- Update Work Order #181 / Repository Control #16 as durable current-state reconciliation requires.

**Interfaces:**
- Consumes: branch exact head and CI/review evidence.
- Produces: reviewed PR and accepted credential-independent state, or a precise blocker.

- [ ] **Step 1: Run fresh full verification** `python -W error -m unittest discover -v` and compile all touched Python entry points.
- [ ] **Step 2: Compare branch against exact base and inspect every changed file.**
- [ ] **Step 3: Open PR linked to #181** with scope, verification, rollback and explicit credential/E2E limitation.
- [ ] **Step 4: Wait for/read exact-head required check evidence; fix only evidence-backed failures via RED->GREEN.**
- [ ] **Step 5: Submit Formal Review** at exact head; address blocking findings once and reverify.
- [ ] **Step 6: Merge only if current devflow policy authorizes this reversible repository-only change and no protected Human Gate is crossed.**
- [ ] **Step 7: Post-merge verify and reconcile #181 / #16.** Credential creation/secret setup and real provisioning E2E remain a named Human Gate if no approved credential exists.
