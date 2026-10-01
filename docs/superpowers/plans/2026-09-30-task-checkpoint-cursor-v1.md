# Task Checkpoint Cursor v1 Implementation Plan

> **Standing-policy note (2026-10-01):** `devflow#290` / PR #291 supersedes this historical implementation plan wherever it describes the Cursor as optional. Current standing policy requires one Cursor for eligible single-frontier multi-step work and pairs it with the designated durable progress surface. The historical task steps below are retained as implementation provenance.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight, standard-library-only Task Checkpoint Cursor helper that projects one canonical first-unfinished recovery frontier, warns on drift instead of rejecting ordinary duplicate/stale work, and integrates that projection into current devflow recovery policy.

**Architecture:** Keep all cursor semantics in one pure Python module with no network writes. GitHub Issue transport remains outside the helper; workers or future thin adapters discover/update the one canonical trusted comment and use the helper for parse/render/compare/transition/post-write verification. Existing owning Issue, durable-progress, Execution Session, Review/CI and execution-coordinator authority remain unchanged.

**Tech Stack:** Python standard library, `unittest`, existing GitHub Issue/PR/Actions surfaces, Markdown/YAML-subset cursor comment.

**Spec:** `docs/superpowers/specs/2026-09-29-task-checkpoint-cursor-design.md` plus `docs/superpowers/specs/2026-09-30-task-checkpoint-cursor-v1-reconciliation.md`

## Global Constraints

- Cursor is navigation/drift projection only; never readiness, claim, lease, lock, CAS or fencing authority.
- Ordinary checkpoint/revision/post-write drift returns typed warnings and requires live re-read; it does not hard-reject normal work.
- Existing Human/security/merge/review/publication/credential/session/permission/destructive/shared-history gates remain fail-closed.
- One cursor represents exactly one canonical recovery frontier per task.
- Cursor transport uses one trusted owning-Issue comment with sentinel `<!-- devflow-task-checkpoint-cursor:v1 -->`.
- Pure helper uses Python standard library only; no new runtime dependency.
- No mandatory per-repository workflow/App migration.
- No RDC.
- `head`, when present, is a full 40-hex Git commit SHA to match devflow exact-head conventions.
- Checkpoint identifiers accepted by the helper use the stable ASCII token form `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`; task semantics/order still come from the owning durable plan, never identifier spelling.

## Review Focus

- A trusted valid cursor plus one untrusted copied sentinel must keep the trusted cursor usable while surfacing spoof/noise as a warning.
- Duplicate trusted markers must never be silently ordered by comment age or revision; return `WARN_DUPLICATE_MARKER` for explicit reconciliation.
- A cursor whose `first_unfinished` is unchanged but revision moved must return `WARN_REVISION_DRIFT`, not checkpoint drift.
- A post-write observed cursor differing in any canonical field from the intended write must return `WARN_POST_WRITE_DRIFT` rather than `OK_ADVANCED`.
- Terminal `first_unfinished: null` must render/parse round-trip without being confused with a missing/malformed marker.

---

### Task 1: Pure cursor parser, renderer and transition semantics

**Files:**
- Create: `tools/task_checkpoint_cursor.py`
- Create: `tests/test_task_checkpoint_cursor.py`
- Modify: `.github/workflows/project-sync-tests.yml`

**Interfaces:**
- Produces: `SENTINEL: str`
- Produces: `CursorFormatError(ValueError)`
- Produces: immutable `CursorState(schema_version: int, task: str, revision: int, last_completed: str | None, first_unfinished: str | None, head: str | None, evidence: tuple[str, ...], updated_at: str)`
- Produces: immutable `CursorResult(code: str, cursor: CursorState | None = None, live: CursorState | None = None, warnings: tuple[str, ...] = ())`
- Produces: `parse_cursor_comment(body: str) -> CursorState`
- Produces: `render_cursor_comment(cursor: CursorState) -> str`
- Produces: `inspect_cursor_comments(comments: Sequence[Mapping[str, object]], task: str) -> CursorResult`
- Produces: `compare_cursor(live: CursorState, expected_revision: int, expected_first_unfinished: str | None) -> CursorResult`
- Produces: `initialize_cursor(*, task: str, last_completed: str | None, first_unfinished: str | None, head: str | None, evidence: Sequence[str], updated_at: str) -> CursorState`
- Produces: `advance_cursor(live: CursorState, *, expected_revision: int, expected_first_unfinished: str | None, completed_checkpoint: str, next_first_unfinished: str | None, head: str | None, evidence: Sequence[str], updated_at: str) -> CursorResult`
- Produces: `verify_post_write(written: CursorState, observed: CursorState) -> CursorResult`
- Produces: `reconcile_cursor(live: CursorState, *, last_completed: str | None, first_unfinished: str | None, head: str | None, evidence: Sequence[str], updated_at: str) -> CursorState`

- [ ] **Step 1: Write the failing unit tests**

Add focused tests for:
- canonical render/parse round-trip;
- strict required fields, duplicate key, invalid schema/revision/task/checkpoint/head/timestamp/evidence shape -> `CursorFormatError`;
- missing marker -> `NO_MARKER`;
- only untrusted sentinel -> `NO_MARKER` + `WARN_UNTRUSTED_MARKER` warning;
- one trusted valid marker plus untrusted copy -> `OK_CURSOR` + warning;
- duplicate trusted markers -> `WARN_DUPLICATE_MARKER`;
- one trusted malformed marker -> `WARN_MALFORMED_MARKER`;
- exact compare -> `OK_MATCH`;
- checkpoint mismatch -> `WARN_CHECKPOINT_DRIFT` with live cursor;
- same checkpoint/revision mismatch -> `WARN_REVISION_DRIFT`;
- initialize starts at revision 1;
- normal advance increments revision and sets `last_completed` / next frontier;
- advance with drift returns warning and no prepared replacement cursor;
- identical post-write read -> `OK_ADVANCED`;
- differing post-write read -> `WARN_POST_WRITE_DRIFT`;
- reconcile increments revision and may move the frontier backward or forward explicitly;
- terminal `first_unfinished=None` round-trips.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -W error -m unittest tests.test_task_checkpoint_cursor -v`  
Expected: FAIL because `tools.task_checkpoint_cursor` does not exist.

- [ ] **Step 3: Implement the minimal pure helper**

Implement the interfaces above in `tools/task_checkpoint_cursor.py`.

Parser requirements:
- recognize exactly one sentinel in the comment body;
- parse exactly one fenced `yaml` block following the sentinel;
- support only the canonical v1 top-level fields and the `evidence` sequence;
- reject duplicate/unknown keys and invalid scalar forms;
- do not infer checkpoint order;
- treat `OWNER`, `MEMBER`, `COLLABORATOR` and repository-authorized `github-actions[bot]` as trusted marker sources; copied sentinels from other associations remain warnings/noise.

- [ ] **Step 4: Add the new module to compile verification**

Modify `.github/workflows/project-sync-tests.yml` so the Compile check includes `tools/task_checkpoint_cursor.py`.

- [ ] **Step 5: Run focused and full tests**

Run: `python -W error -m unittest tests.test_task_checkpoint_cursor -v`  
Expected: PASS.

Run: `python -W error -m unittest discover -v`  
Expected: PASS with zero failures/errors.

- [ ] **Step 6: Commit Task 1**

Commit message: `feat: add task checkpoint cursor helper (#233)`

### Task 2: Canonical policy and machine-readable workflow integration

**Files:**
- Modify: `docs/operations/DURABLE_PROGRESS_EXTERNALIZATION.md`
- Create: `docs/operations/TASK_CHECKPOINT_CURSOR.md`
- Modify: `AGENTS.md`
- Modify: `.devflow/WORKFLOW.yaml`
- Create: `tests/test_task_checkpoint_cursor_contract.py`

**Interfaces:**
- Consumes: Task 1 sentinel/outcome vocabulary and the reviewed v1 authority model.
- Produces: canonical operator procedure for read -> compare -> warn/re-read -> advance/reconcile.
- Produces: machine-readable workflow declaration that cursor is an optional task-level resume projection, not task/readiness/claim authority.

- [ ] **Step 1: Write failing contract tests**

Tests assert that accepted docs/workflow contain:
- `Task Checkpoint Cursor` and the exact sentinel;
- `first_unfinished` projection semantics;
- ordinary drift warning/re-read behavior;
- no readiness/claim/lease/fencing authority;
- single-frontier constraint;
- affected-surface reconciliation obligation when frontier moves;
- `AGENTS.md` resume order reads an accepted cursor before reconstructing historical checkpoint chronology;
- `.devflow/WORKFLOW.yaml` identifies the cursor as optional projection and keeps GitHub Project display-only.

- [ ] **Step 2: Run contract tests and verify RED**

Run: `python -W error -m unittest tests.test_task_checkpoint_cursor_contract -v`  
Expected: FAIL because the canonical integration is not yet present.

- [ ] **Step 3: Implement the smallest documentation/workflow changes**

Update only the sections required to route workers to the cursor helper and operator procedure. Do not duplicate the entire design spec into standing policy.

`docs/operations/TASK_CHECKPOINT_CURSOR.md` must document:
- recognized comment format and trust boundary;
- read/initialize/compare/advance/post-write/reconcile flow;
- warning codes;
- readiness/safety authority separation;
- single-frontier eligibility;
- fallback to ordinary durable-progress resume when no cursor exists.

- [ ] **Step 4: Run contract and full suites**

Run: `python -W error -m unittest tests.test_task_checkpoint_cursor_contract -v`  
Expected: PASS.

Run: `python -W error -m unittest discover -v`  
Expected: PASS with zero failures/errors.

- [ ] **Step 5: Commit Task 2**

Commit message: `docs: integrate task checkpoint cursor recovery contract (#233)`

### Task 3: Bounded real Issue-comment pilot and final exact-head verification

**Files:**
- No additional production file required unless the pilot exposes a concrete defect.
- Update durable progress on `devflow#233`.
- Update PR body/evidence for the implementation PR.

**Interfaces:**
- Consumes: Task 1 canonical renderer/transition semantics and Task 2 operator procedure.
- Produces: one real trusted cursor on `devflow#233` proving create/read/update/re-read recovery behavior without a repository-wide Actions deployment.

- [ ] **Step 1: Open the implementation PR from `feature/task-checkpoint-cursor-v1` to `main`**

PR body must use the validator-recognized list syntax:
- `- Formal review required: yes`
- `- Different reviewer required: yes`
- `- Implementer-System: ChatGPT`
- `- Implementer-Model: GPT-5.6 Sol`

- [ ] **Step 2: Require Required PR gate GREEN on the exact head**

Expected: `Required PR gate` SUCCESS for the current implementation head.

- [ ] **Step 3: Initialize the real `devflow#233` cursor**

Create exactly one trusted cursor comment whose `first_unfinished` names the first unfinished pilot/acceptance checkpoint. Immediately re-read and verify the stored canonical fields.

- [ ] **Step 4: Exercise one forward movement and one stale-expected comparison**

After the next durable checkpoint is accepted, update the same cursor comment to the next frontier and re-read it. Evaluate an intentionally stale expected revision/checkpoint against the live state and record the resulting warning semantics on #233. Do not create a second trusted cursor.

- [ ] **Step 5: Run full regression again on the final head**

Run through the Required PR gate: `python -W error -m unittest discover -v` plus compile check.  
Expected: PASS.

- [ ] **Step 6: Perform current-head reviews**

Record implementer Formal Review, then obtain a qualifying different-system/model current-head Formal Review because this changes devflow operational authority/source-of-truth semantics. Require review-readiness GREEN.

- [ ] **Step 7: Reconcile affected durable surfaces**

Before acceptance/exit, reconcile #233 status/checkpoints/blockers, the cursor, implementation PR exact head/review evidence, devflow Control #16 if its cross-repository summary changes, and any directly affected standing policy reference. Do not perform a global repository sweep.

- [ ] **Step 8: Stop at the merge boundary unless merge remains already-authorized, safely revertible and all current gates are satisfied**

No release/deploy/publication, credential/session/permission mutation, destructive/shared-history operation or RDC.