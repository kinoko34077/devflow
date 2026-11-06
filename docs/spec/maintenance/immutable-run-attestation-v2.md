# SMC immutable completion attestation v2 — isolated candidate (devflow #588)

## Status
**PROPOSED / CODE-ONLY CONTRACT. NOT A LIVE COMPLETION WRITER.** This additive v2 proof is a prerequisite to moving an audit-coverage projection from historical `LEGACY_SCOPE_UNBOUND` toward verifiable current-scope coverage. The accepted `devflow-maintenance-run:v1` record, existing publisher, native supply, exact 3C, and execution-coordinator Claim authority remain unchanged. Do not treat module presence or a fabricated v2 comment as an executed audit.

## Why the v1 record is insufficient

The v1 active-run block holds repository/slot, catalog digest, coverage key, fingerprint and depth. Its completed `RunRecord` comment omits the scope (kind/selector), coverage key and catalog digest, which can change in later catalog versions. A reader of a historical v1 comment cannot prove that a slot with the same name still denotes the same examined scope. `Audit SHA`, `DEEP`, or a comment timestamp do not fix the gap. #588 M0 observed 4 substantive v1 comments and 3 `BLOCKED` zero-coverage comments among 3 Pilot Ledgers.

## Proposed additive `maintenance-run.v2` contract

A single trusted Ledger completion comment includes:
- version-specific sentinel `<!-- devflow-maintenance-run:v2 -->`;
- complete validated v1-compatible run payload: repository, run identity/generation, lens, depth, fingerprint, result, time, findings and evidence links;
- **immutable per-run scope** (`kind`, `selector`) from the exact resolved slot at selection;
- **immutable coverage key** from the same accepted resolved slot;
- **canonical catalog digest** from the selected/accepted Common Baseline + repository catalog.

The pure binding helper requires active-run repository/slot/generation/run ID, fingerprint, depth, coverage key, catalog digest and Lens to agree with both the completion and exact resolved catalog slot. Any changed catalog digest, retired slot, wrong Lens or mismatch fails closed. Parser requires exact closed v2 fields, valid digest, typed scope, valid v1 completion and duplicate-free JSON.

## Backwards compatibility

- v1 sentinel, payload, historic Ledger comments and machine reader/writer remain unmodified. v1 historical runs stay `LEGACY_SCOPE_UNBOUND`; **never backfill missing scope/digest by guessing current catalog**.
- v2 comment parser is opt-in and independent of v1 parser; publishing v2 through the real `complete-maintenance` workflow is **not** enabled by this code-only milestone.
- A future dual-format reader must verify **GitHub API Ledger Issue owner**, exact comment URL+Issue ID+author association, whether the published history is complete/paginated, exact current catalog digest and slot binding, actual observed source-state fingerprint, same run-ID conflict and evidence sufficiency.
- Merely matching `catalog_digest` and `fingerprint` strings is not cryptographic attestation of the worker or external facts. The source catalogue/provenance must be independently read from authorized GitHub sources.
- Fail closed for v1/v2 disagreement, ambiguous duplicates, unknown versions, invalid signatures of trusted native identity, stale source, denied permission, missing CI/real probe evidence or unresolved active Claim.

## Activation path (M4→M5)

1. Accept this small offline parser/binder with real exact-head tests, native Review and postmain Required CI.
2. Separately add dual-v1/v2 Ledger reader and coverage projection logic, preserving exact source trust and NEVER_RUN/BLOCKED behavior.
3. Prove an isolated fake-native complete/rollback/replay/restart that attaches only to the current active-run generation, with no duplicate published work or miscredited successful audit.
4. Only after bounded normal review/CI and one true existing authorized Pilot-native run may the writer emit v2. Never activate it merely because a machine selector chose work or an agent is idle.
5. The 4th repository, fleet-wide `ENABLED`, actual GH credential/permission changes, external deploy and protected effects remain separate authorization and proof gates.

## Quality gates

Test v1 compatibility, v2 round-trip determinism, duplicate/unknown JSON, mismatched digest/scope/slot/generation/source fingerprint, wrong depth/Lens, malformed result/time, absent authenticated owner and no promotion of BLOCKED/SUPERSEDED/NEEDS_REAUDIT into CLEAN. Code-only success never implies a completed real-world audit or a read-write rollout.
