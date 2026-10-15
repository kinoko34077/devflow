---
name: Repository Control
about: Cross-repository current-state index for one managed repository
title: "[REPO] "
---

## Repository

`kinoko34077/<repository>`

## Work Status

`NEEDS_AUDIT`

## Type

`AUDIT`

## Repository State

`ACTIVE`

## Priority

`P2`

## Risk

`LOW`

## Audit SHA

`UNSET`

## Active Work

None.

<!-- Transitional manual Control summary. Preserve cross-repository context and
     local-work fallback while M3.1 per-repository/per-consumer admission is
     unproven. Do not maintain a second task ledger: owning repository Issues/PRs
     are canonical, and the central devflow producer owns machine projections.
     Do not manually edit DEVFLOW_REPOSITORY_PROJECTION_V1 or
     DEVFLOW_HUMAN_PORTFOLIO_V1 fenced blocks. -->

## Next Action

`Initial STANDARD audit [AUDIT]`

<!-- Retain Human, policy, cross-repository and explicit audit decisions here.
     During M3 P0/P1, local-task instructions remain valid manual fallback.
     Narrowing to cross-repository/Human/policy-only semantics requires separate
     M3.3 admission after real per-consumer source/fallback verification. -->

## Canonical Entry Points

<!-- Exact repository-local paths/Issues/PRs a fresh agent should open after this Control Issue. -->

- README / agent entry: `<path or none>`
- Current State: `<path or none>`
- Specifications: `<path(s) or none>`
- Tests / verify: `<path/command or none>`
- Active local Issue / PR: `<reference or none>`

## Control Notes

Keep this Issue open as the cross-repository index unless the repository is intentionally retired. Detailed implementation belongs in the owning repository's Issue/Work Order/PR. During the M3 P0/P1 dual-read transition, keep Active Work and Next Action as manual fallback and preserve Human/policy/cross-repository decisions; do not duplicate every local TASK status transition here. Machine-derived local TASK facts are generated centrally and are read-only, not execution permission. If projection source is missing, stale, untrusted, incomplete or truncated, inspect owning Issues and retain manual fallback; never infer an empty task queue. Do not remove manual local-work authority before separately accepted M3.1/M3.3 per-repository and per-consumer admission. Update this Control when Audit SHA, state, Priority/Risk, meaningful manual fallback, Next Action, canonical entry points, or cross-repository readiness changes.
