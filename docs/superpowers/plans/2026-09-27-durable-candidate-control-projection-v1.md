# Durable Candidate Control Projection v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first post-spec slice for Durable Candidate Source Contract v1 in `devflow`: deterministic parsing/validation of the Repository Control `DEVFLOW_EXECUTION_CANDIDATES_V1` block plus bounded Repository Control template guidance, without adding runtime scheduling or claim mutation.

**Architecture:** Keep the owning repository Issue/Work Order as detailed durable authority. `devflow` provides a small pure-Python parser/validator that reads one optional versioned candidate block from the unique Repository Control, verifies each record against an exact owning Issue snapshot and canonical body SHA-256, and returns validated projection records/diagnostics. The validator remains read-only and does not discover work from prose, Project fields, PR/branch existence, labels, or runtime state.

**Tech Stack:** Python standard library (`dataclasses`, `hashlib`, `json`, `re`, `urllib.parse` only where needed), `unittest`, existing devflow Markdown Issue templates.

**Spec:** `docs/superpowers/specs/2026-09-27-durable-candidate-source-contract-v1-design.md`

## Global Constraints

- Candidate source is one optional `DEVFLOW_EXECUTION_CANDIDATES_V1` JSON block in the managed repository's devflow Repository Control.
- Owning repository Issue/Work Order remains detailed durable task authority; Control data is a hash-bound reviewed projection only.
- Canonical body digest: `null -> ""`; CRLF/lone-CR -> LF; no trimming; no Unicode normalization; UTF-8; SHA-256 serialized as `sha256:` + 64 lowercase hex characters.
- Ordinary roles are exactly `implementer`, `reviewer`, `verifier`, `integrator`.
- Ordinary role/state/action guards are exactly: implementer=`READY_FOR_IMPLEMENTATION` with `SPECIFY|IMPLEMENT`; verifier=`AWAITING_REVIEW` with `VERIFY`; reviewer=`AWAITING_REVIEW` with `REVIEW`; integrator=`AWAITING_REVIEW` with `MERGE`.
- `IMPLEMENTING` is not fresh ordinary discovery; recovery/resume/takeover remains out of scope.
- Repository State other than `ACTIVE` emits no ordinary candidates.
- Missing/duplicate/malformed/stale/unsupported/contradictory source state fails closed.
- Control, owning task Issue, and optional Work Order Issue require `author_association` in `OWNER|MEMBER|COLLABORATOR`; missing/other associations fail closed and untrusted Control lookalikes are ignored for canonical selection.
- The deprecated owning-Issue `DEVFLOW_EXECUTION_CANDIDATE_V1` source is never consumed as fallback or corroborating authority.
- `requires_user_confirmation=true` is never autonomously claimable; sensitive-action permission is not granted by a validated candidate.
- Conflict keys are explicit only; omitted `conflict_keys` normalizes to `()` and is never inferred.
- No GitHub Project reverse authority, no prose-derived candidate construction, no ranking, scheduling, automatic claims, controller negotiation, runtime Issue #3 mutation, or bulk migration.
- This plan starts only after the parent policy PR #134 is merged and #125 identifies the accepted task-envelope contract as canonical authority.

## Review Focus

- CRLF/lone-CR body normalization must produce the same digest as canonical LF text while preserving all other whitespace and Unicode bytes.
- A syntactically valid candidate block with a stale body digest must emit no validated candidate, even if all projected readiness fields look claimable.
- Multi-track Controls must validate one task envelope with one or more roles; duplicate task envelopes or duplicate roles within an envelope invalidate the block rather than choosing one, and task-level gates cannot vary by role.
- A candidate with `USER_DECISION` plus `requires_user_confirmation=false`, or any unsupported role/state/action combination, must fail closed.
- Parser failure must never fall back to `Active Work`, `Next Action` prose, labels, PR/branch existence, the deprecated owning-Issue marker, or other heuristic sources.
- Outsider/untrusted authored Control, owning task, or Work Order Issues must never produce candidate authority even when their titles/bodies otherwise match exactly.

---

### Task 1: Canonical candidate block parser and body digest

**Files:**
- Create: `tools/durable_candidate_projection.py`
- Create: `tests/test_durable_candidate_projection.py`

**Interfaces:**
- Produces: `canonical_issue_body_sha256(body: str | None) -> str`
- Produces: `parse_candidate_block(control_body: str) -> CandidateBlock | None`
- Produces dataclasses: `CandidateBlock`, `CandidateEnvelope`, `CandidateRole`
- No GitHub network access in this task.

- [ ] **Step 1: Write RED tests for canonical body digest**

Add tests named:
- `test_digest_normalizes_crlf_and_lone_cr_only`
- `test_digest_preserves_leading_trailing_whitespace_and_unicode`
- `test_digest_treats_none_as_empty_string`

Assertions must compare exact `sha256:<64 lowercase hex>` values computed from explicit byte strings in the test.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m unittest tests.test_durable_candidate_projection -v`
Expected: FAIL because `tools.durable_candidate_projection` or the digest API does not exist.

- [ ] **Step 3: Implement `canonical_issue_body_sha256(body: str | None) -> str`**

Implement only the normalization/digest algorithm fixed by the spec. Do not trim or Unicode-normalize.

- [ ] **Step 4: Write RED parser tests**

Add tests for:
- no marker -> `None`;
- one exact valid block -> parsed `CandidateBlock`;
- duplicate/partial/reversed markers -> `ValueError`;
- malformed JSON -> `ValueError`;
- `schema_version != 1` -> `ValueError`;
- unknown outer/candidate fields -> `ValueError`;
- omitted `conflict_keys` -> `()`;
- explicit duplicate conflict keys -> `ValueError`.

- [ ] **Step 5: Implement parser/dataclasses minimally**

`CandidateBlock` fields: `schema_version: int`, `source_ref: str`, `repository: str`, `candidates: tuple[CandidateEnvelope, ...]`.

`CandidateEnvelope` fields: `task: str`, `task_body_sha256: str`, `task_work_status: str`, `entry_ref: str`, `scope_ready: bool`, `blocked: bool`, `requires_user_confirmation: bool`, `conflict_keys: tuple[str, ...]`, `work_order_ref: str | None`, `roles: tuple[CandidateRole, ...]`.

`CandidateRole` fields: `role: str`, `next_action_tag: str`.

`CandidateEnvelope` stores the task-level fields once, and each `CandidateRole` stores only `role` and `next_action_tag`; role-specific output later reuses the envelope `entry_ref` and safety fields.

Reject unknown authority-bearing fields rather than ignoring them.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run: `python -m unittest tests.test_durable_candidate_projection -v`
Expected: PASS for digest/parser tests.

- [ ] **Step 7: Commit Task 1**

```bash
git add tools/durable_candidate_projection.py tests/test_durable_candidate_projection.py
git commit -m "feat: parse durable candidate control projection"
```

### Task 2: Deterministic validation and normalized projection output

**Files:**
- Modify: `tools/durable_candidate_projection.py`
- Modify: `tests/test_durable_candidate_projection.py`

**Interfaces:**
- Consumes: `CandidateBlock`, `CandidateEnvelope`, `CandidateRole`, and `canonical_issue_body_sha256()` from Task 1.
- Produces: `IssueSnapshot(repository: str, number: int, state: str, body: str | None, html_url: str, is_pull_request: bool, author_association: str, title: str, work_status: str | None)`.
- Produces: `ControlContext(source_ref: str, repository: str, repository_state: str, next_action: str, author_association: str)`.
- Produces: `ValidatedCandidate(task: str, role: str, entry_ref: str, conflict_keys: tuple[str, ...], scope_ready: bool, blocked: bool, requires_user_confirmation: bool)`.
- Produces: `ValidationDiagnostic(code: str, task: str | None, message: str)`.
- Produces: `validate_candidate_block(block: CandidateBlock, control: ControlContext, issues: dict[str, IssueSnapshot]) -> tuple[tuple[ValidatedCandidate, ...], tuple[ValidationDiagnostic, ...]]`.

- [ ] **Step 1: Write RED tests for identity/provenance and staleness**

Cover:
- `source_ref` mismatch;
- outer repository mismatch;
- untrusted/missing Control `author_association` -> zero candidates, while untrusted lookalikes are excluded from canonical selection by the upstream discovery boundary;
- repository state not `ACTIVE` -> zero ordinary candidates;
- task repository mismatch;
- owning Issue with missing/untrusted `author_association`;
- missing/closed owning Issue;
- PR object used as owning source;
- digest mismatch;
- duplicate task envelopes or duplicate roles within one envelope invalidate the block;
- task-level scope/blocker/confirmation fields cannot diverge by role because they exist only on the envelope.

Expected authority result for each invalid/contradictory case: no validated candidate for the affected source; block-wide structural contradictions such as duplicate `(task, role)` emit no candidates from the block.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m unittest tests.test_durable_candidate_projection -v`
Expected: FAIL because validator APIs do not exist.

- [ ] **Step 3: Implement identity/digest validation**

Validate exact source/control/task identities and canonical digest before evaluating readiness fields. Never fetch or infer substitute entries.

- [ ] **Step 4: Write RED lifecycle/safety tests**

Cover exact accepted combinations:
- implementer + `READY_FOR_IMPLEMENTATION` + `SPECIFY` -> valid;
- implementer + `READY_FOR_IMPLEMENTATION` + `IMPLEMENT` -> valid;
- verifier + `AWAITING_REVIEW` + `VERIFY` -> valid;
- reviewer + `AWAITING_REVIEW` + `REVIEW` -> valid;
- integrator + `AWAITING_REVIEW` + `MERGE` -> valid.

Also cover:
- `IMPLEMENTING` -> no fresh ordinary candidate;
- `BLOCKED`/`AUDITED`/`DONE` -> no ordinary candidate;
- unsupported role/state/action combination -> fail closed;
- `scope_ready=false` -> not claimable;
- `blocked=true` -> not claimable;
- `requires_user_confirmation=true` -> not claimable;
- `USER_DECISION` + confirmation false -> contradiction/fail closed;
- invalid entry repository -> fail closed;
- optional Work Order with missing/untrusted `author_association` -> fail closed;
- Protocol-v1-invalid conflict-key class -> fail closed;
- omitted conflict keys remain `()` and are not inferred.

- [ ] **Step 5: Implement lifecycle/safety/conflict-key validation**

Use exact tables/constants in this module; do not parse free-form Control/Issue prose to repair missing fields.

- [ ] **Step 6: Add Review Focus regression asserting no heuristic fallback**

Construct a malformed/absent candidate block whose surrounding body contains tempting `Active Work`, `[IMPLEMENT]`, PR URLs, labels-like text, and a deprecated `DEVFLOW_EXECUTION_CANDIDATE_V1` owning-Issue marker. Assert the parser/validator returns no candidate and never interprets those strings as source records.

- [ ] **Step 7: Run focused tests and confirm GREEN**

Run: `python -m unittest tests.test_durable_candidate_projection -v`
Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add tools/durable_candidate_projection.py tests/test_durable_candidate_projection.py
git commit -m "feat: validate durable candidate projections"
```

### Task 3: Repository Control template guidance and full devflow regression

**Files:**
- Modify: `.github/ISSUE_TEMPLATE/repository-control.md`
- Modify: `tests/test_issue_templates.py`
- Modify only if required for discoverability wording: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`

**Interfaces:**
- Consumes: exact marker names and schema fields from Tasks 1-2.
- Produces: optional authoring location/guidance for `DEVFLOW_EXECUTION_CANDIDATES_V1` without making it mandatory for existing Controls.

- [ ] **Step 1: Write RED template contract test**

Extend `tests/test_issue_templates.py` with a test asserting:
- Repository Control template documents `DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN/END` exactly once each;
- guidance states the block is optional/opt-in;
- guidance points to `docs/superpowers/specs/2026-09-27-durable-candidate-source-contract-v1-design.md`;
- no default candidate record is pre-populated that could accidentally authorize work.

- [ ] **Step 2: Run template tests and confirm RED**

Run: `python -m unittest tests.test_issue_templates -v`
Expected: FAIL before template update.

- [ ] **Step 3: Add bounded template guidance**

Add a short optional `Execution Candidates` guidance section after `Canonical Entry Points` or immediately before `Control Notes`. Do not require migration of existing Controls and do not duplicate the full schema in the template. The guidance must describe one task envelope with a non-empty `roles` array, not one flat record per role.

- [ ] **Step 4: Run focused template + projection tests**

Run: `python -m unittest tests.test_issue_templates tests.test_durable_candidate_projection -v`
Expected: PASS.

- [ ] **Step 5: Run full devflow test suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS with no Project-sync/review-readiness regression.

- [ ] **Step 6: Verify diff scope**

Confirm changed implementation files are limited to the new validator/tests/template plus a canonical-spec cross-reference only if actually necessary. Confirm no Project mutation, MCP behavior change, runtime mutation, or candidate migration is bundled.

- [ ] **Step 7: Commit Task 3**

```bash
git add .github/ISSUE_TEMPLATE/repository-control.md tests/test_issue_templates.py tools/durable_candidate_projection.py tests/test_durable_candidate_projection.py docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md
git commit -m "docs: expose optional durable candidate projection guidance"
```

If `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md` is unchanged, omit it from `git add`.

### Task 4: PR verification, formal review, merge, and authority reconciliation

**Files:**
- No product-code additions beyond Tasks 1-3.
- Update durable GitHub state: devflow #125, #16, #105, and #107 only where cross-repository summary materially changes.

**Interfaces:**
- Consumes: green exact-head branch from Tasks 1-3.
- Produces: accepted devflow validator/template slice and an explicit downstream handoff for `execution-coordinator#28` re-audit.

- [ ] **Step 1: Open one bounded implementation PR from a dedicated branch based on the accepted post-#132 main**

PR body must link #125, the accepted spec path, verification evidence, changed scope, non-goals, and rollback via revert PR.

- [ ] **Step 2: Confirm exact-head required verification**

Check the PR head SHA and required `verify` status. Expected: required check PASS for that exact head.

- [ ] **Step 3: Run Formal Review v2 on the exact head**

Review must explicitly inspect parser fail-closed behavior, digest semantics, multi-track handling, Human Gate behavior, and absence of heuristic fallback. Record review evidence in the PR/Issue according to devflow policy.

- [ ] **Step 4: Confirm review-readiness and unresolved-thread state**

Expected: review-readiness PASS and zero unresolved blocking review threads.

- [ ] **Step 5: Merge only if low/medium-risk merge policy remains satisfied**

Use the exact reviewed head. Do not release/deploy/publish or perform credential/permission/history operations.

- [ ] **Step 6: Verify merged main**

Confirm merged-main required verification PASS and re-run/confirm `python -m unittest discover -s tests -v` against merged main when local execution is available.

- [ ] **Step 7: Reconcile durable authority**

Update/close #125 as appropriate, reconcile #16/#105 from verified main, and change #107 Next Action from upstream-spec wait to a single explicit `execution-coordinator#28` re-audit/adaptation handoff. Explicitly record that the owning-Issue marker path from #126 is deprecated and that open execution-coordinator PR #32 must not merge unchanged; close/supersede it when the downstream re-audit establishes its replacement path. Do not create the runtime implementation PR in this task.

- [ ] **Step 8: Create the next separate plan**

After #125 + validator/template slice are accepted, re-read live `execution-coordinator` Control #107, Issue #28, `src/execution_coordinator/discovery.py`, `tests/test_discovery.py`, and current main SHA. Write a new plan specifically for adapting/superseding the provisional free-form Issue parser to the accepted Control projection contract.
