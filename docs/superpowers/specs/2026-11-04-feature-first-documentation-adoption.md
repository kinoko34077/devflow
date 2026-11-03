# Feature-first documentation adoption: KAEP slice

Status: implementation design for `documentation-refactor-workbench#4/#5`.

## Goal

Give an agent a short, feature-specific route to the existing KAEP contract, operational procedure, implementation, tests, and live owner Issues without copying those authorities or changing KAEP behavior. Preserve the existing `tools/kaep_*.py`, `docs/spec/KAEP_*.md`, schema, CLI names, Actions, and test paths until a later code-structure gate proves a compatible move is worthwhile.

## Evidence and constraints

- Base: `devflow@ff607c5ee5b9a68b9d1327b399fc20dde3711e1c`.
- Workbench design: `documentation-refactor-workbench#4`, pilot `#5`, roadmap M0–M9.
- Live `docs/**`: 135 files (93 Markdown, 34 JSON, 4 YAML/YML); the workbench's earlier 97-file inventory is historical and must not be treated as current.
- The feature route is an index, not an operational state cache, claim/lease, permission grant, or replacement for a contract.
- Google Drive originals remain external authorities; no private source text is copied into devflow.

## Chosen approach

Add one small `features/kaep/` route package:

1. `README.md` explains route selection and safety boundaries in plain language.
2. `manifest.json` is a machine-readable discovery index. It contains only route conditions and source paths; it does not contain mutable state, authorization, or duplicated parameter rules.
3. A standard-library test verifies that the manifest is valid, every route path exists at the same revision, routes remain disjoint by purpose, and the README names the same canonical source families.

The route points to current source files. It does not move or rewrite them. The first PR is document-only and can be reverted as one unit.

## Acceptance gates

### G1 — information and contract preservation

- Inbox, discovery, send, implementation-audit, and history routes each reach the existing canonical docs, code, and tests.
- The README explicitly states candidate/observation ≠ Claim or permission, and partial/unknown ≠ no work.
- No CLI flag, schema value, actor/recipient rule, or current-state assertion is redefined in the new files.

### G2 — quality and compatibility

- Existing KAEP tests remain unchanged and pass to the extent the environment supports them.
- The new route test fails closed for missing or duplicate paths.
- Existing import/CLI/Actions paths remain in place.

### G3 — measurable improvement

- The route makes the first relevant KAEP source discoverable without reading unrelated KAEP history.
- The PR records baseline and post-change route evidence; it does not claim a performance improvement from documentation alone.
- Code restructuring is held until M5 document acceptance and a separate D1 dependency/ownership diagnosis identify a real improvement target.

## Deferred work

After this document slice is reviewed and accepted, inspect KAEP code ownership and dependency direction. Only then consider a bounded internal refactor with characterization tests, compatibility shims for public `python -m tools.*` entry points, and separate G1/G2/G3 evidence. Do not move code merely to mirror the feature directory.

