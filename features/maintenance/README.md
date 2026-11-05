# Maintenance

This is an index-only route for standing maintenance selection, audit evidence,
Ledger handling, and explicitly gated workflow operations. It points to the
existing contracts and implementations without adding a scheduler, queue, or
credential path.

## catalog-selection

Use the maintenance audit and reconciliation contracts with the catalog,
selector, and triage modules when deciding whether a predefined slot is useful
and eligible. A repository-scoped request remains repository-scoped; an idle
result is not a reason to invent work.

## audit-ledger

Use the audit, supply, sync-check, Ledger, attestation, and completion owners
when producing or reading maintenance evidence. A selector result is not an
executed audit, and a Ledger record does not replace the owning Issue or
Control.

## manual-safety

Use the actor, writer-queue, shadow, and workflow tests when reviewing manual
effects, rollback, or concurrency boundaries. Effectful paths remain explicit,
owner-controlled, and fail closed when identity, freshness, or required gates
are not proven.

Live Control, catalog, Ledger, Issue, workflow, credential, and runtime state
remain authoritative. This route does not grant claims, permissions,
credentials, deploys, publication, or automatic execution authority.
