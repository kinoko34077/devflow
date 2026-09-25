# GitHub Project Synchronization

Status: Implemented, live activation requires `PROJECTS_TOKEN`
Tracking Work Order: `#39`
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

After live activation, a normal ChatGPT session that cannot directly read the private Project should check, in order:

1. `[SYSTEM] GitHub Project Sync Health`
2. `[REPO] devflow-test` Control Issue
3. active Work Order / relevant Repository Control Issue
4. relevant Actions run/logs when Health is not `PASS`

A `PASS` result means the implemented API-verifiable synchronization checks passed at the recorded run/time. It does not claim that UI-only properties outside API coverage were directly observed.

## 6. Direct Project verification by Codex or another capable agent

Direct Project inspection is an escalation path, not routine state storage.

Use direct inspection when:

- initial live rollout is being accepted;
- Project fields/views/workflows were structurally changed;
- Sync Health says `CODEX_REQUIRED`;
- an API-verifiable result disagrees with an observed UI result;
- Project owner/number/field names changed;
- the user explicitly requests direct Project verification.

The capable agent must:

1. read `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`, `.devflow/WORKFLOW.yaml`, this file, Sync Health, and the active Work Order;
2. directly inspect Project #1 with Project-capable tooling/UI;
3. compare the live Project against canonical requirements;
4. record exact observations/discrepancies in the active Work Order or verification Issue;
5. never silently rewrite canonical requirements to match a UI limitation.

## 7. User-admin activation step

`GITHUB_TOKEN` is repository-scoped and is not used for Project access. The Project synchronizer expects a separate repository Actions secret named exactly:

`PROJECTS_TOKEN`

For the current user-owned Project implementation, use a Project-capable personal access token and save only the token value as that repository secret. GitHub's documented user-Project Actions approach uses a personal access token (classic) with `project` and `repo` scopes.

Do not place the token in source code, Issue bodies, workflow YAML, comments, or logs.

After the secret is configured:

1. manually dispatch `Project sync` with `mode = reconcile` and no Issue number;
2. wait for the run to complete;
3. manually dispatch `Project sync` with `mode = verify`;
4. confirm `[SYSTEM] GitHub Project Sync Health` reports `PASS` (or an explicitly accepted `DEGRADED` state);
5. perform one direct Codex/Project-capable inspection for initial rollout acceptance;
6. record the result in Work Order #39 and update `[REPO] devflow-test`.

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

## 10. Verification limitation before activation

Before `PROJECTS_TOKEN` is registered, implementation/tests/workflow syntax can be verified but the private Project cannot be live-read or mutated by this workflow. That state is intentionally represented as `NOT_CONFIGURED`, not as a failed canonical comparison.

After registration, the first full `reconcile` + `verify` pair and one direct Codex/Project-capable inspection are required before Work Order #39 is closed.
