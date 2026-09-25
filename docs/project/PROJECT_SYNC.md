# GitHub Project Synchronization

Status: Operational; initial live acceptance completed 2026-09-25
Tracking Work Order: `#39` (completed)
Current migration Work Order: `#46`
Project: `KiNoTch. Development Control`
Project URL: `https://github.com/users/kinoko34077/projects/1`

## 1. Role

The synchronizer projects canonical devflow Issue state into the display-only GitHub Project.

Authority remains one-way:

```text
individual repository
  -> devflow Issue / Repository Control Issue
  -> Project synchronizer
  -> GitHub Project display fields
```

Project values are never used to rewrite canonical Issues.

## 2. Synced fields

| devflow canonical state | Project field |
| --- | --- |
| Work Status | built-in `Status` |
| closed Issue | built-in `Status = DONE` |
| Repository State | `Repository State` |
| Priority | `Priority` |
| Risk | `Risk` |
| Type | `Work Type` |
| Repository | `Managed Repository` |
| Next Action | `Next Action` |
| Audit SHA | `Audit SHA` |

Missing Issue sections are not guessed or used to clear existing Project values. Unknown select values fail explicitly.

## 3. Automation

Workflow: `.github/workflows/project-sync.yml`

Event sync runs for devflow Issue events:

- opened
- edited
- reopened
- closed

Manual workflow modes:

- `verify`: read-only comparison of canonical devflow state against Project state.
- `reconcile`: repairs supported Project drift from canonical devflow state and then verifies again.
- optional `issue_number`: limit manual work to one Issue.

There is no periodic schedule in v1.

The workflow uses `$GITHUB_REPOSITORY` at runtime for repository-scoped Issue operations; the workflow YAML itself does not depend on the literal repository name.

## 4. Sync Health Issue

The workflow maintains one Issue with exact title:

`[SYSTEM] GitHub Project Sync Health`

The Health Issue stores the latest verification result rather than append-only history.

Result values:

- `PASS`: API-verifiable canonical state matches the Project.
- `DEGRADED`: synchronization works but a non-blocking check is unavailable.
- `FAIL`: drift/configuration/API error remains.
- `NOT_CONFIGURED`: `PROJECTS_TOKEN` is not available, so Project verification/mutation was not attempted.

The Health Issue also contains coverage, drift/error counts, Actions run reference, and `Direct Verification Requirement`.

The Health Issue is kept closed so the Project Auto-add filter `is:issue is:open` does not normally add it. Event-sync ignores the Health Issue before Project access to prevent recursion. If it is already present in the Project, `reconcile` removes that Project item.

## 5. Normal verification path

A normal ChatGPT session that cannot directly read the private Project should check, in order:

1. `[SYSTEM] GitHub Project Sync Health`
2. the devflow Repository Control Issue `[REPO] devflow`
3. active Work Order / relevant Repository Control Issue
4. relevant Actions run/logs when Health is not `PASS`

A `PASS` result means the implemented API-verifiable synchronization checks passed at the recorded run/time. It does not claim that UI-only properties outside API coverage were directly observed.

## 6. Direct Project verification

Direct Project inspection is an escalation path, not routine state storage.

Use direct inspection when:

- Project fields/views/workflows were structurally changed;
- Sync Health says `CODEX_REQUIRED`;
- an API-verifiable result disagrees with an observed UI result;
- Project owner/number/field names changed;
- repository identity migration may affect Project Auto-add/configuration;
- the user explicitly requests direct Project verification.

The initial live rollout direct inspection was completed on 2026-09-25 and recorded in Work Order `#39`.

The capable agent must:

1. read `AGENTS.md`, `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`, `.devflow/WORKFLOW.yaml`, this file, Sync Health, and the active Work Order;
2. directly inspect Project #1 with Project-capable tooling/UI;
3. compare the live Project against canonical requirements;
4. record exact observations/discrepancies in the active Work Order or verification Issue;
5. never silently rewrite canonical requirements to match a UI limitation.

## 7. Authentication and activation state

`GITHUB_TOKEN` is repository-scoped and is not used for Project access. The Project synchronizer uses a separate repository Actions secret named exactly:

`PROJECTS_TOKEN`

Current state: the secret is configured and authenticated Project access is operational.

For recreation or credential rotation, use a Project-capable personal access token and save only the token value as that repository secret.

Do not place the token in source code, Issue bodies, workflow YAML, comments, or logs.

After credential recreation/rotation, run full `reconcile` then full `verify` and confirm Sync Health returns an accepted state before considering the credential change complete.

## 8. Failure handling

Blocking failures include:

- Project missing/inaccessible;
- Project title or privacy mismatch;
- required field missing/duplicated/wrong type;
- required single-select option set mismatch;
- invalid canonical select value;
- Project add/update failure;
- post-reconcile drift remains.

The synchronizer does not guess IDs or approximate field names. Project, field, option, and item IDs are discovered at runtime.

## 9. Tests

Secret-free CI: `.github/workflows/project-sync-tests.yml`

Local verification:

```bash
python -W error -m unittest discover -v
python -m py_compile scripts/project_sync.py
```

Unit tests do not require Project credentials or live Project mutations.

## 10. Initial live acceptance

Initial live acceptance completed on 2026-09-25.

Recorded evidence:

- full `reconcile`: Actions run `36108965683` — Success;
- full `verify`: Actions run `36109459896` — Success;
- full verification coverage: 33 canonical Issues checked, 33 Project items matched, drift 0, errors 0;
- initial direct Project-capable inspection: completed with no material mismatch recorded;
- Work Order `#39`: completed and closed.

Subsequent Issue changes use event-sync. Use targeted or full `reconcile` -> `verify` when structural changes, suspected drift, credential rotation, repository identity migration, or explicit verification require it.

## 11. Repository rename acceptance

The GitHub repository was renamed from `kinoko34077/devflow-test` to `kinoko34077/devflow` on 2026-09-25. Work Order `#46` owns final migration acceptance.

Historical Issue/PR/commit references may retain the old repository name where they identify historical events. Current operational identity is `kinoko34077/devflow`.

The rename itself has been directly observed. Before Work Order #46 may close, require all of the following:

1. repository metadata resolves as `kinoko34077/devflow`;
2. Issues, PRs, Actions, default branch and branch protection remain usable;
3. required repository secret/configuration remains effective without exposing secret values;
4. Project Auto-add is directly verified to target `kinoko34077/devflow`;
5. full `reconcile` runs with no Issue number and succeeds;
6. full `verify` runs with no Issue number and succeeds;
7. Sync Health records expected full coverage, drift `0`, errors `0`, and no unresolved direct-verification requirement;
8. Repository Control is migrated to `[REPO] devflow`, current repository fields/references are updated, and Audit SHA is refreshed;
9. only then may Work Order #46 close as `DONE`.
