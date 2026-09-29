# Portfolio-scope Broad Pickup v2

Status: proposed for acceptance under devflow#208
Authority chain: devflow#190 Phase D -> #198 -> #208
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

The entry carries only scheduling/worker-match data: optional controller urgency, explicit dependency readiness/order, readiness class, optional `ready_at`, exact required capability/environment tags, and `observed_at`/`fresh_until`. The exact live trusted Control `Priority` field supplies `control_priority`; it is deliberately not duplicated. Owning-Issue scope/acceptance remains in the owning repository.

`dependency_ready = true` requires a non-negative `dependency_order`; `false` requires `dependency_order = null`. `fresh_until` must be later than `observed_at`. `ready_at`, when present, is UTC and must not be inferred from Issue timestamps. Provider/model identity never supplies requirement tags.

## 3. Complete frontier rule

Portfolio enumeration begins from the exact live managed `[REPO]` Controls and retains source/discovery failures. For ordinary fresh candidates, the frontier is complete only when each participating candidate has one unique fresh matching companion entry. Missing, stale, duplicate, body/fingerprint-mismatched or ambiguous ranking/requirements evidence makes portfolio evidence incomplete; consumers return `NEEDS_EVIDENCE / FRONTIER_UNAVAILABLE` rather than using the repository-scoped fallback.

Recovery demand remains a separate track. It is not converted into fresh work and does not gain ordinary ranking authority merely because a runtime claim is absent.

## 4. Ranking and worker matching

Hard filters remain: trusted/fresh admission, live Control state and safety gates, dependency readiness, runtime claim/conflict compatibility, 3C publisher/consumer separation, reviewer independence, and exact capability/environment subset matching.

Ordinary rank class is lexicographic over: Control priority; explicit urgency; dependency order; readiness class; explicit `ready_at`. Canonical task identity is an audit tie-breaker, not part of the rank class.

After selecting the highest-precedence work track and best rank class, portfolio selection uses **worker-scoped** deterministic spread:

```text
SHA-256(coordinator_worker_id || "\0" || task_ref || "\0" || execution_attempt_id)
```

The smallest `(hash, task_ref, role)` wins. Candidate input order never matters. One discovery cycle submits at most one claim attempt. A rejected claim ends the cycle; the worker refreshes rather than falling through to candidate 2.

Repository-scoped requests retain the accepted v1 `(track, rank_key, task_ref, role)` behavior.

## 5. Control gates in portfolio scope

Every candidate repository must resolve to exactly one trusted open Control. Missing, duplicate or untrusted Control identity fails the cycle closed. `Repository State != ACTIVE`, Control Human/User gate, or external blocker omits candidates from that repository without suppressing unrelated eligible repositories. If nothing survives, Human and external blockers keep their existing top-level precedence; otherwise `ALL_CANDIDATES_OMITTED` applies.

## 6. Safety and authority

Release/deploy/publication, credential/session/permission mutation, destructive/shared-history operations and other security-sensitive/difficult-to-reverse actions remain Human-gated. Portfolio metadata cannot relax these boundaries. Adoption remains `PILOT`. No provider launch, daemon scheduler, work stealing or controller negotiation is introduced.

Publication and consumption remain separate operations (3C). A worker/session that adds or relaxes candidate/portfolio metadata does not consume that change in the same execution attempt.

## 7. Acceptance

Acceptance requires exact-head tests/CI/review; runtime implementation consuming this contract only after the devflow contract is accepted; a bounded Stage-3 pilot across at least two real managed repositories; no fallthrough after claim rejection; and final execution-coordinator runtime claims `{}`.
