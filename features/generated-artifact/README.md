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

## devflow#1050 bounded E2E fixture (currently Public)

The fixed recipe `bootstrap-writeback-e2e-v1` is limited to
`kinoko34077/devflow-writeback-bootstrap-e2e-20261118`. This fixture was
originally Private, then explicitly changed to Public for the accepted
protected-main E2E (#1058). The historical `private` label in the pinned
workflow/template is **not** a visibility requirement; the exact template
bytes are authenticated and must not be rewritten as documentation cleanup.
Only the separate, reviewed fixed-recipe writer job receives `contents:write`.
The default Bootstrap-installed Caller remains read-only. This fixture is not
an additional existing-repository rollout target.

The fixed-recipe E2E accepted real writing, same-receipt replay, stale-head
refusal and forward-only recovery (#1050). The resulting scratch PR #3 is
an unmerged evidence surface. Its generated HEAD's GitHub CI was
`action_required` with zero executed jobs, not a passing PR check. The
shared scoped writer intentionally reports `ci_verified=false`; it cannot
attest checks or reviews that run after the commit. Do not interpret writer
success as permission to merge or release the generated artifact.

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

## Source-neutral payload layer

\`tools/generated_artifact_contract.py:validate_payload_and_plan\` and
\`tools/generated_artifact_packager.py:package_generated_bytes\` share exact
output-set, bounded ZIP, content digest and byte-diff validation with the
existing Actions v1 path. They support a non-Actions producer's pure payload
without inventing a run ID or workflow reference. The caller independently
derives exact paths and limits from its reviewed recipe; an untrusted payload
cannot choose its own scope. These functions are read-only and are not a
writer admission or a new execution route. The existing Actions v1 policy,
producer authentication, branch fencing and writer activation stay mandatory.
A local/PC writer still needs its own authenticated producer evidence and
approved target/credential boundary before the shared writer may be invoked.
