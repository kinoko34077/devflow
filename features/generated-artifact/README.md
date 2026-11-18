# Generated Artifact Writeback

This is an index-only route for the verified generated-artifact contract, the
accepted single-repository Japanese Orthography pilot, and separately bounded
writer/admission code. It does not enable a general rollout or add a write path.

New managed repositories can receive the standard capability record through
Repository Bootstrap (#1050). That record points to the existing fixed-recipe
admission and shared writer. It does not grant `contents:write`, admit a new
repository/recipe, or activate the dormant rollout writer. The native
read-only receiver displays the capability record, and a pinned dry-run-only
Caller routes eligible registered recipes through the existing shared
producer and read-only verifier. It grants no `contents:write`. No generated
output is `NOT_APPLICABLE/NO_GENERATED_OUTPUT`; effectful writes still require
the reviewed, exact-recipe caller and per-repository Human/security gates.
Existing repository adoption remains the separate finite rollout in #386.

## devflow#1050 private E2E fixture

The fixed recipe `bootstrap-writeback-e2e-v1` is limited to the private
`kinoko34077/devflow-writeback-bootstrap-e2e-20261118` repository. Its dedicated
caller path and exact template are source-controlled; only the shared writer
job for that repository/recipe pair receives `contents:write`. This is an
acceptance fixture, not a default permission or an additional rollout target.

## contract

Use the contract and packager owners when artifact identity, recipe, digest,
path, receipt, or replay semantics change. Treat generated data as untrusted
until the existing contract checks pass.

## pilot

Use the runbook and pilot owners when reviewing the accepted JO pilot, exact
receipt replay behavior, rollback, or cleanup evidence. The pilot's acceptance
does not authorize other repositories, recipes, branches, deploys, or Pages.

## admission

Use the admission, dry-run, rollout, testapp, and writer owners when reviewing
stale-head, actor, workflow, or bounded write behavior. Unknown identity,
receipt, or post-write evidence must fail closed; a dry-run or skipped job is
not a completed write.

Live owning Issues, PRs, exact workflow runs, current pinned SHAs, review, and
post-main evidence remain authoritative. This route does not grant claims,
permissions, credentials, deploys, publication, or general rollout authority.
