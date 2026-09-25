# Cross-Repository Agent Operations Implementation Plan

> **For agentic workers:** Execute this plan task-by-task on dedicated branches. Repository rename itself is a separate admin mutation and must not be fabricated.

**Goal:** Make devflow the deterministic start point for cross-repository GPT/agent work, define repository-local Issue operation, align Repository Base, and prepare a safe `devflow-test` → `devflow` migration.

**Architecture:** devflow owns the cross-repository operational contract and Current State index. Each managed repository owns detailed technical canon and local task records. Repository Base contains only a thin integration adapter. GitHub Project remains a one-way display layer.

**Tech Stack:** GitHub Issues, Pull Requests, Markdown, YAML, GitHub Actions, Python project-sync implementation.

**Spec:** `docs/superpowers/specs/2026-09-25-cross-repository-agent-operations-design.md`

## Global Constraints

- Do not force Repository Base adoption on managed repositories.
- Do not duplicate repository-local detailed specifications in devflow.
- Do not make GitHub Project authoritative.
- Normal changes use dedicated branches and PRs.
- Low-risk authorized merges may proceed after verification when rollback by revert PR is available.
- Release/deploy/publication/destructive/history-rewrite/security-sensitive operations require explicit user confirmation.
- Do not claim the GitHub repository rename happened until an admin-capable operation is observed.

## Review Focus

- A fresh agent starting from only a repository name must find the correct read order.
- devflow Work Orders and repository-local Issues must not compete for the same detailed task state.
- Non-Base repositories must remain operable without new structure.
- Base documents must reference, not duplicate, devflow semantics.
- The rename migration must not leave synchronization or Project configuration silently pointing at a stale repository identity.

---

### Task 1: Add devflow agent bootstrap and operating manuals

**Files:**
- Create: `AGENTS.md`
- Create: `docs/operations/AGENT_OPERATING_MANUAL.md`
- Create: `docs/operations/REPOSITORY_ISSUE_MANUAL.md`
- Modify: `README.md`

**Produces:** one human/agent entry point and two focused operational manuals.

- [ ] Define the exact bootstrap/read sequence.
- [ ] Define authority and handoff rules.
- [ ] Define repo-local Issue/Work Order creation, update, closure, and PR linking rules.
- [ ] Route README to `AGENTS.md` rather than duplicating the manuals.
- [ ] Review for conflicts with the design spec.

### Task 2: Make the operating contract canonical and machine-readable

**Files:**
- Modify: `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
- Modify: `.devflow/WORKFLOW.yaml`
- Modify: `.github/ISSUE_TEMPLATE/work-order.md`
- Modify: `.github/ISSUE_TEMPLATE/repository-control.md`

**Produces:** canonical and machine-readable read order, Issue authority, control-update triggers, and rename lifecycle.

- [ ] Add agent bootstrap contract to canonical spec.
- [ ] Add repository-local Issue authority/lifecycle.
- [ ] Add Control Issue update triggers and restart contract.
- [ ] Extend YAML without copying repository-specific technical detail.
- [ ] Make templates expose the references needed for handoff.
- [ ] Check YAML syntax via CI or parser evidence.

### Task 3: Prepare the devflow repository for rename

**Files:**
- Inspect/modify only hard-coded repository-name dependencies required for safe migration.
- Update operational docs with a two-phase rename checklist.

**Produces:** repository behavior that does not depend unnecessarily on the old literal name and a verifiable post-rename checklist.

- [ ] Search current repository for `devflow-test` references.
- [ ] Classify each as historical, current identity, or runtime dependency.
- [ ] Update only references safe before rename; leave historical references intact where they identify old Issues/PRs.
- [ ] If runtime code changes are required, add a failing test first and follow RED→GREEN.
- [ ] Record the final admin rename step as pending until observable.

### Task 4: Align Repository Base

**Files:**
- Modify: `AGENTS.md`
- Modify: `.kinotch/AGENT_RULES.md`
- Modify: `.kinotch/meta/08_GITHUB_DEVELOPMENT_CONTROL.md`
- Add repo-local Issue template/guidance only if needed; do not duplicate devflow rules.

**Produces:** Base-adopted repositories enter through devflow Control state and then continue through Base-local canon.

- [ ] Put cross-repository bootstrap before Base-local reading when applicable.
- [ ] Point Base rules to devflow manuals/spec rather than restating them.
- [ ] Preserve local-only read economy.
- [ ] Verify Base-managed vs Project-owned boundaries remain unchanged.

### Task 5: PR verification, merge, and state reconciliation

**Files/records:**
- devflow Work Order #46
- Repository Base Issue #7
- relevant devflow Repository Control Issues

**Produces:** merged low-risk documentation/control-plane changes with recorded evidence.

- [ ] Create PRs for both branches.
- [ ] Review exact diffs against spec and Work Order acceptance criteria.
- [ ] Run/read all available CI and required checks.
- [ ] Re-read merged default-branch entry points.
- [ ] Merge if low-risk and verified; otherwise fix before merge.
- [ ] Update Control Issues with accepted SHA and Next Action.

### Task 6: Admin repository rename and post-rename acceptance

**Produces:** actual repository identity `kinoko34077/devflow` and verified synchronization after migration.

- [ ] Perform GitHub repository rename using an admin-capable path.
- [ ] Confirm current repository identity is `kinoko34077/devflow` and old URL redirects as expected.
- [ ] Verify branch protection, Actions, Issues/PRs and required repository secrets/configuration remain usable.
- [ ] Verify GitHub Project Auto-add targets the renamed repository identity.
- [ ] Run full Project `reconcile` then full `verify`.
- [ ] Require Sync Health accepted state with full expected coverage, drift 0 and errors 0.
- [ ] Update remaining current-identity references and close Work Order #46 only after this evidence exists.
