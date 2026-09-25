# GitHub Project Sync Architecture

Status: Proposed design for Work Order #39
Date: 2026-09-25
Owner repository: `kinoko34077/devflow-test`
Project: `KiNoTch. Development Control` (`kinoko34077` Project #1)

## 1. Purpose

Automatically project canonical devflow Issue state into the display-only GitHub Project while keeping devflow and individual repositories authoritative.

The synchronizer must also produce enough machine-readable evidence that a normal ChatGPT session, which cannot directly read the private Project through the current connector, can still determine whether synchronization is healthy without requiring Codex to inspect the UI on every run.

## 2. Authority boundary

The authority direction is strictly one-way:

```text
individual repository state
        -> devflow Repository Control / cross-repo Issue
        -> Project synchronizer
        -> GitHub Project display fields
```

The synchronizer MUST NOT:

- close or reopen canonical Issues because of Project field changes;
- edit Issue bodies based on Project values;
- treat Project custom fields as canonical state;
- infer unsupported values merely to make the dashboard complete.

The existing built-in `Issue closed -> Status = DONE` Project workflow is compatible with this direction because the canonical Issue event drives the Project display.

## 3. Canonical field mapping

The synchronizer parses Markdown sections from devflow Issues and maps them as follows:

| Canonical Issue section / state | Project field | Project field kind |
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

Supported single-select values are taken from `.devflow/WORKFLOW.yaml` and the canonical cross-repository specification.

### 3.1 Missing sections

Missing canonical sections are not guessed.

- If an open Repository Control Issue has no `Work Status`, the synchronizer leaves Project `Status` unchanged unless a later canonical rule explicitly defines a value.
- If a text field is absent, verification reports it as `NOT_APPLICABLE` rather than overwriting Project state with invented text.
- If a present value is not one of the canonical select options, synchronization fails for that field and reports the invalid value.

### 3.2 Closed Issues

A closed Issue always projects `Status = DONE`, regardless of the last open-state `Work Status` text. Other canonical fields may still be synchronized for historical display if present.

## 4. Components

### 4.1 `.github/workflows/project-sync.yml`

Triggers:

- `issues: [opened, edited, reopened, closed]`
- `workflow_dispatch`

Manual dispatch inputs:

- `mode`: `verify` or `reconcile`
- optional `issue_number`: when present, limit work to one devflow Issue

The workflow MUST NOT use a periodic schedule in v1.

Event behavior:

- Issue event: synchronize only the changed Issue.
- Manual `verify`: read canonical Issues and Project state; make no Project mutations.
- Manual `reconcile`: compare all managed devflow Issues against Project state and repair drift.

### 4.2 `scripts/project_sync.py`

A dependency-light Python CLI implementing:

- Markdown section parsing;
- canonical value normalization without semantic inference;
- GitHub GraphQL requests;
- Project/field/option/item discovery;
- single-Issue sync;
- full verify;
- full reconcile;
- structured result production for workflow logs and health reporting.

Use Python standard library where practical. Additional runtime dependencies require explicit justification.

### 4.3 `tests/test_project_sync.py`

Tests cover parser behavior, mapping, validation, closed-Issue rules, drift comparison, idempotence-oriented planning, and error handling without requiring a live Project token.

### 4.4 `docs/project/PROJECT_SYNC.md`

Operational documentation covering:

- token setup;
- workflow modes;
- expected Sync Health Issue format;
- troubleshooting;
- when direct Project verification by Codex or another capable agent is required.

## 5. Project discovery

No GraphQL node IDs are committed to the repository.

Configuration uses stable human-facing identity:

- owner login: `kinoko34077`
- Project number: `1`

At runtime the synchronizer queries GitHub GraphQL to discover:

- Project node ID;
- Project title and visibility where available;
- Project fields and field IDs;
- single-select option IDs by exact option name;
- Project items and their content Issue node IDs;
- current Project field values.

Field matching is exact and case-sensitive after trimming. Missing or duplicate expected fields are treated as verification failures rather than selecting an arbitrary match.

## 6. Project item membership

For a canonical devflow Issue:

1. Query Project items for an item whose content node ID matches the Issue node ID.
2. If present, reuse the Project item ID.
3. If absent in `verify` mode, report drift and do not mutate.
4. If absent in `reconcile` or event-sync mode, call `addProjectV2ItemById`.
5. After membership exists, update supported fields in separate mutations.

Adding and updating are separate GraphQL operations because GitHub does not support adding an item and updating its field values in the same mutation.

The existing Project Auto-add workflow remains enabled as a convenience; the synchronizer does not depend on its timing for correctness.

## 7. Field update behavior

### 7.1 Single-select fields

For `Status`, `Repository State`, `Priority`, `Risk`, and `Work Type`:

- resolve the field by exact name;
- resolve the option by exact canonical value;
- compare current option ID/value with desired state;
- mutate only when drift exists.

### 7.2 Text fields

For `Managed Repository`, `Next Action`, and `Audit SHA`:

- compare current text with canonical parsed text;
- mutate only when drift exists;
- do not clear a Project field merely because the canonical section is absent unless the canonical specification later explicitly defines absence as clearing.

This prevents partial Issue types from destructively erasing unrelated display state.

## 8. Verify and reconcile

### 8.1 `verify`

Read-only with respect to the Project.

It must report:

- Project resolvable/not resolvable;
- expected fields present/missing/duplicate;
- expected select options present/missing;
- each canonical Issue present/missing in Project;
- each supported field `MATCH`, `DRIFT`, `NOT_APPLICABLE`, or `ERROR`;
- unexpected fatal configuration errors;
- verification coverage and counts.

`verify` may update the Sync Health Issue because that Issue is the operational verification record, not Project state. If health reporting itself fails, the workflow must still fail visibly in Actions logs.

### 8.2 `reconcile`

Runs the same comparison and then repairs supported drift from canonical devflow state.

After mutation it performs a second read-only verification pass. Reconcile succeeds only if the post-write verification has no blocking drift/errors.

Repeated reconcile against unchanged canonical state must be effectively idempotent: no field mutation should be sent when current Project value already matches desired value.

## 9. Sync Health Issue

Create one persistent devflow Issue with exact title:

`[SYSTEM] GitHub Project Sync Health`

Its body is machine-maintained and contains only current verification state, not append-only logs.

Minimum body schema:

```markdown
## Result
PASS | DEGRADED | FAIL | NOT_CONFIGURED

## Last Verification
<ISO-8601 UTC timestamp>

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
<GitHub Actions run URL or identifier>

## Direct Verification Requirement
NONE | CODEX_REQUIRED
<reason when required>
```

Result semantics:

- `PASS`: all API-verifiable requirements checked by the synchronizer match.
- `DEGRADED`: canonical synchronization works but one or more non-blocking checks are unavailable.
- `FAIL`: API-verifiable drift/error remains after verification/reconcile.
- `NOT_CONFIGURED`: required Project credential is absent or Project access cannot be established.

The Health Issue must clearly distinguish what was verified by API from what is outside the synchronizer's visibility.

## 10. Direct Project verification escalation

Normal operation should not require Codex/UI inspection when Sync Health is `PASS` and the relevant requirement is API-verifiable.

Set `Direct Verification Requirement = CODEX_REQUIRED` when any of the following applies:

- Project structure was intentionally changed (field/view/workflow configuration change);
- a required Project/UI property cannot be verified through the implemented GraphQL/API path;
- machine verification and an observed UI result disagree;
- Project/field discovery returns ambiguous data;
- a migration changes Project owner/number or field names;
- the user explicitly requests direct verification.

Operational handoff for a capable agent:

1. Read this design, canonical spec, `.devflow/WORKFLOW.yaml`, the Sync Health Issue, and relevant Work Order.
2. Directly inspect Project #1 using available Project-capable API/UI tooling.
3. Compare observed structure and values against canonical requirements.
4. Record exact observed configuration and discrepancies in the active Work Order/verification Issue.
5. Do not silently rewrite canonical requirements to match the UI; open/retain a blocking Issue when GitHub limitations require a design decision.

This makes direct Codex inspection an escalation path rather than the everyday source of truth.

## 11. Authentication and secrets

The synchronizer reads the token from repository secret:

`PROJECTS_TOKEN`

No token value, derived credential, or authentication header is ever written to source files, Issues, logs, or health reports.

The token must support reading and mutating the user-owned Project and reading devflow Issues. For the initial implementation, a user-admin configured credential is an explicit setup dependency.

If the token is missing:

- workflow returns `NOT_CONFIGURED` where health reporting is still possible;
- no Project mutation is attempted;
- logs explain the missing secret name without exposing any value.

Credential creation/permission changes remain user-controlled because they are security-sensitive.

## 12. Error handling and safety

Blocking failures include:

- Project not found;
- expected field missing or duplicated;
- expected single-select option missing or duplicated;
- invalid canonical select value;
- GraphQL authorization failure;
- Project item add/update failure;
- post-reconcile drift remains.

Safety rules:

- stop mutating the affected item after a structural/configuration error is found;
- do not guess IDs or nearest field/option names;
- do not mutate canonical Issue state from Project values;
- do not print secrets;
- preserve partial-success details in the structured result/health report;
- return non-zero exit status for blocking failure.

## 13. Issue selection for full verification

Full verify/reconcile targets devflow Issues that represent Project items under the current v1 scope:

- open Repository Control Issues (`[REPO] ...`);
- open cross-repository operational/Work Order Issues intended for the Project;
- closed Project-tracked Issues still present in the Project when needed to validate terminal Status.

The implementation should prefer explicit repository/title/state rules over a hard-coded numeric Issue range. It must exclude the backup repositories `pc-files` and `pc-files2` according to canonical scope.

The Sync Health Issue itself is not synchronized into Project display fields unless explicitly made a Project item later.

## 14. Tests

Minimum automated tests:

1. Parse each canonical Markdown section with CRLF/LF and surrounding whitespace.
2. Ignore similarly named headings that are not exact canonical headings.
3. Closed Issue overrides Status to DONE.
4. Missing optional section becomes NOT_APPLICABLE, not guessed.
5. Invalid select value is a blocking validation error.
6. Canonical -> Project field-name mapping matches the current spec.
7. Duplicate/missing field discovery fails deterministically.
8. Duplicate/missing select option discovery fails deterministically.
9. Verify computes MATCH/DRIFT without mutation planning side effects.
10. Reconcile plans mutations only for drift.
11. Reconcile post-verification detects remaining drift.
12. Secret/token values are never included in rendered health/error messages.

Live integration verification after credential configuration:

- run manual `verify`;
- run `reconcile` if drift exists;
- run `verify` again;
- confirm Sync Health Issue result;
- directly inspect Project through Codex only if health says CODEX_REQUIRED or during initial rollout acceptance.

## 15. Rollout

Phase 1 — repository implementation without live secret:

- add parser/client/workflow/tests/docs;
- run unit tests;
- verify workflow syntax and dry-run behavior;
- merge only after re-audit.

Phase 2 — user-admin credential setup:

- create/configure Project-capable credential;
- store only as repository secret `PROJECTS_TOKEN`.

Phase 3 — live acceptance:

- run manual verify;
- reconcile initial field drift;
- confirm post-reconcile PASS;
- perform one direct Codex Project inspection to validate initial rollout and API/UI agreement;
- record evidence in Work Order #39 and Sync Health Issue.

After Phase 3, routine ChatGPT verification reads devflow Issue state, Sync Health Issue, and Actions evidence. Direct Project inspection is escalation-only.

## 16. Completion criteria

Work Order #39 is complete only when:

- implementation/tests/docs are merged;
- required credential has been configured by the user/admin;
- live reconcile/verify succeeds;
- Sync Health Issue reports PASS or an explicitly accepted DEGRADED state;
- initial direct Project verification confirms no material API/UI mismatch;
- `[REPO] devflow-test` Control Issue points to the new normal verification path.