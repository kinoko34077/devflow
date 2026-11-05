# Task Checkpoint Cursor feature route

This directory is a feature-first navigation entry, not a second Cursor
contract or state store. The listed documents, implementation, tests, owning
Issues, CI, and live repository state remain authoritative at their existing
locations. `manifest.json` only selects the smallest relevant route.

## Choose the route

## resume

Use when a successor needs the current `first_unfinished` recovery frontier.
Start at `docs/operations/TASK_CHECKPOINT_CURSOR.md`, then read the owning
Issue, durable progress surface, and live Control before acting.

## audit

Use for read-only Cursor coverage, trust, pagination, or duplicate-marker
audits. Audit output is structural evidence; it does not establish semantic
eligibility or current work authority.

## write

Use when reviewing an authorized single-writer Cursor transport. The helper is
not an atomic CAS, lock, lease, Claim, or permission mechanism. Read-before-
write and readback uncertainty must remain visible.

## contract

Use when parser, renderer, sentinel, field, warning, or specification
consistency changes. Read the operations contract and design/reconciliation
specification before changing code or tests.

## Safety and ownership

- A Cursor locates one recovery frontier; detailed evidence, decisions,
  blockers, PR/CI/Review state, and Control remain at their owning sources.
- Missing, stale, partial, drifted, duplicated, or ambiguous observations do
  not become clean success or no-work.
- This route does not move files, perform writes, change credentials, or grant
  execution authority. Current HEAD, review, CI, and writer authority are
  always checked live.
