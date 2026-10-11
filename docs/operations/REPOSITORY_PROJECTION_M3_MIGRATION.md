# Repository Projection M3 — staged removal of duplicate manual local-work state

Status: **M3 PREFLIGHT / SHADOW ONLY — authority transition not admitted**  
Owner: [devflow #326](https://github.com/kinoko34077/devflow/issues/326)  
Bounded implementation/evidence: [devflow #452](https://github.com/kinoko34077/devflow/issues/452)  
Accepted authority direction: [devflow #325](https://github.com/kinoko34077/devflow/issues/325)  
Accepted transport: M2 [devflow #342](https://github.com/kinoko34077/devflow/issues/342)  
Scope: all seven M3 migration items, *not* M4 operator-view additions.

## 1. Non-negotiable authority boundary

The owning repository's Issues, PRs, specifications and Current State remain canonical for repository-local work. devflow's trusted Repository Projection is a **derived read model**; its central, marker-owned Control cache is transport/display evidence. It must never become a second writable task database, a task supplier, or execution-coordinator claim authority. The devflow Control remains canonical for managed lifecycle, cross-repository dependencies, explicit Human/security decisions, accepted audit provenance and cross-repository Next Action.

**No fleet-wide switch is approved.** Before bounded M3 admission, manual Control `Active Work` and `Detailed Current State` remain compatible/required as before. This document is the migration plan and evidence matrix, **not the change that removes them**. Workstream statuses/priority may be read from Issue metadata only when their exact own-authority evidence is trusted and current. A machine cache `READY` record is **not** permission to run code or create a runtime claim.

## 2. Observed genuine task lifecycle

A real, owner-authored M3 work item [devflow #452](https://github.com/kinoko34077/devflow/issues/452) began with trusted V1 metadata `TASK / READY_FOR_IMPLEMENTATION / scope_ready=true`, and was moved to `IMPLEMENTING` when actual M3 work began.

| Source state | Native M2 producer | Control #16 machine projection | Human Portfolio |
| --- | --- | --- | --- |
| READY_FOR_IMPLEMENTATION | [run #38182213582](https://github.com/kinoko34077/devflow/actions/runs/38182213582) SUCCESS | `tasks.ready=[#452]` | `#452 READY`, VERIFIED |
| IMPLEMENTING | [run #38182294385](https://github.com/kinoko34077/devflow/actions/runs/38182294385) SUCCESS | `tasks.implementing=[#452]` | `#452 IMPLEMENTING`, VERIFIED |

In both runs devflow had **78 open Issues, 2 machine records (1 TASK and 1 TRACKER), 3 legacy hints, 73 unclassified, 0 invalid/untrusted**; `coverage.status=INCOMPLETE`, `coverage.can_replace_manual_active_work=false`. Only the **owning Issue** changed its work state; central fenced Producer updated generated marker blocks. No manual Control `Active Work` edit was necessary for this step. Evidence of automatic projection is not proof that manual fields can already be removed.

The rest of this Issue's true REVIEW/terminal lifecycle, if reached, must be evaluated against a fresh native producer and noncolliding consumers; do not assign fictitious statuses to generate test cases.

## 3. M3 per-repository admission — fail closed

Evaluate one repository independently from the others. Require **all** applicable conditions before removing any manually maintained local-task authority:

1. **Trusted source:** exactly one current, verified canonical devflow Control; correct owner/repository identity; direct/accepted bootstrap provenance; live owning Issue source authoritative. Fail if missing, duplicated, untrusted or inconsistent.
2. **Freshness:** actual live Issue observation and central M2 cache source must be `AVAILABLE/CURRENT`, valid and not expired; trust and generation identity must match its accepted parser. Stale, UNKNOWN, UNAVAILABLE or generation/digest disagreement => legacy/manual fallback; do not silently report zero tasks.
3. **Machine coverage:** `coverage.status=COMPLETE` with zero legacy hints, unclassified open Issues, invalid metadata, and untrusted metadata. A partial sample of genuine TASKs does not justify suppressing *other* active Issues. Do not mass-backfill history or invent TASK to force a green count.
4. **No truncation/lost task or state:** current M2 Control cache exposes *only* `tasks.ready` and `tasks.implementing`, each capped to at most 20 summaries (`MAX_TASK_SUMMARIES=20`). A valid open TASK in `AWAITING_REVIEW`, `BLOCKED`, `NEEDS_REAUDIT`, etc. is **not** included in these two lists. Neither `machine_task_count` nor `newest/recently_active` references recover the full active lifecycle. Therefore **even COMPLETE source coverage is insufficient on its own** to replace manual Active Work. Before admitting replacement, an accepted current and complete all-state task read path (e.g. bounded live Repository Projection `task_records`, not a new task store) must represent *every* relevant open TASK without truncation, under exact trust/freshness and consumer verification. >20 relevant items or missing statuses require a reviewed transport before any active-work authority switch.
5. **Statuses and gates:** TASK/TRACKER/REFERENCE/SYSTEM roles must remain distinct; true READY/IMPLEMENTING lifecycle and explicit Human/security/external/dependency/review gates must be preserved. Reconciler/SMC runtime claim/offer cannot be derived from a displayed queue. Non-task open Issues cannot be assumed runnable.
6. **Consumer agreement:** devflow MCP, Control cache, Human Portfolio, Repo Monitor, Project Sync, bootstrap/manual reader, maintenance audit, and any active external consumer must resolve the *same* canonical Issue refs and safe fallback on unavailable/legacy sources. Record at least one genuinely completed ready→implementing→terminal cycle and verify no duplicate manual Control edit was required.
7. **Authority safety & rollback:** explicitly accept one bounded repository's M3 cutover with native tests/Review and safe revert path, and check live affected consumers immediately before activating. The current M2 `can_replace_manual_active_work` bit is deliberately hard-coded `false`; do **not** flip it from merely observing some machine TASKs, and do not treat this preflight document as its replacement.

A zero-open-task repository can still have complete machine coverage, but **zero work is not evidence of an active TASK lifecycle**. If any of the above are unproven, keep the manual Control sections and record the bounded missing proof.

## 4. Consumer and producer change map

| Existing surface | Current relevant reliance | M3 change/admission boundary |
| --- | --- | --- |
| Owning repository Issue / PR / Current State | Detailed local state/decisions | Remains canonical, no second task store |
| `tools/repository_projection.py` | V1 metadata trust/role/status classification | Preserve role, trust, explicit gate and fail-closed semantics |
| `tools/repository_projection_cache.py` | M2 machine cache, freshness/counts; **ready/implementing only** with 20-entry per-list cap; `can_replace_manual_active_work=false` | Keep false until an all-state, nontruncated canonical task read path and explicit per-repo admission exist; do not silently treat missing review/blocked tasks as zero work |
| `tools/repository_projection_cache_producer.py` / central Actions | Fenced marker-owned cache production and readback | No per-repo synchronization workflows; exact Control body digest and atomic dual-marker writes remain |
| `tools/devflow_mcp_core.py` and `tools/workflow_contract.py` | Read trusted Control manual sections; separate machine projection/Human Portfolio | Provide staged trusted projection view with legacy fallback; do not drop manual parsing prematurely |
| `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`, `AGENTS.md`, `.github/ISSUE_TEMPLATE/repository-control.md` | Current required `Active Work`, `Detailed Current State`, manual `Next Action` | Change requirement/read order/template **only with explicit admission**, while preserving legacy Control compatibility |
| Bootstrap, Project Sync, maintenance audit and other Control consumers | Manual Control status/owner/readiness can still be consumed; own risk/gates | Inventory each affected path, use verified projection first only after consumer regression and real cache evidence; keep fail-closed legacy behavior |
| `kinotch-repo-monitor` #32 and #46 | Read-only Human Portfolio/Projection consumer, own task/agent status not inferred locally | Consume shared devflow classifications; do not implement a second metadata classifier or cause an unsolicited public Pages deployment |
| Execution-coordinator / SMC | Own runtime offer, claim and lease authority; separate standing maintenance admission | No change or automatic supply from a machine cache/task readiness field |
| GitHub Project | Derived display | No Project → Issue reverse synchronization |

## 5. Stage sequencing and milestone acceptance

- **M3.5 evidence first:** #452 genuine READY→IMPLEMENTING native cache and Human Portfolio proof accepted. Need terminal/closed source re-read and negative stale/legacy/gate cases, not merely a mock.
- **M3.2/M3.3 preparation:** define proposed reduced Control structure in reviewed spec; retain old sections until admission. New required Control remains canonical for lifecycle/audit/cross-repository Human policy, with `Next Action` for cross-repo/Human/policy only; local implementation next action belongs to the local Issue.
- **M3.4 + M3.6 staged consumer migration:** after per-repo admission, switch read precedence under a feature/transition rule with explicit fallback; align AGENTS, bootstrap, Control templates, MCP, Repo Monitor and Project/maintenance consumers in dependency order; verify actual old and new Controls.
- **M3.1 authority retirement:** stop treating manual local `Active Work` as source of local TASK truth **only for explicitly verified cohorts**. Do not delete owner/provenance information that has an independent cross-repository role.
- **M3.7 cleanup:** retire obsolete compatibility paths only after no current consumers/repositories depend on them, with regression and a reversible migration record; never remove legacy reads solely for tidiness.
- **M4 separate:** after M3, use evidence to choose optional dashboard/Project fields or `NOT_NEEDED`. No new scheduler/database.

Each milestone receives an evidence pointer, review classification under accepted [#111](https://github.com/kinoko34077/devflow/issues/111)/[#439](https://github.com/kinoko34077/devflow/issues/439), exact current SHA/CI, rollback path, and a parent #326 checkbox **only when that milestone's own acceptance is satisfied**.

## 6. Current decision and resume

**GO:** continue #452 real TASK lifecycle, read-only shadow reconciliation and narrow source/test/docs updates that are justified by an unmet M3 criterion.  
**HOLD:** broad manual Active Work/Current State/Next Action removal, fleet-wide admission and cache flag flips while source coverage/consumer or trust evidence is incomplete.  
**SPLIT:** a concrete consumer integration failure to its owning repository Issue; do not take over other active workers.  
**STOP:** redundant synthetic tasks, second classifier/database, speculative zero-value tests, uncontrolled cross-repository rewrite and unrelated M4 work.

To resume: read devflow `AGENTS.md` → Control #16 → parent #326 Cursor → child #452 Cursor/evidence → this document and current source/consumer state. A new worker must re-check live readiness, statuses and source SHA; the document is **not** runtime claim, activation approval or independent-review evidence.
