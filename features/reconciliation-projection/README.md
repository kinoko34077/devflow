# Development Reconciliation and Repository Projection

This is an index-only route for the deterministic reconciliation and
repository-projection feature family. It connects the accepted specifications
to their existing implementation and tests; it does not create a second task
database, queue, or runtime.

## assessment

Use the Development Reconciliation contract and reconciler when live evidence
from an Issue, PR, review, execution session, or external dependency must be
validated before choosing a disposition. Missing, stale, contradictory, or
untrusted required evidence must fail closed.

## publication

Use the work-publication contract when a validated reconciliation result needs a
bounded demand projection. Publication is derived demand, not execution: the
owning Issue remains durable task truth and execution-coordinator remains the
runtime claim/lease authority.

## projection

Use the cross-repository Control and Repository Projection migration documents
when repository-local work visibility or projection state needs inspection. A
projection is an observed summary and never replaces the owning Issue, Control,
current HEAD, review, CI, or live runtime evidence.

All current state, acceptance, review, CI, and runtime decisions must be read
from live owners. This route does not grant claims, acknowledgements, releases,
permissions, credentials, deploys, or publication authority, and it does not
change the existing write paths.
