# Project Sync Closed Event Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Keep event-sync membership consistent with the existing open-or-already-tracked Issue selection rule and retain attempted mutation targets through post-write verification.

**Architecture:** Reuse `select_canonical_issues` for event-sync eligibility and read the current trusted Issue before Project mutation. Preserve every selected mutation target in the existing post-write readback and verify path, including when the Issue closes before Project membership becomes visible.

**Tech Stack:** Python 3.10, unittest, GitHub REST and GraphQL adapters already used by `scripts/project_sync.py`.

**Spec:** `docs/project/PROJECT_SYNC.md`; finding and acceptance: devflow #988, discovered under #801.

## Global Constraints

- The GitHub Project is a display projection; the Issue remains canonical.
- Only open Issues and already-tracked closed Issues are selected by the existing canonical selector.
- An Issue selected for mutation stays in readback verification through the bounded delayed-membership retries, even if it closes after the write.
- Preserve actor admission from #820/#822, Project-wide concurrency from #373, and Health/readback behavior from #406.
- Do not change credentials, permissions, workflow policy, Project schema, or live settings.

## Review Focus

- Closed and untracked event Issue: do not add a Project item.
- Stale open event snapshot with a currently closed, untracked Issue: use live state and do not add.
- Closed but already-tracked Issue: continue synchronizing it.
- Open and untracked Issue: continue allowing it into the Project.
- Issue closes after an open-untracked mutation while membership is delayed: keep it in readback and report persistent drift rather than a clean empty verification.
- Untrusted event initiator: existing actor gate remains unchanged and covered separately.

### Task 1: Align event-sync with canonical Issue selection

**Files:**
- Modify: `scripts/project_sync.py`
- Modify: `docs/project/PROJECT_SYNC.md`
- Test: `tests/test_project_sync.py`

**Interfaces:**
- Reuse existing `reread_event_issue(rest, event_issue, control_trust_service)` and `select_canonical_issues(issues, tracked_items, control_trust_service)`.
- Carry the pre-write selected Issue identity into readback so post-write closure cannot remove an attempted mutation from verification.
- No new public API or synchronization state.

- [x] Add focused run-level regression tests for closed-untracked and stale-open/current-closed events, plus positive open-untracked and closed-tracked cases.
- [x] Add a run-level regression for an Issue that closes after the open-event write while Project membership remains delayed; verify it is retained through both bounded read retries and persistent drift fails.
- [x] Run the new tests and confirm they fail because the current path processes the event payload directly and adds the item.
- [x] Read the latest trusted Issue before event writes; pass it through the existing canonical selector against the discovered Project snapshot. Keep attempted mutation targets in post-write live readback even if the latest canonical selector would now exclude a just-closed, not-yet-visible item.
- [x] Document the event eligibility rule alongside the full-sync rule.
- [x] Run focused Project Sync tests, the repository test suite, and `git diff --check`; verify the actor gate, writes, Health memory, and derived audit label cases remain covered. Project Sync module: 70 PASS; compile and diff checks PASS. Local full suite on the original PR tree: 2,569 executed, 19 failures and 1 import error in environment-dependent cases; rerun for the review-fix tree. Exact-head CI is required.
- [ ] Commit the bounded change, open a PR linked to Issue #988, obtain exact-head checks and Formal Review/readiness, then integrate through the existing safe path and verify current main.
