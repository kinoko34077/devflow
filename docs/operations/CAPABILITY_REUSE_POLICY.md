# Reuse-first capability / API contract for managed repositories

Authority: user decision 2026-10-21 JST; [devflow #758](https://github.com/kinoko34077/devflow/issues/758); [devflow AGENTS.md](../../AGENTS.md). This document defines **cross-repository discovery and acceptance rules**, not the internal implementation of a particular product. The owning repository's current spec/API and user requirements remain authoritative.

## Mandatory cross-repository centralization preflight

Authority: user decision 2026-11-25 JST; [devflow #1136](https://github.com/kinoko34077/devflow/issues/1136).

Before starting, switching work/repositories, or expanding scope, determine:

- Can this be a shared mechanism across the managed GitHub repositories, using or extending an existing canonical implementation rather than copying it?
- Are identical implementations, rules or settings being duplicated, or would a future common change require updates to every consumer?
- Is the proposed local work necessary discovery or minimal representative verification, or repetitive per-repository implementation/adoption before the shared mechanism is ready?

Default order: identify the common problem → discover existing mechanisms → design and implement the shared mechanism → minimal representative verification → consumer adoption. Stop repetitive local fixes once representative evidence is sufficient; return to the shared design. **Cross-repository rollout is not cross-repository centralization.** Separate mechanism acceptance from rollout; never require adoption by all repositories to finish the mechanism. Permit local implementation only for a concrete technical, semantic, ownership or cost/benefit reason. Record that reason in the owning Issue/PR. An existing roadmap alone does not justify repetitive work; prioritize the user's objective and reassess the route. Preserve all safety, authority and verification boundaries; do not force unrelated responsibilities into a common owner.

## Mandatory pre-implementation lookup

For every new feature, bug fix or UI component, before implementation:
1. **Define behavior, not naming:** input/output, units, valid ranges, state owner, error/reset semantics, UI interaction, accessibility and expected visual consistency.
2. **Discover:** read the relevant capability/API catalog or module index in the owning repo and any connected shared-library repo (e.g. Site Kit). Follow the catalog to the **actual current implementation, public entrypoint, tests and current Issue**; search existing source for equivalent semantics. Do not assume a title, comment or exported symbol is a stable API.
3. **Classify:** (A) semantically identical: **reuse the existing contract/component**; (B) same responsibility, missing variation: **extend its owner / configuration or add a thin adapter**, with tests; (C) genuinely different meaning/change reason: separate module is allowed, record the distinction. Visual appearance alone is not a reason to fork a standard control; distinct musical/physical semantics may be.
4. **Trace:** in the owning Issue/PR, identify the capability ID, selected export, behavior gaps, consumer adapters, old duplicate removal/migration, and acceptance checks. For a justified fork/exception document why extension is unsuitable, scope, owner, expiration/revisit condition and compatibility consequences.
5. **Verify:** functional and negative tests plus an **architecture/reuse gate** where the code can be mechanically checked. A successful unit test of duplicate code is not proof of appropriate reuse. Check visible UI consistency on the actual tested entry surface, not only underlying conversions.

### Acceptance boundaries
- Never copy an existing value parser, state controller, domain formula, input component or common style solely to make a new consumer work. New capabilities must import/version-pin the established contract (or change that contract with backward-compatible tests).
- A consumer owns its application state and genuinely specific interactions; shared modules own shared **knowledge**. Do not conflate a shared JavaScript module API with an HTTP API. Do not force unrelated domain logic into Site Kit or another cross-repo owner.
- Legacy/transition exceptions must be explicit and narrowly allowlisted with owning migration Issues; do not silently grandfather new files or accept permanent bypasses.
- The ledger is a **discovery index** with one authority per capability, not duplicated specifications. Technical behavior is written in the owning repository. Multiple catalogs should point to one canonical contract.
- Architecture checks should be scoped to detectable invariants, have negative fixtures, and distinguish strict checks from human review. Static grep alone cannot prove all semantic duplicates.
- Existing behavior, safe error handling, user input, native ABI, release and real-device acceptance are separately gated. Do not merge an unverified functional rewrite in the name of architectural purity.

## Catalog contract (repository-local)
A catalog entry should provide:

`Capability ID | behavior/dimensions | authoritative owner | public entrypoint | consumers/adapters | tests/CI | status | exceptions/migration Issue`

A capability entry is **accepted** only when its actual code/API and tests are verifiable at a concrete revision. Mark planned, experimental and consumer-adopted states separately. The catalog must route to the specification and stable exports; it must not hide older incompatible definitions.

## Example: Frequency Warp parameter units
- Owner: `frequency-warp-vst#77/#79`, `docs/PARAMETER_BINDING_SPEC.md`, `web-demo/parameter-units.mjs`, `parameter-binding.mjs`, `frequency-unit-field.mjs`.
- Reuse codec and canonical binding for Hz/12-TET note+cents/rail-%/ratio when the parameter dimension is compatible. A virtual-root linear integer slider is a legitimate **specialized gesture adapter**, not an excuse to duplicate pitch parsing or keep parallel Hz state.
- `kinotch-site-kit` owns generic site shell and optional UI component facilities, *not* the Frequency Warp domain parameter codec by implication. Any cross-repo promotion requires an explicit versioned interface and verified consumer integration.

## Agent and reviewer handoff
Before declaring a feature complete, report which existing capability was reused, which component was extended, and whether any duplicate remains. Run executable structural guards as well as functional tests. If no reusable contract exists, record the search evidence and define the new owner. Relevant work: [devflow #758](https://github.com/kinoko34077/devflow/issues/758).
