# Plan: Bootstrap standard generated-artifact capability

Issue: devflow #1050 (rollout #386 remains separate)
Base: `19c13342e714dc63bea119e5875a70337235466d`

- [x] Bootstrap/control, Issue, writer, and safety boundaries mapped.
- [x] Design records legacy behavior, default install, shared-writer reuse, and permission gates.
- [x] Add failing contract/provisioning tests for optional feature IDs, standard request defaults, legacy replay, manifest creation, idempotent retry, conflicting seed refusal, no-output N/A, and fixed-recipe selection.
- [x] Implement the request/schema/executor extension, capability status, and a pinned read-only Caller that reuses the existing generic rollout workflow for dry-run only. The Caller cannot request effectful write mode.
- [x] Update Bootstrap spec/operations, feature index, and Issue lifecycle manual / development control with the new-repo completion and separate finite rollout rule. The canonical Drive development principles source was also updated and read back.
- [x] Run focused Bootstrap/generated-artifact suites and full repository suite. Current full run: 2,711 tests, 19 failures and 1 error; no new standard-feature test failed, and remaining failures are environment-dependent. See Session Record and command output for details.
- [ ] Inspect final diff/workflow permissions and prepare a reviewable branch PR with exact test/CI evidence and Human Gates.
- [ ] Obtain exact-head formal review and required CI; do not merge any writer-permission or credential change.
- [ ] After explicit authorization and approved credential are verified, create one private test-scoped repository through canonical Bootstrap; capture run/CI/head, feature entry, no-output N/A, legacy safety, and recovery evidence. A representative admitted-recipe write E2E also needs a reviewed caller, exact recipe admission and permission gate; current generic writer activation remains false.
- [ ] Close #1050 only when its full acceptance (including actual eligible-recipe Bootstrap dispatch/E2E and review/CI) is proven. Hand the accepted baseline and remaining finite existing-repo cohort to #386.

Ruling: Bootstrap now installs a pinned dry-run Caller that reaches the existing shared producer and read-only verifier/planner for registered recipes. The effectful generic writer is still disabled, and the recipe registry remains finite and repository-specific. Do not describe dry-run integration as effectful write acceptance. Complete the actual new-repository write path only through the exact reviewed recipe/caller and per-repository Human/security gates required by #1050.

## Stop / escalation rules

Do not create or delete a GitHub repository, modify secrets/credentials, expand workflow permissions, enable an unadmitted recipe, or perform effectful writer execution without its exact existing Human Gate. Continue all reversible local and reviewable work first.
