# GitHub Project Synchronization

Status: Operational; initial live acceptance completed 2026-09-25
Tracking Work Order: `#39` (completed)
Repository rename Work Order: `#46` (completed)
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
| Audit Ref | `Audit Ref` |
| Last Audit At | `Last Audit` |
| Audit Depth | `Audit Depth` |
| Audit Scope | `Audit Scope` |
| Audit Evidence | `Audit Evidence` |
| Last Deep Audit At | `Last Deep Audit` |
| derived Audit Freshness | `Audit Freshness` |

Audit provenance remains canonical in the Repository Control. `Audit Freshness` is derived from exact `Audit SHA` versus the explicit `Audit Ref` head and is never reverse-synced into the Control. `Last Audit`/`Audit Depth` describe the latest accepted audit event, while `Audit SHA`/`Audit Ref` preserve the latest accepted repository-revision audit binding. A CONTROL-only audit may update the former without advancing the latter. If the ref is absent or cannot be resolved safely, freshness is `UNKNOWN`; the synchronizer does not guess the default branch.

The same derivation result is also projected onto each trusted `[REPO]` Control as exactly one machine-owned, non-canonical label:

- `devflow:audit-freshness:current`
- `devflow:audit-freshness:drifted`
- `devflow:audit-freshness:unknown`

These labels are a transport/cache for read-only consumers such as Repo Monitor. They are not canonical Control facts and do not add an `## Audit Freshness` body section. Manual label edits never become authority: `verify` reports missing/multiple/wrong freshness labels as drift, while `reconcile` and `event-sync` repair only these three machine-owned labels from the same `derive_audit_freshness()` result used by the Project field. Other Issue labels are preserved.

Repo Monitor and other consumers must consume this projection rather than resolve refs or implement a second freshness algorithm.

`Audit Depth` uses `CONTROL | STANDARD | DEEP`. Project date fields display the calendar date from the canonical UTC audit timestamp while the full timestamp remains in the Control/evidence surface.

Missing Issue sections are not guessed or used to clear existing Project values. Unknown select values fail explicitly.

Project custom TEXT fields are **bounded display projections**, not alternative canonical storage. When canonical text exceeds a conservative 1,000 UTF-8-byte projection budget, sync deterministically shows its initial excerpt followed by `... [truncated; see canonical Issue]`. Full text remains unchanged in the owning Issue, which is the source of truth and accessible from the Project item. Shorter values are projected exactly. The same bounded display value is used by event-sync, full/targeted reconcile, and verify; a truncation does not hide other drift or clear failure memory. The byte budget is a conservative integration guard for an observed GitHub GraphQL text-column rejection, **not a claim that GitHub publicly documents an exact 1,000-byte ceiling**.

## 3. Automation

Workflow: `.github/workflows/project-sync.yml`

### Owner-only GitHub-native command transport (devflow#395 — Draft)

On accepted default-branch code, a trusted owner-authored Issue comment may
request a **full-scope** Project Sync with exact text:

- `/kinotch sync verify`
- `/kinotch sync reconcile`

Only newly **created** comments trigger this path; editing an old comment
does not re-issue a command. To request a second run, the owner posts a new
exact command after checking the previous run's outcome. The shared
`project-sync` serialization is at JOB level after admission, so skipped
untrusted comments do not take mutator queue slots.

GitHub's `issue_comment.created` event is authenticated by GitHub and
evaluated at the **job** boundary. The workflow checks this repository identity,
non-PR Issue authored by GitHub user ID `79015263`, and both commenter and
sender with the same owner ID; it rejects any other body. The comment content
is **never used as a shell expression or executable argument**: it selects
a fixed mode, with an empty issue_number (full scope). Existing manual
`workflow_dispatch` and normal `issues` event behavior remain unchanged.
A successful run does not imply Sync Health PASS: check the actual run and
machine Health #41 before advancing or calling reconcile → verify complete.

No private App key or cross-repository token is needed for the request path;
the existing Project Sync secret remains privileged as before and is supplied
only to a guarded, authorized job. There is no new background scheduler.
This feature does **not** configure a repo created outside devflow Bootstrap.
The actual GitHub Actions trigger and secret boundary must receive independent
security Review and Human-authorized merge before becoming active.


Event sync runs for devflow Issue events:

- opened
- edited
- reopened
- closed

Manual workflow modes:

- `verify`: read-only comparison of canonical devflow state against Project state.
- `reconcile`: creates/validates the bounded audit-provenance Project fields when needed, repairs supported Project drift from canonical devflow state, and then verifies again.
- optional `issue_number`: limit manual work to one Issue.

There is no periodic schedule in v1.

Trust boundary: devflow is public, so only Issues whose `author_association` is `OWNER`, `MEMBER` or `COLLABORATOR` are treated as canonical. Event sync for any other author exits without Project access, and verify/reconcile selection skips such Issues (missing association data is treated as untrusted).

The workflow uses `$GITHUB_REPOSITORY` at runtime for repository-scoped Issue operations; the workflow YAML itself does not depend on the literal repository name.

## 4. Sync Health Issue

The workflow maintains one Issue with exact title:

`[SYSTEM] GitHub Project Sync Health`

The Health Issue stores the latest verification result rather than append-only history, plus a bounded machine-owned memory of unresolved scoped failures so a later unrelated event cannot mask an earlier failure.

Project item fields and this Health failure-memory record are shared mutable surfaces. The Project Sync workflow therefore serializes all Issue-event and manual sync mutators through one repository-wide concurrency group with `queue: max` and `cancel-in-progress: false`; different Issue numbers must not update these shared surfaces concurrently, and normal bursts queue instead of replacing an older pending run.

GitHub's bounded concurrency queue may hold up to 100 pending runs. If Actions reports a Project Sync run canceled because that queue capacity was exceeded, event coverage is no longer assumed complete: run a full manual `reconcile` followed by full `verify` before treating Sync Health `PASS` as re-established.

Result values:

- `PASS`: API-verifiable canonical state matches the Project **and no unresolved failure memory remains**.
- `DEGRADED`: synchronization works but a non-blocking check is unavailable.
- `FAIL`: drift/configuration/API error remains, including a remembered unresolved scoped/global failure.
- `NOT_CONFIGURED`: `PROJECTS_TOKEN` is not available, so Project verification/mutation was not attempted.

Failure-memory clearing is deterministic:

- an `event-sync` or targeted manual run that succeeds clears only that exact Issue's remembered failure;
- success for a different Issue does not clear another Issue's failure and therefore does not turn global Health to `PASS`;
- a failed full-scope `verify`/`reconcile` records a global failure that ordinary Issue events cannot clear;
- a successful full-scope `verify`/`reconcile` clears the bounded failure memory because it has re-established the whole API-verifiable synchronization boundary.

The memory is stored only in the machine-owned Sync Health body. It is observability state, not task authority, not a second lifecycle, and never drives Project -> Issue reverse synchronization.

The Health Issue also contains coverage, drift/error counts, Actions run reference, `Direct Verification Requirement`, and the currently unresolved scoped/global failure identities.

The Health Issue is kept closed so the Project Auto-add filter `is:issue is:open` does not normally add it. Event-sync ignores the Health Issue before Project access to prevent recursion. If it is already present in the Project, `reconcile` removes that Project item.

## 5. Normal verification path

A normal ChatGPT session that cannot directly read the private Project should check, in order:

1. `[SYSTEM] GitHub Project Sync Health`
2. the devflow Repository Control Issue `[REPO] devflow`
3. active Work Order / relevant Repository Control Issue
4. relevant Actions run/logs when Health is not `PASS`

A `PASS` result means the implemented API-verifiable synchronization checks passed at the recorded run/time **and the bounded unresolved-failure memory is empty**. An unrelated successful event cannot clear another Issue's remembered failure. `PASS` still does not claim that UI-only properties outside API coverage were directly observed.

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

For audit freshness, the synchronizer also consumes the read credential already used by the Stage-2 maintenance auditor:

`MAINTENANCE_AUDIT_TOKEN`

That credential is used only to resolve the explicit repository/ref named by `Audit Ref`. Missing/unresolvable read evidence yields `Audit Freshness = UNKNOWN`; it does not authorize Project -> Control reverse writes or repository mutation.

For recreation or credential rotation, use a Project-capable personal access token and save only the token value as that repository secret.

Do not place the token in source code, Issue bodies, workflow YAML, comments, or logs.

After credential recreation/rotation, run full `reconcile` then full `verify` and confirm Sync Health returns an accepted state before considering the credential change complete.

When audit Project fields are introduced or structurally changed, use explicit full `reconcile` to create/validate them, then full `verify`, followed by direct Project inspection because field structure is an API/UI structural boundary. Event sync and ordinary verify do not create Project fields.

### Failure prevention (#406)

Transient GitHub GraphQL transport failures (HTTP 502/503/504 and transport
timeouts) are retried with bounded backoff (at most three attempts) **only** for
read queries and idempotent `updateProjectV2ItemFieldValue` mutations that set
the desired field value. Failed add/remove/schema mutations, 4xx, and GraphQL
validation errors are not retried: an indeterminate write must not be repeated
without proof of safety. Exhausted retries remain explicit failures.

After event-sync writes, a missing Project member in immediate readback triggers
at most two extra read-only Project snapshot checks with short delays. No
additional mutation is attempted in that loop. Persistent absence still fails
and remains in Sync Health. This guards against possible read-after-write
visibility lag; its occurrence was hypothesized, not conclusively established.

Every run emits a bounded, non-sensitive diagnostic summary: current-run
membership/field drift and error counts, separately from the keys of
unresolved retained failures and the final aggregate result. The summary never
prints credential values or raw canonical Issue/Project text. An event whose
current write/readback is clean can therefore be recognized even when an older
unresolved failure keeps the aggregate exit status red. **Fail-closed health and
failure-memory clearing semantics are unchanged.**

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

The GitHub repository was renamed from `kinoko34077/devflow-test` to `kinoko34077/devflow` on 2026-09-25. Work Order `#46` completed the migration acceptance and is closed.

Historical Issue/PR/commit references may retain the old repository name where they identify historical events. Current operational identity is `kinoko34077/devflow`.

Accepted evidence:

1. repository metadata resolves as `kinoko34077/devflow`;
2. Issues, PRs, Actions, default branch and branch protection remained usable;
3. required repository secret/configuration remained effective without exposing secret values;
4. Project Auto-add was directly verified to target `kinoko34077/devflow` with filter `is:issue is:open`;
5. full `reconcile` Run #63 (`36138740200`) succeeded on `main`;
6. full `verify` Run #64 (`36138826213`) succeeded on `main`;
7. Sync Health recorded full coverage with drift `0`, errors `0`, and `Direct Verification Requirement: NONE`;
8. Repository Control was migrated to `[REPO] devflow` and returned to `AUDITED / ACTIVE` normal operation;
9. Project remains display-only and no reverse Project -> Issue workflow is enabled.
