# GPT Liveness

This is an index-only route for the opt-in GPT liveness pilot and its identity,
routing, evidence, and dispatch-preview artifacts. It does not add a transport,
automatic model wake, or runtime authority.

## pilot

Use the pilot and rollout documents when reviewing enrollment scope, scheduling,
or observation semantics. The pilot is opt-in and bounded to its owning Issue;
scheduled Actions are not a precise timer or proof that a model turn survived.

## identity-routing

Use the identity, routing, and two-turn documents with the shared ID and registry
owners when a chat/session/turn contract changes. Compatibility-preserving ID
reuse must not be confused with model identity attestation.

## evidence-dispatch

Use the evidence producer, mailbox, manual-action, and dispatch-preview owners
when validating correlation or downstream projections. Transport actor and
comment evidence do not prove which model authored text; invalid or incomplete
evidence must fail closed.

Live owning Issues, mailbox contents, enrollment, current HEAD, workflow runs,
and downstream coordinator state remain authoritative. This route does not grant
claims, permissions, credentials, wake, deploy, or publication authority.
