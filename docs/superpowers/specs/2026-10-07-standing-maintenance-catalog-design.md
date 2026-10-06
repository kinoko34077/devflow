# Standing Maintenance Catalog + Idle Fallback Audit Supply — Design

Status: USER APPROVED 2026-10-07 / IMPLEMENTATION PLAN REVIEW REQUIRED
Owning Issue: devflow#363
Scope: cross-repository maintenance supply, recurring audit rotation, durable audit progress, finding escalation, and broad-work fallback
Implementation authority: not released by this document

## 1. Purpose

This design defines how a managed KiNoTch. repository can expose recurring maintenance/audit work as predefined legitimate work, so an otherwise-idle GPT/agent can continue with useful bounded work without inventing synthetic tasks.

Target order:

    recoverable work
    -> normal runnable work
    -> predefined maintenance due/old/useful
    -> alternate lens / deeper audit / another repository
    -> portfolio maintenance
    -> NO_ELIGIBLE_WORK only when no materially new evidence is expected

The objective is useful inspection coverage, not worker occupancy for its own sake.

## 2. Non-goals

This design does not:
- make idle state itself a task source;
- create a second queue/scheduler/claim authority;
- weaken Human/security/release/deploy/credential/session/permission gates;
- convert every observation or improvement idea into an Issue;
- permit blind repetition of the same audit;
- replace Stage-2 maintenance audit/triage;
- replace devflow#249 broad backstop auditing;
- replace execution-coordinator claim/lease/generation/fencing;
- authorize implementation merely because this draft exists.

## 3. Authority model

### 3.1 Single-canon rule

Each kind of information has exactly one canonical owner.

- shared Common Audit Baseline definition: devflow;
- repository-specific maintenance definition: owning repository;
- lightweight run history/checkpoints: repository standing Maintenance Ledger Issue;
- complex/deep run progress: bounded owning Audit Issue;
- runtime claim/lease/fencing: execution-coordinator;
- cross-repository aggregation/selection: derived devflow read model;
- UI/Control/Project views: projection only.

The same semantic field must not be maintained independently in multiple authorities.

### 3.2 Definition, history, and projection are separate

Catalog definition = what should be audited.
Ledger / bounded Audit Issue = what was actually audited and what happened.
Machine projection/cache = what currently appears due, stale, uncovered, or eligible.

The projection is derived and disposable. It must be reconstructible from canonical definition plus durable run evidence.

## 4. Canonical files

### 4.1 Shared baseline

devflow owns one machine-readable shared baseline:

    docs/spec/maintenance/common-baseline.v1.yaml

It defines:
- schema version;
- common lenses;
- default risk/cadence/depth policy;
- default score components;
- freshness classes;
- stable common slot IDs.

Repositories do not copy this baseline as a second canon.

### 4.2 Repository catalog

A participating repository owns:

    .devflow/maintenance.yaml

This file contains only repository-specific information:
- referenced baseline version;
- repository Risk Profile;
- scope-level Risk overrides;
- repository-specific slots/lenses;
- common-slot overrides;
- explicit disable/low-frequency rationale where allowed;
- rollout/adoption state.

It must not contain run history.

### 4.3 Schema

Initial schema identifier: maintenance-catalog.v1.

Unknown major schema versions fail closed as NEEDS_EVIDENCE / SCHEMA_UNSUPPORTED.
The v1 default is closed-schema parsing unless the accepted consumer contract explicitly permits an additive field.

## 5. Maintenance slot model

Each slot has a stable machine identity independent of display text.

Minimum semantics:
- slot_id;
- title;
- lifecycle;
- structured scope;
- lens;
- coverage_key;
- risk;
- cadence class;
- minimum depth;
- external freshness class where applicable;
- description/rationale.

### 5.1 Slot lifecycle

Allowed values:
- ACTIVE
- MERGED
- SUPERSEDED
- RETIRED

Only ACTIVE normally participates in eligibility.
MERGED means meaning was absorbed elsewhere.
SUPERSEDED points to a successor.
RETIRED remains historical and non-runnable.

### 5.2 Scope

Supported v1 scope kinds:
- repository
- path
- component
- runtime_boundary
- workflow
- external_system

A human-readable explanation may accompany the structure.

### 5.3 coverage_key

coverage_key represents materially overlapping audit coverage.
Different slot IDs may share or overlap a coverage family so nominally different but effectively repetitive checks can be penalized.
A name change does not change slot identity.

## 6. Common Lens baseline

The shared baseline contains at least:
- Correctness
- Edge Cases
- Reliability / Recovery
- Security
- State Integrity / Concurrency
- Spec / Implementation Drift
- Test Quality
- Resource Management
- Dependency / External Assumptions
- Error Handling
- Observability
- Lifecycle / Issue / PR / Session consistency

Repositories may add domain-specific lenses.
A repository may lower cadence/relevance for a common lens when justified, but may not silently remove Security coverage entirely.

A worker may inspect a newly discovered viewpoint during a run when necessary, but permanent inclusion requires a normal catalog change with rationale and review.

## 7. Risk Profile

Repository and scope-level values:
- LOW
- MEDIUM
- HIGH
- CRITICAL

Initial derivation direction:
- documentation/static-only: LOW leaning;
- ordinary local application: MEDIUM;
- network/API/external input/process execution: HIGH;
- credential/auth/permission/sensitive boundary: CRITICAL.

Ambiguity resolves conservatively.

A run may recommend a permanent Risk Profile change, but permanent change is a catalog change with durable rationale. Absence of recent findings is not enough to reduce risk automatically.

## 8. Security model

Security is a common lens whose cadence/depth is risk-sensitive.

Recommended v1 sub-lenses:
- SEC.AUTH
- SEC.SECRETS
- SEC.INPUT
- SEC.EXECUTION
- SEC.DEPENDENCY
- SEC.DATA
- SEC.FAILURE
- SEC.PERMISSION

A low-risk repository still retains security coverage, but at lower cadence/depth.

Security findings are not automatically Human-gated. Safe reversible code repairs may follow ordinary autonomous policy. Human confirmation remains mandatory when a repair requires credential/session mutation, permission/IAM mutation, changing a protected security boundary, destructive action, release/deploy/publication, or another difficult-to-reverse action.

## 9. Cadence and cooldown

Cadence means when a slot becomes due; it does not mean the slot is forbidden before that point.

A not-yet-due slot may become useful because of relevant code/config change, new dependency/external evidence, prior finding, security advisory, incomplete previous evidence, explicit user request, or lack of higher-value work.

Initial cadence defaults:

| Risk | General STANDARD | Security STANDARD | DEEP target |
| --- | ---: | ---: | ---: |
| LOW | 90d | 90d | 180d |
| MEDIUM | 60d | 45d | 120d |
| HIGH | 30d | 21d | 60d |
| CRITICAL | 14d | 7d | 30d |

Initial similar-audit cooldowns:

| Risk | Cooldown |
| --- | ---: |
| LOW | 7d |
| MEDIUM | 3d |
| HIGH | 24h |
| CRITICAL | 6h |

Cooldown may be bypassed by relevant change, Security event/advisory, finding verification, incomplete prior evidence, explicit recovery need, or explicit user request.

## 10. Audit Depth

Canonical depth vocabulary:
- CONTROL
- STANDARD
- DEEP

CONTROL confirms authority/current-state structure.
STANDARD is ordinary substantive audit.
DEEP is bounded broader/deeper inspection justified by risk/evidence.

DEEP does not mean an unlimited whole-repository re-audit.

Primary DEEP triggers:
- STANDARD coverage exists but DEEP is never/long-unrun;
- HIGH/CRITICAL scope;
- repeated or serious findings;
- complex concurrency/state behavior;
- protected security boundary;
- major semantic change;
- STANDARD cannot support a reliable conclusion.

## 11. Audit state fingerprint

A run records the state actually audited.
The fingerprint is slot-dependent and may contain:
- code_sha
- dependency_digest
- workflow_digest
- config_digest
- external_observed_at
- provider_evidence_version

This prevents same code SHA from falsely implying freshness for external dependencies.

Initial external freshness classes:
- FAST: 1 day
- NORMAL: 7 days
- SLOW: 30 days

The shared baseline owns class meaning. Repository overrides require concrete rationale.

## 12. Deterministic candidate selection

All eligible maintenance candidates in scope enter one deterministic selection set.
No random tie-break and no free-form LLM priority judgment.

Hard filters include:
- slot lifecycle not ACTIVE;
- repository not ACTIVE;
- invalid catalog/schema/authority evidence;
- overlapping active owner;
- Human/security gate preventing the work itself;
- same effective audit inside cooldown without bypass trigger;
- no plausible new evidence;
- rollout gate not enabled for the repository.

Initial pilot score:

Positive:
- NEVER_RUN +40
- overdue +20
- more than 2x overdue additional +10
- unexecuted lens coverage +15
- justified unexecuted deeper coverage +15
- relevant source/config change +25
- HIGH risk +15
- CRITICAL risk +25
- finding re-audit +20
- security-sensitive change/event +30
- external/dependency freshness stale +20

Negative:
- same repository as immediately previous completed maintenance unit -10
- materially similar recent coverage -20
- same repo + scope + lens + depth + equivalent fingerprint with no bypass trigger: ineligible

The result emits component breakdown.

Tie-break order:
1. higher Risk Profile;
2. longer since materially equivalent run;
3. never-run lens/depth;
4. repository not recently selected;
5. stable lexical repository + slot_id.

## 13. NEVER_RUN behavior

Initial adoption does not create hundreds of Issues.
Slots without prior evidence are classified NEVER_RUN.
They receive score pressure and are consumed gradually.
Catalog existence is not equivalent to published runtime supply.

## 14. Lightweight Audit Ledger

Each participating repository has one standing Issue:

    [MAINTENANCE] Audit Ledger

Portfolio-wide maintenance has one devflow-owned Ledger.

A lightweight read-only run records:
- Run ID;
- slot ID;
- lens/depth;
- audited fingerprint;
- result;
- findings summary;
- completed timestamp;
- next eligibility/re-audit reason when relevant;
- durable evidence links.

The Ledger is run history/progress evidence, not catalog definition.

## 15. Run identity

Stable v1 form:

    audit:<repository>:<slot_id>:<generation>

Generation is a monotonically increasing integer for that repository+slot.
Dates are metadata, not identity.

## 16. Escalation to bounded Audit Issue

A lightweight run promotes to an individual bounded Issue when any applies:
- DEEP work is entered;
- a durable finding needs independent tracking;
- mutation is required;
- multiple recovery-relevant steps are required;
- handoff to another worker is likely;
- blocker/Human Gate appears;
- independent Acceptance is required.

The Ledger retains Run ID, summary, link and promotion point only.
After promotion, detailed progress authority moves to the bounded Issue.

## 17. Durable interruption and resume

Any audit/investigation with continuation value follows existing durable-progress rules.

A successor reads:
1. owning Ledger or Audit Issue;
2. eligible Task Checkpoint Cursor;
3. volatile head/PR/check/review/claim evidence needed for the first unfinished unit;
4. resumes there.

Accepted checks are not replayed merely because chat context is missing.

For long interruption, re-observe volatile evidence. If drift materially invalidates the old frontier, mark the run SUPERSEDED or NEEDS_REAUDIT and start a new generation.

## 18. Finding model

Finding classes:
- DEFECT
- RISK
- DRIFT
- COVERAGE_GAP
- IMPROVEMENT

Confidence:
- CONFIRMED
- PROBABLE
- UNVERIFIED
- FALSE_POSITIVE

Severity describes technical impact.
Priority describes scheduling urgency.
They are separate axes.

## 19. Finding escalation and remediation

- P0/P1: normally create/attach durable owner and interrupt the audit;
- P2/P3: record and normally continue;
- security finding with concrete impact or credible escalation potential may interrupt regardless of nominal Priority.

Before creating a new Issue, search existing open/closed owners for the same root cause/scope.

Same root cause + same contract recurrence favors reopening when semantically correct.
Different cause or different spec generation creates a new Issue with cross-reference.

## 20. Improvement-to-work threshold

An Improvement becomes runnable work only when it directly addresses at least one of:
- acceptance requirement;
- reliability defect/risk;
- security defect/risk;
- concrete maintainability obstacle;
- repeated measurable operational cost;
- explicit project objective.

Cleaner, more elegant, or generic best practice alone is not enough to manufacture supply.

## 21. Mutation and review boundary

A lightweight Ledger run that discovers required mutation must promote to an owning Issue before mutation.

Then use:
- dedicated branch;
- normal tests/verification;
- PR boundary;
- existing review policy.

If the audit already has a bounded Issue and the fix is within its accepted scope, that Issue/branch may carry the fix.
Independent findings get separate ownership.
No normal direct write to default branch.

Audit-generated fixes do not receive weaker review standards. Formal Review and different-reviewer requirements continue to apply when ordinary policy requires them.

## 22. Security tool probe boundary

Already-present safe tools may be used directly.

A new tool may be probed only when use is read-only or isolated, source/safety are known enough for the probe, and it does not modify repository/dependency/workflow/permission state.

Persistently adding a tool, dependency, workflow or permission is a separate normal change.

## 23. Generated / vendored / third-party material

Prefer the real source of truth.

- generated output: audit generator/source plus generation consistency;
- vendored/third-party: emphasize dependency/security/provenance;
- avoid auditing copied/generated content as independent authored code.

## 24. Test and documentation auditing

Test Quality may inspect:
- meaningful assertions;
- negative/failure paths;
- flaky behavior;
- excessive mocking;
- real-entry/runtime mismatch;
- regression coverage.

Documentation/spec auditing focuses on operationally meaningful drift:
- specification vs implementation;
- Current State vs accepted main;
- stale recovery/routing instructions;
- misleading authority.

Pure prose beautification is not maintenance supply.

## 25. Claims and ownership

A maintenance candidate is not owned because a selector chose it.

Accepted path:

    catalog + durable evidence
    -> derived eligible candidate
    -> accepted publication path
    -> execution-coordinator serialized claim
    -> acknowledge
    -> work

execution-coordinator remains sole runtime claim/lease/generation/fencing authority.
3C separation remains mandatory: the same attempt that publishes/relaxes a candidate does not consume it.

## 26. Parallelism and active-producer collision

Different maintenance work may run in parallel only when scope is clearly disjoint and there is no mutation/owner collision.
Same-scope or broad DEEP audits are exclusive.

An active implementation producer owns its bounded scope.
Maintenance may record a finding against that scope, but should not patch over the active producer except for urgent P0/P1 escalation under existing policy.
Normal disposition is handoff/reference to the active owner.

## 27. Portfolio-wide maintenance

devflow may define portfolio slots such as:
- Control consistency;
- stale Sessions;
- open lifecycle;
- claims/supply consistency;
- audit freshness;
- dependency consistency;
- security gates;
- spec/current-state drift.

These compete in the same deterministic model when portfolio scope is active.
They remain backstops, not substitute garbage collectors for producer-owned reconciliation.

## 28. Broad instruction semantics

When a generic broad instruction has no repository target, use portfolio scope:

    recoverable
    -> normal runnable
    -> maintenance
    -> alternate/deeper maintenance
    -> portfolio audit
    -> NO_ELIGIBLE_WORK

For an explicit repository-scoped instruction:
- remain repository-scoped;
- explore alternate lenses/depths within that repository;
- do not silently broaden to the fleet merely because that repository is fresh.

For a generic audit request, use the selector to choose the most useful unsatisfied Lens/Depth.
Words such as "deep" or "thorough" may bias toward DEEP where justified, but never imply unbounded repository-wide audit.

## 29. True NO_ELIGIBLE_WORK

A successful scan may emit NO_ELIGIBLE_WORK only when:
- no recoverable work exists;
- no normal runnable work exists;
- no due/overdue maintenance exists;
- no never-run useful Lens exists;
- no materially useful depth expansion exists;
- no alternate repository candidate exists in current scope;
- no portfolio candidate exists when portfolio scope applies;
- no security/external freshness problem exists;
- repeating an existing audit is not reasonably expected to produce materially new evidence.

The system is near-C in persistence, but never repeats work solely to avoid idle state.

## 30. Catalog mutation versus machine projection

Catalog definition changes require a dedicated branch, schema validation, diff review and ordinary PR boundary.

Machine-owned runtime projection may update through a dedicated accepted projection path without editing catalog definition.

This prevents a PR for every audit while preserving single-canon semantics.

## 31. Stage-2 integration

Existing Stage-2 audit/triage remains the deterministic fleet scanner.

This design reuses its exact-source/freshness/fail-closed principles and does not alter its disposition vocabulary.

Stage-2 output may contribute evidence to maintenance eligibility but does not create runnable work unless a predefined slot plus accepted publication rule establishes legitimate supply.

A scan finding alone remains non-supply.

## 32. devflow#209 supply integration

devflow#209 remains standing supply/publication authority.

The new path may eventually extend legitimate demand to predefined catalog-backed maintenance demand, but only after this design is accepted and the publication contract is explicitly changed.

Until then, #209 current no-synthetic-supply rule remains unchanged.

Future candidate evidence must include at least:
- repository/catalog identity;
- slot ID;
- generation;
- fingerprint;
- selection score breakdown;
- trusted catalog digest;
- freshness;
- owning Ledger/Audit Issue;
- 3C publisher attempt identity.

## 33. Rollout gate

Adoption state:
- DISABLED
- PILOT
- ENABLED

A catalog does not produce supply unless rollout state permits it.

Initial pilot:
1. devflow;
2. execution-coordinator;
3. optionally one additional control-plane repository after the first two are stable.

## 34. Pilot acceptance

Pilot must demonstrate:
- deterministic selection;
- explainable score;
- no duplicate claim;
- lightweight Ledger-only completion;
- Ledger to bounded Issue promotion;
- interrupted run resume;
- finding to normal-work re-ranking;
- alternate Lens rotation;
- justified deeper audit;
- same-audit suppression;
- external freshness trigger with unchanged code SHA;
- repository bias penalty;
- portfolio selection;
- true NO_ELIGIBLE_WORK;
- no catalog/projection authority duplication;
- no weakening of Human/security gates.

A fixed count of successful runs alone is insufficient.

## 35. Rollback

The new maintenance supply path must be feature-gated.

On pilot failure:
- return affected repositories to DISABLED or prior rollout state;
- retain catalog definitions and durable history;
- withdraw maintenance supply;
- leave normal work/recovery paths untouched.

No history rewrite or destructive cleanup is required.

## 36. Chat reporting

Issue-first reporting remains mandatory.

Chat normally includes:
- what was selected/done;
- finding/fix result;
- current state;
- blocker/Human action if any;
- owning Issue/PR references.

Detailed evidence belongs in the Ledger/Audit Issue/PR/Actions.

## 37. Review gate

User design approval was recorded on 2026-10-07.

Implementation planning may proceed, but implementation itself still requires:
1. the implementation plan to remain consistent with live devflow authority;
2. canonical implementation targets to be named;
3. #209 publication extension and execution-coordinator interaction to be represented in the plan;
4. rollout to remain PILOT until evidence supports broader adoption;
5. the implementation plan to pass its user/execution-method review gate.

Design approval does not itself release implementation.
