# Repository Projection M3 — adopted A–E operating model

Status: **USER-APPROVED OPERATING DIRECTION / STAGED IMPLEMENTATION** (2026-10-12 JST).
Implementation owner: [devflow #477](https://github.com/kinoko34077/devflow/issues/477).
Parent roadmap: [#326](https://github.com/kinoko34077/devflow/issues/326); existing M3 admission owner [#452](https://github.com/kinoko34077/devflow/issues/452).
Accepted authority policy [#325](https://github.com/kinoko34077/devflow/issues/325); existing implementation and strict M3 transition contract: [REPOSITORY_PROJECTION_M3_MIGRATION.md](REPOSITORY_PROJECTION_M3_MIGRATION.md).

The user's approval applies to all five operational approaches **A–E**, with their distinct purposes. It does **not** imply that unimplemented features, cohort admission, external publication, permissions or execution rights are already enabled. Accepted previous M0–M2/M3.2/M3.5 milestones remain accepted; all other M3 milestone boxes remain evidence-gated.

## 1. Authority and what must never change

1. Repository-local Issues/PRs/specifications/Current State own **local work truth**. devflow owns cross-repository Control/lifecycle/Human/policy facts. GitHub Project is display-only.
2. Only the existing devflow Repository Projection may classify source Issue metadata. Do not create another task database, another role classifier in Repo Monitor, or per-repository sync workflows.
3. **Reading/display** is not **complete local-work authority**, and neither one grants **runtime offer/claim/lease, write, merge, release, security or Human permission**. execution-coordinator / Maintenance supply / reviewer/Human gates retain their own source authority.
4. Missing/legacy/unclassified/untrusted/invalid/stale data is never silently ignored. Never interpret zero machine TASKs with incomplete coverage as zero actual work.
5. Existing M2 cached summaries include only READY/IMPLEMENTING capped at 20 each. They are NOT all-state work authority; the M1-derived live `get_repository_work_view` preserves review/blocked/open-DONE states.
6. `can_replace_manual_active_work=false` remains unchanged until separate, exact-cohort M3.1 approval, native verification, consumer agreements and rollback. Existing manual `Active Work` and `Next Action` stay authoritative in the meantime.
7. Existing owned Issues, security gates and independent worker sessions must not be overridden for a migration pilot.

## 2. Adopted approaches (roles, not alternatives)

| Approach | Standard operating decision | Acceptance boundary |
| --- | --- | --- |
| **A: bounded full classification** | Classify every open Issue by *actual* role only in a carefully selected, real, nonempty low-collision pilot repository; test strict COMPLETE → consumer admission. Not a fleet-wide backfill policy. | Genuine open TASK, zero unresolved roles, trusted/current Control and Issue source, no synthetic status/issue, other-owner collision check and per-consumer recovery. |
| **B: normalize on creation/material edit** | New Issue and materially edited active Issue receive validated role/appropriate V1 or future version metadata; don't churn on comments/closures, mass-backfill history or infer executability from title. | Tests/documentation for safe templates and parser, no additional manual second-state store. |
| **C: split information use from authority** | Expose trusted known TASKs even under partial coverage **alongside exact unresolved counts/status**; reserve authoritative *complete* task-list substitution for independently verified COMPLETE, and runtime execution for its existing authority. | No machine-state fabrication, no loss of review/blocked/DONE, explicit source freshness/trust, fallback to manual Control for authority, not for erasing partial evidence. |
| **D: migrate by consumer** | Move read-only MCP/Repo Monitor visibility first; bootstrap/Project semantics next; effectful Maintenance/owner-sensitive paths last, each with a rollback. | Each consumer's actual read/write/permission semantics, source identity, stale/untrusted handling, CI/Formal Review and live rollback proven. Pages deploy/publication requires explicit separate clearance. |
| **E: lightweight non-TASK declaration** | Add versioned, backward-compatible, low-burden trusted role metadata for TRACKER/REFERENCE/SYSTEM, with an *explicit* gate/unknown policy; keep TASK requirements strict and V1 valid. | Never let a role-only assertion silently mean 'no Human, external, evidence or security gate'. Human Portfolio and coverage regressions pass before accepting as complete. |

## 3. Use-level matrix

These are **proposed use levels, not existing schema or rollout flags**:

| Use level | Input / required evidence | Allowed behavior | Never implies |
| --- | --- | --- | --- |
| `OBSERVED_PARTIAL` | Live AVAILABLE/CURRENT trusted machine TASKs, and explicit unresolved counts/status; may have legacy/unclassified | Read-only display of known TASKs with visible incompleteness | Complete task coverage, no other work, local authority removal |
| `COMPLETE_READ` | Exactly verified Control/repo identity, live complete M1 full list, AVAILABLE/CURRENT, unresolved=0, full role+gate semantics, no truncation | Assert all open TASKs are accounted for **as read evidence** | Runtime task claim or local authority switch |
| `LOCAL_AUTHORITY_ADMITTED` | All COMPLETE_READ evidence **plus** real nonempty lifecycle, per-repo accepted consumer equivalence, reversible scoped deployment/rollback | Selected consumer may cease treating manually duplicated local task data as authority | Executor supply/claim, reviewer/Human/security bypass |
| `EXECUTION_AUTHORIZED` | Independent runtime/reconciliation/Human/security/review grants for the specific action | Only precisely allowed action | General repo or fleet-wide authorization |

The first three are logically separate. Do not implement a new executor permission or replace current `coverage.status` merely by naming them.

## 4. Day-to-day issue lifecycle and classification

- **New TASK:** require the accepted action-relevant metadata, using trusted author/source. Work state reflects reality; READY requires actual scope readiness, and explicit Human/external gates are never assumed false.
- **New non-TASK:** V1 is currently valid; after E is independently accepted, use the supported minimal schema with truthful gate/unknown contract.
- **Meaningful changes to an active Issue:** normalize if its true role and necessary gates are known, respecting an owner/session boundary. Do not convert `[BUG]` titles or a stale prose hint into an executable TASK automatically.
- **Comments/Close or old idle Issues:** no classification-only bulk edits. Keep stale or unknown issues visible. Historical closed Issues do not need mass rewrite.
- **Untrusted/malformed/duplicated metadata:** remain fail-closed and observably invalid. An explicit untrusted block must never be rescued by title guessing.
- **PARKED:** don't manufacture readiness to silence an attention entry. Non-gated PARKED work should not create Human action; real explicit Human/external/dependency gates still show.

### Lightweight non-TASK (E) safety contract to resolve before code

A `schema_version=2` role-only snippet is **not automatically admitted** as COMPLETE, because omitted `requires_user_confirmation`, `external_wait`, `scope_ready` could conceal actionable attention. Choose and test one **explicit** contract before enabling:
1. Minimal role plus an explicit reviewed gate/attention declaration (e.g. reviewed `attention=NONE|NEEDS_HUMAN|WAIT_EXTERNAL|NEEDS_EVIDENCE`), preserving truthful explicit gates; **or**
2. Minimal role alone marked `gate_status=UNKNOWN`, only a partial classification, **not** eligible for automatic COMPLETE/local-authority admission until the unknown is resolved.

Both require backward-compatible V1 parsing, duplicate/mixed-marker rejection, strict TASK fields, correct source-author trust, and Human Portfolio evidence tests. Never silently default unknown gate fields to `false`. Contract selection belongs to R3 evidence and review.

## 4A. Explicit user-approved dual-read transition (2026-10-12 JST)

The operator's preferred M3 migration is **traditional/manual and machine-derived work shown side by side, followed by a gradual change in read precedence**. This is adopted as the default implementation pattern of A/C/D and *supplements*, rather than relaxes, the preceding gate contracts.

There are **not two write authorities**: only repository-local Issues/PRs own local task facts; the existing M2 machine block is automatically projected by the central producer; `Active Work` is legacy manual summary/cross-repository operational context. Do not require users to edit both fields after each task transition. Keep meaningful Human/policy and cross-repository facts in the Control until independently migrated.

| Stage | What operator sees | Which source determines local-work action? | Promotion/rollback |
| --- | --- | --- | --- |
| **P0 DUAL_READ** (default now) | Existing Control `Active Work` / `Next Action` beside verified machine TASK refs + state, unresolved counts, timestamps/source health | Existing manual Control/owning Issues, never machine-derived runtime authority | No auto promotion. If source absent/stale, machine side says **unknown**, not empty. |
| **P1 SHADOW_CROSSCHECK** | Both, plus source/link overlap and tracked differences/reasons; historical manual links are *not* classified as current TASK | Manual remains the operational fallback; no execution change | Collect genuine examples across READY/IMPLEMENTING/REVIEW/BLOCKED, Human/external gates and source failures. Exact link overlap is insufficient to prove semantic equivalence. |
| **P2 PER_CONSUMER_MACHINE_READ** | Machine first, legacy still visible/readable for rollback; unknown/unclassified distinctly shown | Only a **specifically admitted read-only Consumer** may prefer machine display; effectful ownership/claims unchanged | Require real nonempty COMPLETE/CURRENT/trusted cohort, actual Consumer equivalence, review/CI and independent rollback. An observational phase does not confer task authority. |
| **P3 MANUAL_LOCAL_WORK_RETIREMENT** | Legacy local-task summary deprecated for *verified admitted cohort*; cross-repo/Human/policy Control text retained | Owning repository machine-readable work is the local read authority for admitted Consumers only | Actual M3.1 sign-off and exact per-Consumer fallback; leave non-admitted repositories at P0/P1. Do not globally flip hard-false cache flag. |

**Machine-read API transport:** existing `get_repository_work_view` returns `manual_control`, `task_records`, `observed_task_view`. The additive `parallel_read` groups the same live facts for side-by-side display and reports **only exact local Issue-URL overlaps**. Links to closed/history/parents can occur in manual prose: neither overlap nor lack of overlap is a semantic consistency judgment or permission. `parallel_read.can_replace_manual_active_work=false` and `can_authorize_execution=false` at P0/P1. This is not a second task store or a replacement for the already accepted Maintenance shadow preflight.

**Operational transition rule:** keep machine projected by existing producer, not separately hand-maintained; retain manual as the current fallback with no forced full historical transcription. When two views disagree, read the original owning Issue/PR and inspect freshness/role/trust before labeling a defect. The source-of-truth discrepancy is recorded to its owning Issue; do not blindly copy manual text into new machine metadata. Each Consumer's precedence/rollback is accepted independently. Other repositories do not inherit one pilot's sign-off.

## 5. Consumer deployment order and fallback

1. **MCP**: reuse existing all-state M1 read, show known and unresolved counts; `can_replace_manual_active_work=false` during observational stages.
2. **Repo Monitor (display only)**: first verify existing cache and display behavior; build only the missing non-mutating surface, no second classifier, no unsolicited Pages publication.
3. **Project Sync / AGENTS / Bootstrap**: preserve local issue references and independent cross-repo Next Action; compare old/new Controls, don't strip manual headings until migration conditions hold.
4. **Maintenance**: `tools/maintenance_github.py` currently has opt-in `m3_shadow` for comparison only; `maintenance_audit.py` is single-owner-oriented, and multiple genuine TASKs are not one unique Maintenance owner. Keep maintenance-specific owner/candidate/ledger contract separate from the general local-work list; don't infer supply or authorize execution from a display list.
5. **M3.1 active cutover**: only for explicitly admitted one-repo/one-consumer cohort; test negative source, empty vs nonempty, stale, duplicate, different Control revision, multi-TASK, reviewer/Human, rollback, and current concurrent producers. Revert PR and restore manual reader on failure; do not backfill or rewrite another worker's state.
6. **M3.7/M4**: retire confirmed-unused compatibility code only; optional view fields require demonstrated decision value.

## 6. Rollout checkpoints and metrics

Detailed execution/acceptance tracked in [#477](https://github.com/kinoko34077/devflow/issues/477) (R0 through R7). Distinguish **R0 contract acceptance** from **R1–R7 actual implementation or live migration**.

Measure separately:
- Classified open Issue fraction (`machine_records/open_issues`) and unresolved legacy/unclassified/invalid/untrusted breakdown.
- Nonempty `COMPLETE_READ` repository count (empty COMPLETE is not a real task lifecycle).
- Number of **read-only migrated consumers** vs number of **local authority-admitted consumers/repositories**.
- Fail-closed, stale, gate, multi-TASK and revert checks per admitted cohort.
- Number of manual updates removed per actual local task status change, without counting automation-generated cache writes as human work.

Initial evidence: prior 49 cached Controls, 204 open Issues, 2 machine records, 1 TASK; 24 COMPLETE all zero-open and 25 INCOMPLETE. Those snapshots were generated at different times, so **do not present them as a contemporaneous live full-fleet read**.

## 7. Immediate order / blockers

1. R0 accepted contract/roadmap via reversible PR + Required + Formal Review. No authority change.
2. R1 and R2 bounded additive implementation using current V1/source model; separate commits/PRs if ownership/safety requires.
3. R3 explicit E gate semantics design then parser/portfolio regression; no invented easy shortcut.
4. R4 genuine nonempty full-classification admission pilot after selecting a real, low-risk, non-colliding owner.
5. R5 read-only display consumer; R6 actual guarded M3.1 only after admission; R7 cleanup/optional M4.
6. If no genuine eligible cohort, HOLD effectful authority and continue only clearly justified independent R1/R2/R3/consumer work. No synthetic issue or status mutation merely to reach metrics.

Review and verification: native tests, exact-head PR Required CI, Formal Review according to [#111](https://github.com/kinoko34077/devflow/issues/111)/[#439](https://github.com/kinoko34077/devflow/issues/439), guarded merge and post-main Required; evidence and first unfinished tracked in owning Issues.
