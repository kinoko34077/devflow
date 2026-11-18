# Design: standard generated-artifact capability in Repository Bootstrap

Date: 2026-11-18
Owner: devflow #1050
Base: `19c13342e714dc63bea119e5875a70337235466d`

## Decision

Extend the existing `repository-bootstrap.v1` request with an optional,
allowlisted `bootstrap.standard_features` array. New managed-repository
emitters request the existing `repo_native_dispatch` plus
`generated-artifact-writeback`. An absent list retains the exact legacy v1
retry behavior; the legacy `repo_native_dispatch` field remains accepted.

Bootstrap records the installed standard feature manifest under
`.devflow/standard-features.json`, reuses the existing
`.github/workflows/kinotch-repo-command.yml` for read-only status, and installs
one pinned dry-run-only Caller at
`.github/workflows/verified-artifacts-rollout.yml`. That Caller invokes the
existing shared `generated-artifact-rollout.yml` and fixed-recipe admission
path. The effectful writer remains disabled. This change introduces no new
writer core, scheduler, credential, secret or write permission. Existing files
are never overwritten; mismatches fail closed.

The common capability record, read-only status entry, and shared dry-run route
are installed by default, while effectful writes remain per-repository
admitted. A repository with no generated outputs reports
`NOT_APPLICABLE/NO_GENERATED_OUTPUT`. An output without a fixed admitted
recipe/caller reports a refusal/precondition state. The generic effectful
writer remains disabled until its existing review and per-repository
permission gates pass; the standard Caller cannot request write mode and does
not silently admit a recipe.

## Lifecycle rule

A generic mechanism is complete when a new managed repository receives the
standard entry and a representative new-repository use case passes. The
existing-repository migration is a separate finite rollout owner (#386). N/A,
equivalent existing implementation and Human/security hold are valid rollout
dispositions; fleet-wide completion is not part of the development Issue's
acceptance.

## Human gates

A live Bootstrap E2E may create one private, test-scoped repository only after
the existing approved credential and any workflow-seed permission are verified.
Changes that grant a repository's writer `contents:write`, alter credentials,
or activate an unapproved recipe require their existing explicit Human/security
approval. The local implementation, deterministic tests, CI/PR and read-only
evidence preparation continue independently of those gates.

## Acceptance evidence split

Local tests prove backward compatibility, feature installation, pinned
read-only shared-route admission, idempotence, fail-closed mismatch/refusal,
and no added write permission. A real private
Bootstrap run proves the new-repository creation path and no-output status.
If the new repository has no admitted generated recipe, it must not write. The
dry-run path reaches the existing verifier/planner for a newly registered
recipe. A representative eligible-recipe effectful writer E2E still requires
a reviewed caller, exact recipe admission and the separate permission gate.
The accepted testapp E2E remains evidence for the effectful writer itself; it
does not by itself prove Bootstrap provisioning or new-repository writeback.
