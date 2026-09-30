# Portfolio-scope Broad Pickup v2

Status: accepted under completed devflow#208; additive work-class/reviewer-provenance extensions remain governed by their owning acceptance evidence
Authority chain: devflow#190 Phase D -> #198 -> #208; additive work-class constraint: devflow#215 Stage 1; reviewer-provenance requirement extension: devflow#211
Runtime consumer: `kinoko34077/execution-coordinator`

## 1. Purpose

Portfolio scope resolves a broad request with `target_repository = null` from live managed Repository Controls without asking the user to choose a repository. It reuses the accepted candidate, ranking, capability and serialized-claim authorities; it creates no second scheduler or assignment database.

Repository-scoped v1 behavior is unchanged. `DEVFLOW_EXECUTION_CANDIDATES_V1` remains the sole ordinary admission/freshness projection. Portfolio participation requires an additional scheduling record; no fields are silently added to the v1 admission block.

## 2. Companion scheduling projection

A Repository Control MAY contain exactly one block:

```text
<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN -->
{
  "schema_version": "execution-portfolio-metadata.v1",
  "source_ref": "kinoko34077/devflow#59",
  "repository": "kinoko34077/kinotch-repo-monitor",
  "entries": []
}
<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_END -->
```

The JSON shape is canonicalized by `schemas/execution-portfolio-metadata.v1.schema.json`. Duplicate/partial/reversed markers, duplicate `(task, role)` entries, unknown fields, malformed values or source/repository mismatch fail closed for portfolio enumeration. No block is valid for repository-scoped v1 but means that repository's ordinary candidates are not yet portfolio-rankable.

Each entry binds exactly one already-valid v1 candidate role using both `task_body_sha256` and `candidate_fingerprint`. The body digest prevents a newly revised owning task from silently inheriting old scheduling metadata; the fingerprint prevents a changed admission/conflict projection from inheriting it. Both must match current validated evidence.

The entry carries only scheduling/worker-match data: optional controller urgency, explicit dependency readiness/order, readiness class, optional `ready_at`, exact required capability/environment tags, optional `work_class`, optional `different_reviewer_requirement`, and `observed_at`/`fresh_until`. The exact live trusted Control `Priority` field supplies `control_priority`; it is deliberately not duplicated. Owning-Issue scope/acceptance remains in the owning repository.

`work_class`, when present, uses the closed Stage-1 vocabulary from `CHAT_WORKER_BOOTSTRAP.md`: `audit`, `triage`, `sync-check`, `quickfix`, `implementation`, `formal-review`. It describes task content and is independent of the participation `role` as an axis, but explicit evidence must remain compatible at the review boundary: `work_class == formal-review` iff `role == reviewer`. A contradictory explicit pair is malformed portfolio evidence and fails closed; it is not treated as a worker-preference mismatch. `work_class` remains optional for backward compatibility, and absence continues to use the conservative legacy role-to-class fallback from the bootstrap contract.

`different_reviewer_requirement` is optional and valid only for a reviewer entry. Presence records the exact implementer Review Provenance `system + model` signature against which a consuming reviewer must differ. It does not store a derived `self/independent` flag. Because it lives in the same companion entry, its authority/freshness is already bound to `task_body_sha256`, `candidate_fingerprint`, `observed_at` and `fresh_until`; no second freshness clock is introduced. Missing or ambiguous required signature evidence fails closed. The devflow-side schema/classifier contract does not by itself authorize current execution-coordinator publishers/parsers to emit this optional field; runtime propagation remains separately gated by its owning execution-coordinator work.

`dependency_ready = true` requires a non-negative `dependency_order`; `false` requires `dependency_order = null`. `fresh_until` must be later than `observed_at`. `ready_at`, when present, is UTC and must not be inferred from Issue timestamps. Provider/model identity never supplies requirement tags, a work class, or a Review Provenance signature. Review signature evidence must be direct and explicit.

## 3. Complete frontier rule

Portfolio enumeration begins from the exact live managed `[REPO]` Controls and retains source/discovery failures. For ordinary fresh candidates, the frontier is complete only when each participating candidate has one unique fresh matching companion entry. Missing, stale, duplicate, body/fingerprint-mismatched, role/work-class-contradictory or otherwise ambiguous ranking/requirements evidence makes portfolio evidence incomplete or invalid; consumers fail closed rather than using the repository-scoped fallback.

The optional absence of `work_class` does not make legacy metadata incomplete. It deliberately invokes the conservative role-to-class compatibility mapping from `CHAT_WORKER_BOOTSTRAP.md`. New lightweight classes (`audit`, `triage`, `sync-check`, `quickfix`) require explicit class evidence and are never inferred from an old implementer entry.

Recovery demand remains a separate track. It is not converted into fresh work and does not gain ordinary ranking authority merely because a runtime claim is absent.

## 4. Ranking and worker matching

Hard filters remain: trusted/fresh admission, live Control state and safety gates, dependency readiness, runtime claim/conflict compatibility, 3C publisher/consumer separation, reviewer independence, and exact capability/environment subset matching. For an explicit different-reviewer entry, reviewer independence includes direct Review Provenance signature inequality under the #111/#211 rule; this is eligibility only and does not replace exact-head merge-time Review freshness.

When a bootstrap request explicitly supplies `accepted_work_classes`, work-class mismatch is an additional hard omission applied after the existing safety/capability gates and before role-track ranking. This means a maintenance-mode worker can reject unrelated `formal-review` demand without changing the global `recovery -> reviewer -> implementer` track policy for unconstrained workers. Contradictory explicit role/work-class evidence is validated earlier as malformed evidence and never reaches this omission/ranking stage.

Ordinary rank class is lexicographic over: Control priority; explicit urgency; dependency order; readiness class; explicit `ready_at`. Canonical task identity is an audit tie-breaker, not part of the rank class.

After filtering, portfolio selection fixes the highest-precedence surviving work track and best rank class, then uses **worker-scoped** deterministic spread:

```text
SHA-256(coordinator_worker_id || "\0" || task_ref || "\0" || execution_attempt_id)
```

The smallest `(hash, task_ref, role)` wins. Candidate input order never matters. One discovery cycle submits at most one claim attempt. A rejected claim ends the cycle; the worker refreshes rather than falling through to candidate 2.

Repository-scoped requests retain the accepted v1 `(track, rank_key, task_ref, role)` behavior after the same optional work-class filter.

## 5. Control gates in portfolio scope

Every candidate repository must resolve to exactly one trusted open Control. Missing, duplicate or untrusted Control identity fails the cycle closed. `Repository State != ACTIVE`, Control Human/User gate, or external blocker omits candidates from that repository without suppressing unrelated eligible repositories. If nothing survives, Human and external blockers keep their existing top-level precedence; otherwise `ALL_CANDIDATES_OMITTED` applies.

## 6. Safety and authority

Release/deploy/publication, credential/session/permission mutation, destructive/shared-history operations and other security-sensitive/difficult-to-reverse actions remain Human-gated. Portfolio metadata cannot relax these boundaries. Adoption remains `PILOT`. No provider launch, daemon scheduler, work stealing or controller negotiation is introduced.

Publication and consumption remain separate operations (3C). A worker/session that adds or relaxes candidate/portfolio metadata does not consume that change in the same execution attempt.

Stage 1 adds no effort scoring, fairness controller, persistent queue or small-batch loop. It only permits a worker cycle to constrain the already-authoritative frontier by a bounded work-class set before existing ranking/claim logic runs.

## 7. Acceptance

The original #208 acceptance requires exact-head tests/CI/review, a bounded Stage-3 pilot across at least two real managed repositories, no fallthrough after claim rejection, and final execution-coordinator runtime claims `{}`. The additive #215 Stage-1 change separately requires exact-head compatibility tests proving unconstrained legacy behavior, explicit work-class filtering, and fail-closed rejection of contradictory explicit role/work-class evidence before runtime propagation is accepted.
