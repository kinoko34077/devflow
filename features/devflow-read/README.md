# Devflow read/MCP feature route

This is a feature-first navigation index for the read-only Devflow MCP and
CLI. It does not duplicate the normative contract, move implementation files,
or change the live Repository Control. The manifest's `source_ref`,
`b18606558e5292b93f9efb115b3d776fce9b0a4a`, records the audited source
snapshot used for this route; it is dated provenance, not a pointer to the
current `main` head.

For current behavior or status, bootstrap the live Control, read the current
`main` head, and recheck the linked sources at that revision. The route does not grant
execution, write access, or permission.

Open only the route needed for the task. The linked documents, implementation,
tests, live Control, current HEAD, CI, and human gates remain authoritative at
their existing locations.

## bootstrap

For a managed-repository resume or current-state audit, call the live
`bootstrap_repository` path first, then follow the returned Control and
canonical entry points.

## work_view

For an all-status TASK observation, use the work-view route. Preserve source
status, coverage, unresolved counts, and the manual fallback; a partial or
filtered result is not an empty inventory.

## inbox

For a recipient-scoped Inbox observation, use the bounded Inbox route with an
explicit recipient and page. Preserve `next_offset`, coverage, and unknown
work indicators. Inbox visibility is not a task assignment.

## workspace

For the explicitly requested combined work/KAEP observation, use the workspace
route. Its TASK, message, and optional published-supply sections are distinct
read surfaces and do not replace the manual Control.

## portfolio

For explicitly authorized targetless managed-repository discovery, use the
existing read-only portfolio projection through MCP or
`python -m tools.devflow_read_cli portfolio` when MCP is not registered.
This is repository discovery, not candidate publication, work assignment,
full source completeness or Claim authority. After selecting a repository,
the existing read-only Human Portfolio is available through
`python -m tools.devflow_read_cli human-portfolio --repository <owner/repo>`
when its MCP tool is unavailable; this only observes Human gates.

## issue_goal_context

For one Issue's source-linked effective Goal Context, use the shared service
route. Incomplete ancestry, inaccessible sources, and missing citations remain
unknown rather than being promoted to current specification.

## assessment

For the advisory plan or outcome comparison, use the shared read-only
assessment path. Declared alignment is not execution, acceptance, authorship,
or evidence that the runtime result occurred.

## cloud_fallback

When an existing Cloud checkout has GitHub read access but no registered Devflow
MCP, use `python -m tools.devflow_read_cli`. It delegates to the same service,
is GET-only, and must not install a server, add credentials, schedule work, or
turn incomplete output into a conclusion that no work exists.

## Boundaries

- Read `docs/operations/DEVFLOW_MCP.md` before relying on an argument, value,
  error code, source-status field, or safety condition.
- Static route metadata never substitutes for live Control, Issue, PR, CI, or
  current-head reads.
- The route is valid only while each indexed source path exists. Physical code
  restructuring is a separate compatibility-gated change.
