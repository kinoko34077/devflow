# Generated Artifact Writeback

This is an index-only route for the verified generated-artifact contract, the
accepted single-repository Japanese Orthography pilot, and separately bounded
writer/admission code. It does not enable a general rollout or add a write path.

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
