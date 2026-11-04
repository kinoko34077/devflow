# Project Sync

This is an index-only route for the one-way projection from canonical devflow
Issues and Repository Controls to the display-only GitHub Project. It points to
the existing contract, workflow admission, sync implementation, and tests.

## contract

Use the Project Sync specification and cross-repository Control specification
when field mappings, audit freshness, or the canonical-to-display direction
need review. Project values are observations for display and are not inputs
that rewrite canonical Issues.

## admission

Use the workflow and admission implementation when serialization, target
selection, or failure fencing changes. The workflow's existing boundaries and
owner-controlled write path remain authoritative.

## verification

Use the health, native-command, resilience, and workflow tests when validating
the synchronization path. Incomplete, ambiguous, stale, or contradictory
evidence must fail closed rather than being treated as a successful sync.

Live Issues, Repository Controls, workflow runs, current HEAD, and Project Sync
Health remain the sources for current state. This route does not grant claims,
permissions, credentials, deploys, or publication authority, and it does not
reverse-sync Project display values into canonical state.
