# GitHub Project Sync Architecture

Status: Proposed design for Work Order #39
Date: 2026-09-25
Owner repository: `kinoko34077/devflow-test`
Project: `KiNoTch. Development Control` (`kinoko34077` Project #1)

## 1. Purpose

Automatically project canonical devflow Issue state into the display-only GitHub Project while keeping devflow and individual repositories authoritative.

The synchronizer must also produce machine-readable verification evidence so a normal ChatGPT session can judge Project-sync health without directly reading the private Project. Direct Project inspection by Codex or another Project-capable agent becomes an escalation/acceptance path rather than a routine dependency.

## 2. Authority boundary

Authority is strictly one-way:

```text
individual repository state
        -> devflow Repository Control / cross-repo Issue
        -> Project synchronizer
        -> GitHub Project display fields
```

The synchronizer MUST NOT:

- close or reopen canonical Issues because of Project field changes;
- edit canonical Issue content based on Project values;
- treat Project custom fields as canonical state;
- infer unsupported values merely to fill the dashboard.

The existing `Issue closed -> Status = DONE` Project workflow is compatible because the canonical Issue event drives the display.

## 3. Canonical field mapping

| Canonical source | Project field | Kind |
| --- | --- | --- |
| Issue closed | Status = DONE | built-in single-select |
| Work Status | Status | built-in single-select |
| Repository State | Repository State | custom single-select |
| Priority | Priority | custom single-select |
| Risk | Risk | custom single-select |
| Type | Work Type | custom single-select |
| Repository | Managed Repository | custom text |
| Next Action | Next Action | custom text |
| Audit SHA | Audit SHA | custom text |

Canonical select values come from `.devflow/WORKFLOW.yaml` and `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`.

Missing sections are never guessed. For an open Issue, a missing field is `NOT_APPLICABLE` and is not cleared or overwritten in the Project. A present but invalid select value is a blocking validation error. A closed Issue always projects `Status = DONE`.

## 4. Components

### 4.1 `.github/workflows/project-sync.yml`

Triggers:

- `issues: [opened, edited, reopened, closed]`
- `workflow_dispatch`

Manual inputs:

- `mode`: `verify` or `reconcile`
- optional `issue_number`

No periodic schedule is added in v1.

Behavior:

- normal Issue event -> synchronize only that Issue;
- manual `verify` -> compare canonical devflow state with live Project, no Project mutation;
- manual `reconcile` -> repair supported drift, then verify again.

The workflow uses repository `GITHUB_TOKEN` only for devflow Issue/Health-Issue operations and `PROJECTS_TOKEN` only for Project GraphQL access.

### 4.2 `scripts/project_sync.py`

Dependency-light Python CLI implementing:

- exact Markdown section parsing;
- canonical validation;
- GitHub GraphQL Project discovery/read/write;
- single-Issue event sync;
- full verify/reconcile;
- structured health result generation.

Use Python standard library where practical.

### 4.3 `tests/test_project_sync.py`

Unit tests cover parsing, mapping, validation, drift computation, mutation planning, health rendering, and failure behavior without requiring a live Project token.

### 4.4 `docs/project/PROJECT_SYNC.md`

Operations guide covering credentials, workflow modes, Sync Health interpretation, troubleshooting, and direct-verification escalation.

## 5. Project discovery

No Project, field, option, or item node IDs are committed.

Stable configuration:

- owner login: `kinoko34077`
- Project number: `1`

At runtime GraphQL resolves:

- Project node ID/title/visibility where exposed;
- field IDs;
- exact single-select option IDs;
- item IDs and Issue content node IDs;
- current Project field values.

Expected field/option names are exact after trimming. Missing or ambiguous matches are blocking errors; no nearest-name fallback is allowed.

## 6. Expected Project membership

The current built-in Auto-add rule is `kinoko34077/devflow-test` + `is:issue is:open`. Therefore full verification defines the expected active set as:

1. every open Issue in `kinoko34077/devflow-test`, except the Sync Health Issue itself;
2. closed devflow Issues already present in the Project, when validating terminal `Status = DONE`.

This matches the actual feeder rule instead of relying on hard-coded Issue ranges or title conventions.

`pc-files` and `pc-files2` remain outside managed Repository Control scope, but this does not require special numeric Issue filtering.

For each expected Issue:

1. locate Project item by Issue content node ID;
2. in `verify`, missing membership is drift only;
3. in event-sync/reconcile, missing membership is repaired with `addProjectV2ItemById`;
4. field updates occur only after membership exists.

GitHub requires item addition and field update as separate operations. The existing Auto-add workflow remains a convenience; synchronizer correctness does not depend on its timing. citeturn715469search0turn715469search1

## 7. Field update behavior

For single-select fields (`Status`, `Repository State`, `Priority`, `Risk`, `Work Type`):

- resolve field and desired option by exact name;
- compare current versus desired;
- mutate only on drift.

For text fields (`Managed Repository`, `Next Action`, `Audit SHA`):

- compare exact normalized text;
- mutate only on drift;
- absence does not imply clearing.

`updateProjectV2ItemFieldValue` is used only for supported Project item field types. Built-in Repository remains read-only Issue ownership metadata and is not mutated. citeturn715469search1turn715469search2

## 8. Verify and reconcile

### 8.1 Verify

Project-read-only comparison producing, per field/item:

- `MATCH`
- `DRIFT`
- `NOT_APPLICABLE`
- `ERROR`

It also validates Project resolvability, expected fields/options, item membership, coverage, and blocking configuration errors.

Verify may update the Sync Health Issue because that Issue is the operational verification record, not Project state.

### 8.2 Reconcile

Runs the same comparison, repairs supported drift, then performs a fresh verify pass.

Success requires no blocking drift/errors after the second pass. Re-running reconcile against already matching state must produce no Project field mutations.

## 9. Sync Health Issue

Create one persistent Issue named exactly:

`[SYSTEM] GitHub Project Sync Health`

Its body is overwritten with current health, not used as an append-only log.

Minimum schema:

```markdown
## Result
PASS | DEGRADED | FAIL | NOT_CONFIGURED

## Last Verification
<ISO-8601 UTC>

## Mode
verify | reconcile | event-sync

## Project
- Owner: kinoko34077
- Number: 1
- Title: KiNoTch. Development Control

## Coverage
- Canonical issues checked: N
- Project items matched: N
- Drift fields: N
- Errors: N

## Drift / Errors
- ...

## Run
<Actions run URL>

## Direct Verification Requirement
NONE | CODEX_REQUIRED
<reason if required>
```

Result semantics:

- `PASS`: every API-verifiable required check matches.
- `DEGRADED`: synchronization works but non-blocking coverage is unavailable.
- `FAIL`: API-verifiable drift/error remains.
- `NOT_CONFIGURED`: Project credential/access is unavailable.

### 9.1 Health-Issue recursion rule

Because Auto-add currently accepts every open devflow Issue, the Health Issue may itself appear in the Project. That is acceptable for v1, but it is not canonical synchronization input.

The workflow MUST detect the exact Health-Issue title and exit event-sync without Project-field synchronization. Updating its body therefore cannot recursively trigger another health update loop.

Full verify/reconcile excludes the Health Issue from expected canonical field coverage even if Auto-add has placed it in the Project.

## 10. Direct Project verification escalation

Routine ChatGPT operation relies on:

1. canonical devflow Issues;
2. Sync Health Issue;
3. Actions run/status/log evidence when needed.

Set `Direct Verification Requirement = CODEX_REQUIRED` when:

- Project structure/field/view/workflow configuration intentionally changed;
- a required UI/property is not covered by implemented APIs;
- API verification and observed UI disagree;
- discovery is ambiguous;
- owner/project number/field names migrate;
- user explicitly requests direct Project verification.

A Project-capable agent must then:

1. read canonical spec, `.devflow/WORKFLOW.yaml`, this design, Health Issue, and active Work Order;
2. inspect live Project #1 directly;
3. compare exact observed structure/values with canonical requirements;
4. record evidence/discrepancies in the active Work Order;
5. never silently alter canonical requirements to match UI limitations.

This satisfies the requirement that Codex can act as a direct-verification substitute when the normal Chat connector cannot read Projects.

## 11. Authentication

Repository secret:

`PROJECTS_TOKEN`

GitHub's official Projects API documentation requires `read:project` for reads or `project` for Project queries/mutations when using a classic PAT; a GitHub App installation token is also supported. v1 uses a user-admin configured Project-capable token unless a later design replaces it with an App. citeturn715469search0

`devflow-test` is public, so Project access is the additional capability required for the Project operations themselves. Repository Issue updates use the workflow's `GITHUB_TOKEN` with explicit `issues: write` and `contents: read` permissions.

No credential value or authorization header may be written to source, Issues, logs, or health output.

If `PROJECTS_TOKEN` is absent:

- no Project request/mutation is attempted;
- workflow reports `NOT_CONFIGURED` when possible;
- logs name the missing secret only;
- security-sensitive credential creation remains user-controlled.

## 12. Error handling

Blocking failures include:

- Project not found/access denied;
- expected field or select option missing/ambiguous;
- invalid canonical select value;
- Project membership/add/update failure;
- post-reconcile drift remains.

Rules:

- never guess IDs/names;
- stop mutating affected item after structural error;
- never mutate canonical Issue state from Project values;
- redact secrets;
- preserve partial-success details;
- return non-zero for blocking failure.

## 13. Tests

Minimum automated tests:

1. exact section parsing under LF/CRLF/whitespace;
2. similarly named headings do not match;
3. closed Issue overrides Status to DONE;
4. missing field -> NOT_APPLICABLE;
5. invalid select -> blocking error;
6. canonical -> Project field mapping;
7. missing/duplicate field and option discovery failures;
8. verify is Project-read-only;
9. reconcile plans only drift mutations;
10. post-reconcile remaining drift fails;
11. Health Issue event is ignored and does not recurse;
12. full coverage excludes Health Issue while including ordinary open devflow Issues;
13. secret values never appear in rendered output.

## 14. Rollout

### Phase 1 — repository implementation

- implement script/workflow/tests/docs;
- unit-test without live secret;
- verify workflow syntax/dry-run behavior;
- PR/re-audit/merge.

### Phase 2 — user-admin credential

- create Project-capable token;
- store only as `PROJECTS_TOKEN` repository secret.

### Phase 3 — live acceptance

- manual verify;
- reconcile if drift exists;
- verify again;
- confirm Health result;
- perform one direct Codex Project inspection to validate initial API/UI agreement;
- record evidence in Work Order #39 and Health Issue.

After acceptance, direct Project inspection is escalation-only.

## 15. Completion criteria

Work Order #39 completes only when:

- implementation/tests/docs are merged;
- Project credential is configured;
- live reconcile/verify succeeds;
- Health Issue is `PASS` or explicitly accepted `DEGRADED`;
- initial Codex/direct Project inspection finds no material API/UI mismatch;
- `[REPO] devflow-test` points to the new verification path.