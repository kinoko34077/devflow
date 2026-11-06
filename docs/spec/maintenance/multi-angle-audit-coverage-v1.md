# SMC multi-angle audit quality and conservative coverage — M0–M3 candidate

Status: scoped implementation candidate under [devflow #588](https://github.com/kinoko34077/devflow/issues/588).
Authority: the accepted [SMC #363](https://github.com/kinoko34077/devflow/issues/363) v1 baseline and implementation are unchanged. This file adds a **read-only evaluation rubric and conservative coverage projection**; it does not itself upgrade runtime rollout, publisher, credentials, Project, or claim authority.

## 1. Distinguish definition, execution, credit, and presentation

- Definition: devflow `common-baseline.v1.yaml` owns the shared 12 Lens IDs and defaults. Each participating repo owns its `.devflow/maintenance.yaml` overrides and risk. Never copy a second common baseline into a consumer.
- Execution: the actual read-only/normal tests/review must run on a trusted source. Slot selection, published candidate, queue, Claim or Issue existence is *not* an executed audit.
- Evidence: the standing repository `[MAINTENANCE] Audit Ledger` holds authenticated `devflow-maintenance-run:v1` comments; material DEEP audit and mutations promote to a bounded local Issue. Actual changed code/spec/test evidence belongs to its repository.
- Credit: a projection must tie `repository × scope × lens × depth × source fingerprint` to the evidence that was actually checked. Neither global `Audit Depth=DEEP` nor Audit SHA alone implies all lenses complete.
- Presentation: current audit table and Project/Repo Monitor are derived non-canonical views. `NOT_RUN`, `NO_COVERAGE`, stale and unknown must be distinguishable; no auto-green/default dates.

## 2. Lens review procedure (existing IDs; no baseline schema changes)

| Existing Lens ID | Questions/negative cases | Required verification evidence |
| --- | --- | --- |
| correctness | Does current source satisfy the accepted functional contract? Wrong outputs, path branch, precision | Exact source rev, representative positive/negative expected-vs-actual test, open finding refs |
| edge-cases | Empty, null, Unicode, large, malformed, overflow, cancellation; domain-relevant limits | Boundary-case test inputs/results and justified missing domains |
| reliability-recovery | Crash, retry, restart, partial commit, interrupted session, rollback | Recovery proof, replay disposition, before/after evidence, fail-closed adverse case |
| security | Auth/principal, secret exposure, input injection, execution, dependencies, data, permission, failure | Relevant trust boundary, positive + negative authorization probes without leaking secrets |
| state-integrity-concurrency | Duplicate actions, races, stale read/write, contention, owner/lease/fence | Deterministic conflict/replay/stale-generation tests and authoritative state evidence |
| spec-implementation-drift | Accepted requirements vs actual code, published artifact vs main, obsolete TODO | Exact spec and source paths/refs; mismatch/fixed/unknown list, not wordsmithing |
| test-quality | Assertions, missed negative paths, mocked vs real boundary, flakiness | Real tests/CI step evidence + limitations and missing tests, not only test count |
| resource-management | Memory leaks, unbounded work, subprocess cleanup, time/cost/perf | Reproducible environment, measured limits/cleanup and comparison scope |
| dependency-external-assumptions | GitHub Actions pins, libraries, API/clock assumptions, external freshness | Lock/version and dated external-source evidence; code SHA alone is insufficient |
| error-handling | Timeouts, denied access, malformed response, unknown effect, partial rollback | Exact failed operation, actor, smallest recovery and checked exit condition |
| observability | Logs/alerts/metrics permit detecting loss, latency, failure or suppressed errors | Genuine diagnostics/traces, blind spots and actionable escalation path |
| lifecycle-consistency | Issues/PR/CI/review/Control/Session/Project current-state contradictions | Exact live owner/HEAD/CI/Review refs, resolution and preserved historical notes |

Scope and risk can make some checks inapplicable. Record the rationale and what *remains uncovered*; never silently remove Security coverage. A generic Lens does not automatically certify every component or runtime boundary.

## 3. Audit depth and attribution

- `CONTROL`: source/owner/Issue/routing audit, no repository-code coverage implied.
- `STANDARD`: bounded substantive examination of the named scope and Lens with checked evidence and negative cases appropriate to risk.
- `DEEP`: explicitly justified broader/deeper bounded examination; never a blanket whole-repo/all-lens pass, and never infer that a DEEP record proves an unrelated Lens.
- A finding's **severity** is separate from work scheduling **priority**. Confirmed dangerous P0/P1 and risk-significant Security findings interrupt and attach to owner; low-priority findings normally recorded and audit continues.
- Audit status values in the v1 **derived view** are not new worker states, Issue statuses, selector outcomes, or accepted canonical `RunRecord` enums.

## 4. Repository type archetypes (adoption recommendations, not live catalogs)

| Type of repository | Extra candidates requiring actual source validation | Example boundaries |
| --- | --- | --- |
| Web/UI/Pages | keyboard/touch, a11y, real browser, payload/asset and public deployment | Separately prove public HTTP and physical Safari if claimed; never infer one from CI |
| VST3/DSP/audio | bitwise/phase/spectral correctness, DAW automation IDs, audio callback latency | Deterministic WAV/sample-rate fixtures, native plugin host evidence, RT-safe allocations |
| API/Worker/auth | request input, tenant isolation, secrets, rate/quotas, effect replay | Positive/negative principal tests, dry-run before any side-effect |
| Infrastructure/agents | Issue/PR/claim/current-state truth, credentials, concurrency, loss recovery | Exact-native Review, fenced claims, failed CI without runner steps, no bypass |
| Numerical research/simulation | reproducibility, units, falsifiability, seeds, provenance, tolerances | Independent baselines, exact environment/random seed, negative and underpowered evidence |
| Transformation/orthography | Unicode, idempotence, stream chunking, source-rule fidelity, size constraints | Golden fixture parity, source model, boundary and real payload distribution |
| Docs/reference-only | provenance, links, accepted decisions, reproduction steps | Verify canonical links/commands; security still applies at lower justified cadence |

This table is *not* a fixed risk classification or permission to adopt all candidates. M2 must inspect actual repo Current State, architecture, accepted Issue/PR, generated/third-party origins, dependencies and risk overrides. A catalog change needs its own owner, branch, validation, review and accepted merge.

## 5. M0 real Ledger evidence inventory (2026-10-16 JST observation)

Three accepted catalogs/standing Ledgers read: devflow #367 (5 recorded runs: 2 substantive CLEAN/FINDINGS + 3 BLOCKED zero-credit), execution-coordinator #127 (1 CLEAN), kinotch-repository-base #50 (1 FINDINGS). 7 total recorded completion events **are not 7 completed audits**. A report must carry exact source comment IDs and trusted author evidence before credit.

**Important v1 provenance gap:** completed `RunRecord` does NOT store immutable `scope`, `coverage_key` or `catalog_digest` even though `ActiveRun` includes the latter two while active. Thus the historical run cannot automatically prove the *present* meaning of its slot name after catalog change. The conservative `tools/maintenance_coverage.py` projection shows `LEGACY_SCOPE_UNBOUND` for an otherwise matching substantive v1 record: **this is useful historical evidence, not independently accepted current scope coverage**. Later M4 must decide whether to introduce an opt-in versioned immutable completed-run envelope and migration/attestation evidence; never backfill scope or SHA by inference.

## 6. Read-only coverage projection v1 interface

`derive_coverage(resolved_slots, evidence_envelopes, current_fingerprints, depths=("STANDARD","DEEP"))` emits deterministic per-active-slot rows with current *display* scope from validated catalog. The source observation must supply actual resolved slots/fingerprints and trusted Ledger comments; the helper performs **no GitHub calls** and has **no write side effects**.

Result states:
- `NOT_RUN`: no machine run comment for the slot/depth.
- `UNTRUSTED`: comments exist, but no source/author association can be accepted.
- `AMBIGUOUS_HISTORY`: conflicting records share a run ID.
- `UNKNOWN_FINGERPRINT`: source freshness cannot be safely resolved.
- `NO_COVERAGE`: latest trusted result BLOCKED/SUPERSEDED/NEEDS_REAUDIT.
- `SOURCE_DRIFT`: current source fingerprint differs from the historical completed record.
- `LENS_DRIFT`: current Lens no longer matches recorded Lens.
- `INSUFFICIENT_EVIDENCE`: no supported completed result or missing evidence links.
- `LEGACY_SCOPE_UNBOUND`: substantive v1 run/fingerprint/Lens/Depth match but the old scope/catalog identity is not securely attestable.

The source URL/author association must be obtained from the real owning Ledger via GitHub API (OWNER/MEMBER/COLLABORATOR). An external assertion about trust is not sufficient by itself. A current fingerprint must incorporate relevant external/dependency freshness where necessary; no SHA-only freshness shortcut. An archived comment merely containing a sentinel or comment-like text is not an accepted audit.

## 7. M4–M8 release gates

- **M4:** decide v2 provenance binding and maintain backwards-compatible v1 read-only view; negative tests for partial write, duplicate/stale run, denied reviewer, claim collision and external-source change; preserve 3C.
- **M5:** run heterogeneous real positive+negative scope audits and compare materially useful findings/false positives/cost against read-only derived selection; verify claim withdrawal.
- **M6:** each new repo onboarding must have its own owner, profile validated from code, existing Control + Issue/PR, single Ledger, tests, exact-head review, and explicit bounded adoption decision. User's broad M0–M8 directive does **not** itself override security/credential/release or grant blanket `ENABLED`.
- **M7:** only project accepted readings through existing Project/Repo Monitor authority; no independent freshness implementation, writable second truth or huge manually maintained spreadsheets.
- **M8:** after accepted rollback/security/recovery/regression proof, report true coverage and noncoverage for each admitted repo; any unproven effect stays HOLD with a concrete actor/action/recheck.

No new per-repo schedule, privileged credential, third-party dependency, auto-publisher, or silent fleet activation is authorized by this M0–M3 document.
