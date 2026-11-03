# KAEP feature route

This directory is a feature-first discovery entry, not a second KAEP contract.
The listed documents, code, tests, schemas, Issues, PRs, and live repository
state remain authoritative at their existing locations. `manifest.json` is an
index only; it grants no work, Claim, reply, permission, or runtime access.

## Choose the route

Read the smallest route that matches the task. Open the linked source document
before relying on a command, value, error code, actor rule, recipient rule, or
security condition.

## inbox

Use when an already-running agent needs a recipient-scoped Inbox read. Start at
`docs/spec/KAEP_AGENT_INBOX_V01.md`, then open the protocol and MCP operating
documents listed in the manifest. The result is read-only observation. An empty
or filtered result, `PARTIAL_UNKNOWN`, `INCOMPLETE`, or `BLOCKED` result is not
evidence that no work exists and is not execution authority.

## discovery

Use when an already-running agent needs bounded source-candidate discovery.
Start at the Agent-first API and read-path responsibility documents. Re-read
the original Issue, actor, recipient, nonce, reply chain, current head, and
owning Control before treating a candidate as relevant. A pointer or JSON
record is not a Claim.

## send

Use when reviewing or changing authorized send/reply code. Start at the KAEP
protocol, send responsibility document, and wire schema, then inspect the
listed implementation and tests. Do not infer permission or authorization
from this route; the live owner Issue and current repository policy decide it.

## audit

Use when auditing source-to-route preservation or the boundary between source
verification and discovery. The audit tool and its tests are read-only
evidence. They do not establish complete source coverage, current head
freshness, recipient pickup, Claim, or permission.

## history

Use when investigating prior incidents, acceptance, or migration evidence.
The live owner Issues (`devflow#503`, `#531`, and `#680`) and their linked
PR/CI/history records are the source of truth. Historical text is not copied
into this entry and is never silently promoted to current state.

## Safety and ownership

The feature route does not move existing source files and does not change a
CLI, schema, Action, or runtime behavior. `current head`, CI, review, Claim,
permission, and publication state must be checked live. The route remains
valid only while every indexed path exists; the route test fails if a source
is moved without updating the index. Keep incomplete information explicit and
preserve the existing fallback paths.

