# Chat Worker

This is an index-only, provider-neutral route for working with an already-open
chat worker. It points to the existing bootstrap, profile, schema, and fixture
artifacts; it does not define a new runtime or replace their owning contracts.

## bootstrap

Use the bootstrap specification and integration guide when a worker receives a
broad or scoped instruction. The route covers the existing disposition flow for
one candidate and does not create a queue, scheduler, provider launch, or
runtime authorization.

## profile

Use the profile specification and profile tool when a session needs reproducible
identity, capability, environment, and tool-surface evidence. A profile is
observed evidence, not a provider reputation or capability guarantee.

## schemas

Use the existing request, evidence, and result schemas when an envelope or its
fixture contract changes. The schema files remain the contract owners.

## fixtures

Use the fixture directory when disposition selection or a fail-closed boundary
is regressed. Unknown, stale, or secret-shaped evidence must fail closed.

Live AGENTS, Control, Issue, frontier, and execution-coordinator state remain
the authority for current work. This navigation route does not issue a claim,
acknowledgement, release, or permission; it also does not change credentials,
permissions, releases, deploys, or publication.
