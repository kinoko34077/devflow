# Implementer-Authored Formal Review Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an implementer-authored current-head formal Review a valid default merge path while retaining explicit different-reviewer escalation and exact-SHA/provenance gates.

**Architecture:** Keep formal Review mandatory for non-trivial PRs, but remove persisted self/independent classifications. PR metadata declares only whether formal review and a different reviewer are required; Review Provenance v2 records direct reviewer/implementer signatures, and the readiness evaluator derives signature equality at evaluation time.

**Tech Stack:** Markdown policy/specification, YAML workflow contract, Python 3 standard library, unittest, GitHub Pull Request Reviews.

**Spec:** `devflow#111`

## Global Constraints

- Formal Review remains required for non-trivial PRs.
- Reviewer separation is not required by default.
- Review Provenance v2 stores direct reviewer/implementer identity, reviewed SHA, scope and decision only.
- Do not persist self-review/independent-review/Review-Role/Independence classifications.
- Different-reviewer Review is mandatory only through an explicit escalation condition.
- Exact-head freshness, blocking findings, CI/check, thread-resolution and confirmation boundaries remain intact.

## Review Focus

- A same-signature Review must satisfy the default path when different-reviewer escalation is false.
- A same-signature Review must not satisfy an explicit different-reviewer gate.
- A different-signature current-head Review must satisfy that escalation gate.
- A stale-head or REQUEST_CHANGES Review must remain blocking regardless of reviewer relation.
- Missing/ambiguous direct provenance fields must fail closed.

---

### Task 1: Pin the v2 readiness contract with tests

**Files:**
- Modify: `tests/test_review_readiness.py`

**Interfaces:**
- PR fields: `Formal review required: yes|no`, `Different reviewer required: yes|no`.
- Review provenance v2 fields: Reviewer-System, Reviewer-Model, Implementer-System, Implementer-Model, Reviewed-Commit, Review-Scope, Decision, Review-Provenance-Version.

- [ ] Replace role/independence fixtures with direct-signature v2 fixtures.
- [ ] Add default same-signature PASS, escalated same-signature FAIL, escalated different-signature PASS, stale SHA FAIL, blocker FAIL, and no-review-required PASS cases.
- [ ] Run `python -m unittest tests.test_review_readiness -v` and confirm RED against the v1 evaluator.

### Task 2: Implement identity-derived readiness

**Files:**
- Modify: `tools/review_readiness.py`

**Interfaces:**
- `evaluate(pr, reviews) -> ReadinessResult` remains stable.
- `_provenance_fields` accepts only the v2 direct field set for managed readiness.

- [ ] Parse the two PR gate booleans and direct implementer signature.
- [ ] Validate v2 exact-head provenance and API Review state/decision consistency.
- [ ] For default review, accept a clean current-head formal Review regardless of signature equality.
- [ ] For different-reviewer escalation, require at least one clean current-head Review whose reviewer signature differs from the implementer signature.
- [ ] Preserve newest-relevant-review supersession of prior blockers.
- [ ] Run targeted tests and full unittest discovery.

### Task 3: Reconcile human and machine policy surfaces

**Files:**
- Modify: `docs/operations/AGENT_OPERATING_MANUAL.md`
- Modify: `docs/operations/REPOSITORY_ISSUE_MANUAL.md`
- Modify: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
- Modify: `.devflow/WORKFLOW.yaml`
- Modify: `.github/pull_request_template.md`

- [ ] Replace default independent-review language with formal-review-by-default plus explicit escalation conditions from #111.
- [ ] Publish Review Provenance v2 without Review-Role or Independence.
- [ ] Document that P1/MEDIUM/devflow/Base/Runtime labels alone do not force a second reviewer.
- [ ] Update merge/auto-merge wording to use the applicable escalation gate.
- [ ] Update PR template gate fields and preserve implementer provenance.
- [ ] Add machine-readable review policy matching the human policy.

### Task 4: Verify and open the policy PR

**Files:**
- No new production files beyond Tasks 1-3.

- [ ] Run full repository tests, Python compile checks and `git diff --check` equivalent through available CI.
- [ ] Open PR owned by #111 with exact-head evidence and Review Provenance v2 target.
- [ ] Submit a formal current-head implementer-authored Review under v2.
- [ ] Confirm advisory readiness passes the default same-signature path.
- [ ] Reconcile #111 and devflow Control #16; merge only after applicable gates are green and safely reversible.
