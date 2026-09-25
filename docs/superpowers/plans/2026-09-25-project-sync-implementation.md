# GitHub Project Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize canonical devflow Issue state into `KiNoTch. Development Control`, expose machine-readable synchronization health, and leave only credential creation/secret registration as the user-admin step.

**Architecture:** A dependency-light Python CLI parses canonical Markdown sections, discovers Project/field/option/item IDs through GitHub GraphQL at runtime, compares canonical state with Project display state, and optionally reconciles drift. A GitHub Actions workflow runs single-Issue event sync and manual verify/reconcile. A dedicated Sync Health Issue stores the latest machine-readable result so normal ChatGPT sessions can inspect Project health indirectly.

**Tech Stack:** Python 3 standard library, GitHub Actions YAML, GitHub REST/GraphQL APIs, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-25-project-sync-design.md`

## Global Constraints

- Authority direction is only `canonical devflow/repository state -> GitHub Project`.
- Never mutate canonical Issue state from Project values.
- Do not commit Project/field/option/item node IDs.
- Project identity is owner `kinoko34077`, Project number `1`.
- Repository secret name is exactly `PROJECTS_TOKEN`; never log or persist its value.
- No periodic schedule in v1.
- No third-party Python runtime dependency unless required by a later explicit decision.
- Sync Health Issue events must not recursively trigger Project synchronization.
- `pc-files` and `pc-files2` remain outside managed scope.

## Review Focus

1. Markdown headings that look similar to canonical headings must not be parsed as canonical state.
2. Project pagination must not silently omit fields/items after the first 100 entries.
3. A missing secret must produce `NOT_CONFIGURED` without attempting Project mutation or leaking credential data.
4. Health Issue edits must be ignored by event-sync to prevent recursive workflow runs.
5. Reconcile must be idempotent and never send mutations for already-matching field values.

---

### Task 1: Core parser and canonical mapping

**Files:**
- Create: `scripts/project_sync.py`
- Create: `tests/test_project_sync.py`

**Interfaces:**
- Produces: `parse_sections(body: str) -> dict[str, str]`
- Produces: `desired_project_fields(issue: dict[str, object]) -> dict[str, str]`
- Produces: `validate_select_values(fields: dict[str, str]) -> list[str]`

- [ ] **Step 1: Write failing parser/mapping tests**

Cover LF/CRLF, exact `##` headings, fenced/backticked scalar values, missing sections, closed Issue `DONE` override, field-name mapping, and invalid select values.

- [ ] **Step 2: Run the focused test module and confirm RED**

Run: `python -m unittest -v tests.test_project_sync`

Expected: import/function failures before implementation.

- [ ] **Step 3: Implement parser and mapping with no network access**

Canonical mapping:

```python
FIELD_MAP = {
    "Work Status": "Status",
    "Repository State": "Repository State",
    "Priority": "Priority",
    "Risk": "Risk",
    "Type": "Work Type",
    "Repository": "Managed Repository",
    "Next Action": "Next Action",
    "Audit SHA": "Audit SHA",
}
```

Closed Issue must force `Status = DONE`. Missing sections remain absent rather than guessed.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 5: Commit Task 1**

Commit message: `feat: add canonical Project sync parser`

### Task 2: GitHub API clients and Project discovery

**Files:**
- Modify: `scripts/project_sync.py`
- Modify: `tests/test_project_sync.py`

**Interfaces:**
- Produces: `GitHubREST(token: str, repository: str)`
- Produces: `GitHubGraphQL(token: str)`
- Produces: `discover_project(owner: str, number: int) -> ProjectSnapshot`
- Produces: pagination helpers for REST Issues and Project fields/items.

- [ ] **Step 1: Add failing tests with fake HTTP transport**

Tests must cover GraphQL errors, exact field matching, duplicate/missing expected fields, duplicate/missing single-select options, and pagination cursors for fields/items.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 3: Implement standard-library HTTP clients and discovery**

Use `urllib.request`; centralize JSON request handling; use GraphQL variables; never embed the token in exceptions or health output.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 5: Commit Task 2**

Commit message: `feat: add GitHub Project discovery client`

### Task 3: Compare, verify, reconcile, and membership

**Files:**
- Modify: `scripts/project_sync.py`
- Modify: `tests/test_project_sync.py`

**Interfaces:**
- Produces: `compare_issue_to_item(...) -> IssueComparison`
- Produces: `plan_mutations(...) -> list[Mutation]`
- Produces: `sync_one_issue(...)`
- Produces: `verify_all(...)`
- Produces: `reconcile_all(...)`

- [ ] **Step 1: Add failing tests for MATCH/DRIFT/NOT_APPLICABLE/ERROR**

Include absent Project membership in verify vs reconcile, closed Issue handling, text/single-select drift, invalid canonical value, and unchanged/idempotent comparison.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 3: Implement comparison and mutation planning**

`verify` never calls mutation methods. Event-sync/reconcile may add missing Project membership with `addProjectV2ItemById` and update only drifted supported fields with `updateProjectV2ItemFieldValue`.

- [ ] **Step 4: Add post-reconcile verification**

Re-read Project state after writes; non-zero exit if blocking drift remains.

- [ ] **Step 5: Run tests and confirm GREEN**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 6: Commit Task 3**

Commit message: `feat: verify and reconcile Project display state`

### Task 4: Health Issue and recursion prevention

**Files:**
- Modify: `scripts/project_sync.py`
- Modify: `tests/test_project_sync.py`

**Interfaces:**
- Produces: `render_health_report(...) -> str`
- Produces: `upsert_health_issue(...)`
- Produces: `is_health_issue(issue: dict[str, object]) -> bool`

- [ ] **Step 1: Add failing tests**

Cover PASS/DEGRADED/FAIL/NOT_CONFIGURED rendering, secret redaction, `CODEX_REQUIRED`, and Health Issue event exclusion.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 3: Implement machine-maintained Health Issue body**

Exact title: `[SYSTEM] GitHub Project Sync Health`. Use GitHub REST Issue API for search/create/update. Ensure Health Issue event returns success without Project sync work.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 5: Commit Task 4**

Commit message: `feat: add Project sync health reporting`

### Task 5: CLI and GitHub Actions workflow

**Files:**
- Modify: `scripts/project_sync.py`
- Create: `.github/workflows/project-sync.yml`
- Modify: `tests/test_project_sync.py`

**Interfaces:**
- CLI modes: `event-sync`, `verify`, `reconcile`
- Environment: `PROJECTS_TOKEN`, `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_EVENT_PATH`, `GITHUB_RUN_ID`, `GITHUB_SERVER_URL`

- [ ] **Step 1: Add failing CLI behavior tests**

Cover missing `PROJECTS_TOKEN`, manual issue-number filtering, event Health Issue skip, and read-only verify dispatch.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 3: Implement CLI entry point**

`GITHUB_TOKEN` may be used only for repository Issue reads/health updates. Project GraphQL reads/writes require `PROJECTS_TOKEN`.

- [ ] **Step 4: Add workflow YAML**

Triggers:

```yaml
on:
  issues:
    types: [opened, edited, reopened, closed]
  workflow_dispatch:
    inputs:
      mode:
        type: choice
        options: [verify, reconcile]
      issue_number:
        required: false
```

Grant `issues: write` and `contents: read`; pass `secrets.PROJECTS_TOKEN` and `${{ github.token }}` through environment only.

- [ ] **Step 5: Validate workflow text and run full tests**

Run: `python -m unittest -v tests.test_project_sync`

Also parse/read the workflow in a test to assert required triggers, secret name, and absence of `schedule:`.

- [ ] **Step 6: Commit Task 5**

Commit message: `feat: automate devflow Project synchronization`

### Task 6: Operational docs and canonical specification

**Files:**
- Create: `docs/project/PROJECT_SYNC.md`
- Modify: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
- Modify: `.devflow/WORKFLOW.yaml`
- Modify: `README.md`

**Interfaces:**
- Documents user-admin secret setup and normal verification path.

- [ ] **Step 1: Document credential setup**

Only user-admin action after merge: create a Project-capable token and store it as repository Actions secret `PROJECTS_TOKEN`. Never document an actual credential value.

- [ ] **Step 2: Document normal verification path**

Normal ChatGPT reads `[SYSTEM] GitHub Project Sync Health`, #16, active Work Order, and Actions evidence. Codex/direct Project inspection is escalation-only after initial rollout acceptance.

- [ ] **Step 3: Update canonical spec/workflow config**

Mark custom-field synchronization as implemented architecture but credential-dependent until live acceptance. Preserve Project display-only authority.

- [ ] **Step 4: Run full tests**

Run: `python -m unittest -v tests.test_project_sync`

- [ ] **Step 5: Commit Task 6**

Commit message: `docs: define Project sync operations`

### Task 7: Pre-live verification, PR, and merge

**Files:**
- No new implementation files unless review fixes are required.

- [ ] **Step 1: Run complete local verification**

Run:

```bash
python -m unittest -v tests.test_project_sync
python -m py_compile scripts/project_sync.py
```

Expected: all tests pass; compile succeeds.

- [ ] **Step 2: Compare branch against `main`**

Confirm only planned implementation/spec/docs files changed.

- [ ] **Step 3: Open PR referencing #39**

PR body records test evidence and explicitly states live Project mutation is blocked only by missing `PROJECTS_TOKEN` if not yet configured.

- [ ] **Step 4: Re-audit PR**

Check authority direction, token leakage, GraphQL mutation boundaries, recursion prevention, pagination, and idempotence.

- [ ] **Step 5: Merge when no blocking finding remains**

User has authorized low-risk merges with rollback by revert PR if a material problem is found.

### Task 8: User-admin credential handoff and live acceptance

**Files:**
- Update operational Issues only after user action.

- [ ] **Step 1: Leave exact user action**

User creates/configures Project-capable credential and repository secret `PROJECTS_TOKEN`.

- [ ] **Step 2: After the user reports secret configured, run manual reconcile/verify**

Use GitHub Actions manual dispatch. Confirm post-reconcile Health Issue state.

- [ ] **Step 3: Initial direct Project acceptance**

Have Codex or another Project-capable agent directly inspect Project #1 once and compare against Sync Health/API result.

- [ ] **Step 4: Complete #39 and #16**

Close #39 only after live acceptance; update #16 to make Sync Health the normal indirect Project verification path.
