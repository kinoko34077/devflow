# Cross-Repository Core

This is an index-only route for the shared devflow control plane: managed
repository bootstrap, Issue/Goal context, durable handoff, and semantic Control
checks. It connects existing rules and implementations without creating a
second task ledger or authority surface.

## bootstrap-control

Start with the live AGENTS, Workflow, Control specification, and operating
manual when entering a managed repository. Then use the read CLI or MCP owner
for the required observation path. Static documents and filtered observations
do not replace live Control or owning Issue state.

## issue-goal

Use the Issue Manual and goal/plan helpers when preserving user-request
lineage, assessing declared effects, or comparing an outcome observation. These
helpers are advisory and source-linked; they do not turn metadata into a task
or execution decision.

## handoff

Use the Chat Rollover Archive procedure when a long-running conversation needs
durable minutes and a verified successor handoff. Handoff records preserve
history and resume context but do not replace the owning Issue, Cursor, Session,
PR, review, CI, or live Control.

## semantic-control

Use the semantic drift and post-merge owners when Control meaning or evidence
needs checking. Unknown, stale, incomplete, or contradictory source state must
fail closed.

Live AGENTS, Control, Issue, current HEAD, review, CI, and runtime state remain
authoritative. This route does not grant claims, permissions, credentials,
merges, deploys, publication, or task execution authority.
