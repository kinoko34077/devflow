# Chat Worker Bootstrap Contract v1

Status: accepted baseline under devflow#191/#208/#215; this document also defines the bounded reviewer-provenance pickup-eligibility extension owned by devflow#211, whose acceptance is governed by its Issue/PR evidence
Authority: devflow cross-repository workflow specification
Scope: provider-neutral bootstrap for an already-open, manually-started Codex, Claude/Claude Code or ordinary ChatGPT chat

This contract turns a broad instruction such as

> 「このリポ側に合わせてなんか作業して」

into exactly one deterministic, fail-closed **disposition** for one worker, plus at most one selected work candidate. It is a derived decision contract. It creates no queue, scheduler, task database or provider-specific priority authority. The owning Issue/Work Order remains durable task truth. The Repository Control remains the cross-repository summary and candidate source. `kinoko34077/execution-coordinator` remains the only runtime claim/lease/generation/fencing authority. Adoption mode stays `PILOT` (devflow#189).

Machine-readable artifacts:

- request schema: [`schemas/chat-worker-bootstrap-request.v1.schema.json`](./schemas/chat-worker-bootstrap-request.v1.schema.json)
- evidence schema: [`schemas/chat-worker-bootstrap-evidence.v1.schema.json`](./schemas/chat-worker-bootstrap-evidence.v1.schema.json)
- result schema: [`schemas/chat-worker-bootstrap-result.v1.schema.json`](./schemas/chat-worker-bootstrap-result.v1.schema.json)
- executable reference classifier (pure, no I/O): `tools/chat_worker_bootstrap.py`
- positive and negative examples: [`examples/chat-worker-bootstrap/`](./examples/chat-worker-bootstrap/), exercised by `tests/test_chat_worker_bootstrap.py`

If the prose here and the reference classifier ever disagree, the prose is normative and the classifier has a defect.

## 1. Processing model

```text
user broad instruction (+ current working context)
  -> worker builds a v1 request (runtime identity, declared tags, tool surfaces, optional work-class constraint, optional direct Review Provenance signature)
  -> worker reads live evidence in the canonical order (section 4)
  -> classify(request, evidence) -> exactly one v1 result
  -> work disposition: serialized claim -> acknowledge -> Execution Session -> bounded work
  -> any other disposition: report it and stop; no invented task
```

The classification is a pure function of `(request, evidence)`. Provider transport identity never grants capability, priority or rank. For an explicit different-reviewer demand only, a directly supplied Review Provenance `System + Model` signature may participate as a hard eligibility gate; it is not inferred from `worker_system`.

## 2. Request envelope (`chat-worker-bootstrap-request.v1`)

The original v1 fields remain required. Additive optional fields are `accepted_work_classes` (#215) and `review_provenance` (#211). Unknown fields are rejected.

| Field | Type | Rule |
| --- | --- | --- |
| `schema_version` | const | `chat-worker-bootstrap-request.v1`; any other value gives `NEEDS_EVIDENCE` / `SCHEMA_UNSUPPORTED` |
| `target_repository` | `owner/name` or `null` | from the user or the current working context; `null` means portfolio scope |
| `work_intent` | string ≤ 500 or `null` | the user's broad instruction, recorded for audit only; **never selects, ranks or filters work** |
| `accepted_work_classes` | optional non-empty closed array | explicit structured constraint over Stage-1 work classes; absent means unconstrained legacy selection |
| `review_provenance` | optional `{system, model}` | direct Review Provenance v2 reviewer signature for eligibility checks; never inferred from provider identity and ignored unless an explicit different-reviewer candidate needs it |
| `worker_system` | `codex` \| `claude` \| `chatgpt` | provenance only; never implies a capability |
| `worker_session_id` | identity | one per chat/session for its lifetime (section 6) |
| `execution_attempt_id` | identity | one per discovery cycle (section 7) |
| `capabilities` | exact tags | declared by the session; no inference |
| `environment` | exact tags | declared by the session; no inference |
| `tool_surfaces` | exact tags | tools the chat can actually use right now (section 8) |
| `observed_at` | RFC3339 UTC (`…Z`) | when the request was built |

Stage-1 work classes are a deliberately small closed vocabulary:

- `audit`
- `triage`
- `sync-check`
- `quickfix`
- `implementation`
- `formal-review`

`accepted_work_classes` is a worker-cycle preference/constraint, not a capability grant and not a new scheduler. It may be populated only from an explicit operating-mode/request interpretation made before classification. Free-form `work_intent` remains audit text and does not itself cause selection. An absent `accepted_work_classes` field preserves the pre-#215 behavior exactly.

Normalization:

- tags must match `^[a-z0-9][a-z0-9_.:/-]{0,63}$`;
- duplicate tags are rejected, and valid tags are sorted;
- `accepted_work_classes`, when present, must be non-empty, unique and contain only the closed values above;
- `review_provenance`, when present, contains exactly non-empty `system` and `model` strings; whitespace is normalized for comparison and secret-shaped values are rejected;
- identities must match `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`;
- `target_repository` is compared case-insensitively against Control identities, with no other transformation.

Secret prohibition: credentials, tokens, cookies, secrets and session material must never appear in any request field. Secret-shaped values are rejected with `REQUEST_INVALID`. Examples of secret-shaped values are `ghp_`, `github_pat_`, `sk-`, and text containing `bearer`, `token`, `secret`, `password` or `cookie`. The session/attempt identities are procedural/audit identities, not cryptographic identity or authentication.

## 3. Result envelope (`chat-worker-bootstrap-result.v1`)

One envelope serves every disposition. `role`/`action` distinguish fresh, review and recovery work, so no per-disposition subtypes exist (decision 8).

| Field | Rule |
| --- | --- |
| `disposition` | exactly one of the seven dispositions (section 5) |
| `worker_session_id`, `execution_attempt_id`, `target_repository` | echoed from the normalized request; `null` only when the request itself was invalid |
| `task_ref`, `role`, `action` | set **exactly** for the work dispositions; `null` otherwise |
| `claim_required` | `true` exactly for the work dispositions |
| `claim_candidate_fingerprint` | the selected candidate fingerprint, for binding the serialized claim; `null` otherwise |
| `coordinator_worker_id` | `<worker_system>:<worker_session_id>` for the runtime claim; `null` otherwise |
| `source_refs` | sorted, unique canonical references only (section 9) |
| `reason_code` | a typed code from section 5.2 (authority) |
| `reason_detail` | human-readable; **never authority** |
| `omissions` | per-candidate `{task_ref, role, reason}` evidence, sorted |
| `next_authoritative_step` | derived from the disposition (section 5.1) |

## 4. Canonical read and selection order

Repository-scoped entry reads, in order:

1. live `devflow/AGENTS.md`, or the equivalent bootstrap result;
2. the exact target `[REPO]` Repository Control;
3. canonical repository-local entry points, and the active owning Issue/Work Order/PR where referenced;
4. trusted active/relevant Execution Session Records (#142/#144);
5. the accepted candidate/reconciliation frontier (#125, #159, execution-coordinator managed frontier);
6. execution-coordinator runtime state and claimability;
7. dependency, capability/environment, safety and optional work-class filtering;
8. deterministic selection.

The classifier then applies the **first matching rule**:

| # | Condition | Result |
| --- | --- | --- |
| 1 | request malformed / unknown schema / secret-shaped | `NEEDS_EVIDENCE` (`REQUEST_INVALID` / `SCHEMA_UNSUPPORTED`) |
| 2 | evidence malformed, or its `[observed_at, fresh_until]` window does not cover the request | `NEEDS_EVIDENCE` (`EVIDENCE_INVALID` / `EVIDENCE_STALE`) |
| 3 | `target_repository` is `null` | apply the accepted portfolio-v2 path from `PORTFOLIO_PICKUP_V2.md`; a complete frontier is mandatory and no repo-scoped fallback is allowed |
| 4 | live AGENTS.md not read | `NEEDS_EVIDENCE` (`BOOTSTRAP_UNREAD`) |
| 5 | no open Control / more than one open Control / untrusted Control for the target | `NEEDS_EVIDENCE` (`CONTROL_NOT_FOUND` / `CONTROL_DUPLICATE` / `CONTROL_UNTRUSTED`) |
| 6 | Control `Repository State` is not `ACTIVE` | `NO_ELIGIBLE_WORK` (`REPOSITORY_NOT_ACTIVE`) |
| 7 | Control-level Human gate / external blocker | `NEEDS_HUMAN` (`HUMAN_GATE`) / `WAIT_EXTERNAL` (`EXTERNAL_BLOCKER`) |
| 8 | frontier incomplete / runtime state unread | `NEEDS_EVIDENCE` (`FRONTIER_UNAVAILABLE` / `COORDINATOR_STATE_UNAVAILABLE`) |
| 9 | successful scan with zero published candidates | `NO_ELIGIBLE_WORK` (`NO_CANDIDATES_PUBLISHED`) |
| 10 | per-candidate hard filters (section 5.3); if nothing survives: a Human-gate omission gives `NEEDS_HUMAN`; otherwise an external-blocker omission gives `WAIT_EXTERNAL`; otherwise `NO_ELIGIBLE_WORK` (`ALL_CANDIDATES_OMITTED`) | |
| 11 | provider lacks a required tool surface (section 8) | `NEEDS_EVIDENCE` (`PROVIDER_SURFACE_MISSING`) |
| 12 | deterministic selection (section 5.4) | `RECOVERY_WORK` / `REVIEW_WORK` / `CLAIM_AND_WORK` |

A later rule never overrides an earlier integrity or safety rule.

Portfolio scope (`target_repository = null`) is defined by `PORTFOLIO_PICKUP_V2.md` under #208. Repository-scoped behavior remains v1-compatible. `PORTFOLIO_ENUMERATION_UNAVAILABLE` is retained as a legacy typed code for older implementations but is not the accepted #208 portfolio outcome.

## 5. Dispositions and vocabulary

### 5.1 Dispositions

| Disposition | Meaning | `next_authoritative_step` |
| --- | --- | --- |
| `CLAIM_AND_WORK` | one fresh `implementer` candidate is fully eligible | `CLAIM_THEN_ACKNOWLEDGE` |
| `REVIEW_WORK` | one explicit `reviewer` demand is eligible and satisfies reviewer independence | `CLAIM_THEN_ACKNOWLEDGE` |
| `RECOVERY_WORK` | one explicit `recovery` demand over interrupted/stale work is eligible | `CLAIM_THEN_ACKNOWLEDGE` |
| `NEEDS_HUMAN` | a Human/User gate is the next real blocker | `ASK_HUMAN` |
| `WAIT_EXTERNAL` | a named external blocker is unresolved | `RECHECK_EXTERNAL` |
| `NO_ELIGIBLE_WORK` | the authoritative scan succeeded and nothing is eligible for this worker | `REFRESH_LATER` |
| `NEEDS_EVIDENCE` | required authority/freshness/trust/surface evidence is missing or ambiguous | `RESOLVE_EVIDENCE` |

Fresh, review and recovery work stay distinct:

- `IMPLEMENTING` with no live claim is **never** converted into fresh work. Only an explicit recovery demand (#158/#159) produces `RECOVERY_WORK`.
- A work disposition is not ownership. No work starts before the serialized claim and `acknowledge` succeed. A claim rejection ends the cycle (section 7).

### 5.2 `reason_code` vocabulary (closed for v1)

Selection:
- `ELIGIBLE_FRESH_CANDIDATE`
- `ELIGIBLE_REVIEW_DEMAND`
- `ELIGIBLE_RECOVERY_DEMAND`

Non-work outcomes:
- `HUMAN_GATE`
- `EXTERNAL_BLOCKER`
- `NO_CANDIDATES_PUBLISHED`
- `ALL_CANDIDATES_OMITTED`
- `REPOSITORY_NOT_ACTIVE`

Evidence failures:
- `REQUEST_INVALID`
- `SCHEMA_UNSUPPORTED`
- `EVIDENCE_INVALID`
- `EVIDENCE_STALE`
- `PORTFOLIO_ENUMERATION_UNAVAILABLE`
- `BOOTSTRAP_UNREAD`
- `CONTROL_NOT_FOUND`
- `CONTROL_DUPLICATE`
- `CONTROL_UNTRUSTED`
- `FRONTIER_UNAVAILABLE`
- `COORDINATOR_STATE_UNAVAILABLE`
- `PROVIDER_SURFACE_MISSING`

Adding a code is a contract change.

### 5.3 Per-candidate hard filters

Filters are applied in this order. The first failing filter becomes the candidate's single omission `reason`.

1. `REPOSITORY_NOT_ACTIVE` (portfolio only): the candidate's exact trusted Control is not `ACTIVE`.
2. `ROLE_UNSUPPORTED`: the role is not `implementer`, `reviewer` or `recovery`.
3. `STALE_DIGEST`: the owning-body SHA-256 no longer matches (#125).
4. `HUMAN_GATE`: a task-level Human/User gate.
5. `EXTERNAL_BLOCKER`: a task-level external blocker.
6. `DEPENDENCY_NOT_READY`.
7. `LIVE_CLAIM_CONFLICT`: claimability is not `CLAIMABLE` (`BLOCKED_LIVE` / `EXPIRED_UNSWEPT`).
8. `PUBLISHED_BY_THIS_ATTEMPT`: decision 3C; this attempt published or relaxed the candidate.
9. `REVIEWER_INDEPENDENCE_CONFLICT`: reviewer role only; covers both live claim/session independence and an explicit durable Review Provenance signature requirement.
10. `CAPABILITY_MISMATCH`: `required_capabilities ⊄ capabilities`.
11. `ENVIRONMENT_MISMATCH`: `required_environment ⊄ environment`.
12. `WORK_CLASS_MISMATCH`: the request contains `accepted_work_classes` and the candidate's effective class is outside that set.

Capability/environment matching is an exact tag subset check. `worker_system`, the model name, `work_intent`, repository language and prior success never add tags.

A candidate may carry an explicit optional `work_class`. For compatibility with candidates published before #215 Stage 1, a missing class has only these conservative defaults:

- `reviewer` -> `formal-review`;
- `implementer` -> `implementation`;
- `recovery` -> `implementation`.

For an **explicit** `work_class`, the participation role and class must satisfy the smallest Stage-1 compatibility invariant:

```text
work_class == formal-review  <=>  role == reviewer
```

Thus an explicit reviewer candidate with any non-`formal-review` class, or an explicit non-reviewer candidate with `formal-review`, is malformed frontier evidence and fails the cycle closed as `NEEDS_EVIDENCE / EVIDENCE_INVALID`. This validation occurs before per-candidate omission filtering; it is not downgraded to `WORK_CLASS_MISMATCH`. Omitted `work_class` remains backward compatible and continues to use the conservative legacy defaults above.

No legacy candidate is inferred to be `audit`, `triage`, `sync-check` or `quickfix`. Those classes require explicit publication evidence. This avoids reclassifying an old broad implementation task as a lightweight job merely because a maintenance worker requested one.

#### Explicit different-reviewer eligibility (#211)

Ordinary reviewer candidates keep #111 semantics: a Formal Review authored by the implementer remains valid unless the owning policy explicitly requires a different reviewer. No reviewer signature is required at pickup for that ordinary path.

An explicit different-reviewer candidate MAY carry:

```json
{
  "different_reviewer_requirement": {
    "implementer_system": "ChatGPT",
    "implementer_model": "GPT-5.6 Sol"
  }
}
```

Presence means the durable task requires a reviewer whose eventual Review Provenance v2 signature differs from the implementer signature. The field is valid only on a `reviewer` candidate. The candidate-side requirement is accepted only through the same trusted/fresh evidence path as the candidate itself; portfolio publication binds it to the existing task-body digest, candidate fingerprint, `observed_at` and `fresh_until`.

A worker that may consume such a candidate must provide direct request evidence:

```json
{
  "review_provenance": {
    "system": "Claude Code",
    "model": "Claude Sonnet 5"
  }
}
```

`review_provenance` is the signature the worker would place in `Reviewer-System` / `Reviewer-Model`; it is not derived from `worker_system`, provider reputation or model capability. Missing or malformed required signature evidence fails closed as `NEEDS_EVIDENCE / EVIDENCE_INVALID`. A proven same signature is valid evidence but makes that candidate ineligible with `REVIEWER_INDEPENDENCE_CONFLICT`.

Comparison intentionally matches the merge-time Review Provenance rule in `tools/review_readiness.py`: normalize whitespace/case; an unknown reviewer system never proves difference; different known systems prove difference; when systems match, unknown model on either side does not prove difference; otherwise models must differ.

This pickup gate does **not** prove that a later Review exists or is fresh. Exact PR head, submitted Review state, blocking findings and current-head Review Provenance remain merge-time/readiness evidence. Pickup identity eligibility and merge-time Review freshness are separate gates.

### 5.4 Deterministic selection

Among candidates surviving hard filtering, exactly one is selected by the existing lexicographic policy:

```text
(track, rank_key, task_ref, role)
track: recovery = 0, reviewer = 1, implementer = 2
```

- Finishing in-flight work comes before starting new work **within the worker's accepted class set** when one was explicitly supplied.
- `rank_key` is the accepted execution-coordinator Phase 2 rank key (priority, urgency, dependency order, readiness, `ready_at`, …), carried verbatim. Integers compare numerically.
- No free-form semantic scoring, model preference, Issue age, branch-existence or chat-memory heuristic participates.
- Candidates arrive through accepted projections. Candidate order in the input does not affect the result.
- Portfolio scope first fixes the best track and rank class, then applies the worker-scoped SHA-256 spread defined in `PORTFOLIO_PICKUP_V2.md`; repository-scoped v1 keeps the existing lexical tie-break.
- If `accepted_work_classes` is absent, the exact pre-#215 role/track behavior is preserved.

## 6. Identity boundary (decision 4)

| Identity | Scope | Used for |
| --- | --- | --- |
| `worker_session_id` | one chat/session, stable for its lifetime | equals the Manual Execution Session `Execution-Session-ID` in the worker-owned Session Record (#142/#144) |
| `coordinator_worker_id` = `<worker_system>:<worker_session_id>` | runtime | the execution-coordinator `worker_id` for claim/acknowledge/release and live claim/session reviewer-independence checks |
| `review_provenance.system + model` | one review-capable session when explicitly observed | durable Review Provenance signature eligibility only; not runtime ownership, capability or rank |
| `execution_attempt_id` | one discovery cycle | the execution-coordinator `AutonomousAttempt.attempt_id` for 3C, and the audit trail |

The Session Record stays a soft, worker-owned provenance record. The runtime claim is the only atomic ownership. Neither is a cryptographic identity. Two chats must never share a `worker_session_id`.

## 7. Discovery cycle (decision 5)

One cycle is one `classify` evaluation over one freshly gathered evidence set, identified by `execution_attempt_id`.

- A cycle submits **at most one** claim.
- A rejected claim, or any other disposition, ends the cycle. The next cycle re-reads live evidence under a **new** `execution_attempt_id`.
- A recommended attempt id is `<worker_session_id>:c<N>` with `N` increasing within the chat. Uniqueness is required; the format is advisory.

## 8. Provider-local tool surfaces (decision 6)

`tool_surfaces` records which tools the chat can actually invoke right now. It is availability evidence, **not capability**, and it never participates in candidate matching. v1 defines these tags:

| Tag | Meaning |
| --- | --- |
| `github:read` | read live Issues/PRs/files of the target and devflow |
| `github:write` | create branch/commit/PR/comment in the target |
| `coordinator:claim` | invoke the execution-coordinator serialized mutation lane (claim/acknowledge/release) |

Work dispositions require all three. If one is missing, the result is `NEEDS_EVIDENCE` / `PROVIDER_SURFACE_MISSING`, and the missing tags appear in `reason_detail`. This is a provider-local limitation. The worker must not fall back to uncoordinated implementation, and the common authority model is not weakened for that provider.

## 9. Source references (decision 7)

`source_refs` carries canonical references only:

- the Control ref `kinoko34077/devflow#N`;
- the selected `owner/repo#N`;
- when relevant, PR refs and exact SHAs.

It never copies Issue bodies, acceptance text or checkpoints. The worker must re-read the referenced objects before mutation. The result is a pointer into durable truth, not a copy of it.

## 10. Broad-instruction rule

A missing Issue number in the user prompt is **not** a reason to ask the user. If `target_repository` is known from the prompt or the working context, and the classification returns a work disposition, the worker proceeds to the claim without asking the user to choose among machine-resolvable candidates.

A worker may normalize an explicit operating-mode instruction such as 「監査だけ」「軽い保守だけ」「レビューだけ」 into `accepted_work_classes` according to the accepted integration procedure. It must not infer a hidden preference from provider identity, repository language, model reputation or prior chats. `work_intent` itself remains non-authoritative input to the classifier.

The worker asks the user only when the missing information is authoritative and cannot be derived safely:

- portfolio evidence itself is unavailable or ambiguous after `target_repository = null` is resolved through the accepted #208 contract;
- the disposition is `NEEDS_HUMAN`;
- proceeding would require a credential/session/permission change;
- `PROVIDER_SURFACE_MISSING` holds and no safe read-only path satisfies the task.

For any other non-work disposition, the worker reports the typed disposition and does not invent a task.

## 11. Boundaries preserved

- Already-open chats only. There is no provider launch and no provider-to-provider spawning.
- One chat/session is one worker context.
- Live GitHub/devflow is the source of truth; chat history is not durable task authority.
- Release/deploy/publication, credential/session/permission, destructive, shared-history and difficult-to-reverse operations remain Human-gated. They surface as `NEEDS_HUMAN` and are never automated by this contract.
- There is no second scheduler, queue, task database or provider-specific priority authority. Controller negotiation stays deferred (#188), and adoption stays `PILOT` (#189).
- Stage 1 does not add effort scoring, batching, daemon workers, audit-supply automation or task manufacture. Those remain separately staged under #215.

## 12. Phase B handoff (per-session worker profiles)

Phase B must define, for each of `codex`, `claude` and `chatgpt`, how a session produces the request's identity/profile fields reproducibly. A Phase B profile MUST supply:

- `worker_system`;
- a unique `worker_session_id`, with its rule for stability across the chat's lifetime;
- an `execution_attempt_id` generation rule;
- `capabilities[]` and `environment[]`, each with an explainable, reproducible derivation from what the session can verify about itself, and never from the provider/model name;
- `tool_surfaces[]` derived from the tools actually available in that chat at bootstrap time;
- when the session explicitly reports a Review Provenance signature, preserve that direct `system + model` value without deriving it from provider identity;
- a confirmation that no secret, token, cookie or session material enters any field.

Phase B does not require `accepted_work_classes` or `review_provenance`. Omitted work classes mean unconstrained legacy behavior. Omitted review provenance preserves ordinary review behavior but makes an otherwise-eligible explicit different-reviewer demand fail closed for missing required signature evidence.