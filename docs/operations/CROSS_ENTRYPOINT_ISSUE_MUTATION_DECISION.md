# R2 Decision — Cross-entrypoint GitHub Issue metadata concurrency

**Status:** NEGATIVE COUNTEREXAMPLE ACCEPTANCE PENDING PR/CI; global serializable Issue writes **NOT established**.  
Owner: [devflow #487](https://github.com/kinoko34077/devflow/issues/487) / [R2 Work Order #632](https://github.com/kinoko34077/devflow/issues/632).  
Scope: existing Public devflow GitHub Issue body writers, not a new permission, active dispatcher, credential or workflow.

## Exact source-level negative proof

- Existing `scripts/maintenance_audit.py::_SyncCheckGitHubTransport.update_control_body → update_issue_body` does a native authenticated GET, confirms canonical Control identity/open/trust and expected body SHA, then sends a **full-body GitHub Issue REST PATCH**. GitHub's API is not proven in this project to enforce an atomic `expected-old-body`/revision condition for that PATCH.
- `tests/test_operation_control_writeback_guard.py::test_external_direct_writer_after_final_get_is_overwritten` injects a real-shaped competing REST effect **between** the final GET and existing PATCH: writer A sees old content, writer B commits different valid content, A's later unconditional PATCH overwrites B. A's final content matches its plan, despite the lost B update. This is a **deterministic mock counterexample to the client algorithm's guarantee**, not a claim of a production race incident or an empirical attack frequency.
- In the opposite order, B updates **before** A's final GET, and the existing SHA guard refuses A. This establishes that A5's preflight reduces *some* races without guaranteeing serializability.

## Reachability and distinct guarantees

| Existing actor/path | What is actually protected | What is not protected |
| --- | --- | --- |
| `scripts/maintenance_audit.py` Control writer (#614) | Read-first identity/body SHA, no-op, caller readback; #624 queue for four participating Actions jobs | Other GitHub REST/CLI/MCP clients; final GET→PATCH gap |
| `scripts/repository_projection_cache.py` (#622) | Canonical provenance, pinned revision/body digest, independent final GET; same #624 Actions queue | Outside direct clients and atomic REST update |
| `scripts/project_sync.py` closed Health #41 (#629) | Native closed-Health identity/revision/fresh GET/no-op/postread; distinct `project-sync` Actions queue (#373) | An external Health writer not participating in its queue; Issue PATCH atomic compare |
| `tools/development_reconciler.execute_merge` | GitHub native PR expected-head merge and independent PR readback | It is not a general Issue body update primitive |
| #541 SQLite job ledger and F3C local WSL2 | Atomic SQLite job queue/nonce under its own owner and fixed Public read-only on-demand recipe | Does not acquire global GitHub Issue lock or authorize effectful writer cutover |
| ChatGPT native GitHub `update_issue` / owner CLI | Individual API permissions and normal current-state reads when explicitly performed | No automatic membership in the #624 Actions queue or repository-wide mandatory serialization |

## Admission decision for consequential concurrent Issue edits

For a resource where concurrent edits would cause unacceptable loss, **HOLD the effectful multi-actor body edit** until at least one of these independently verified safety mechanisms exists:

1. **One admissible serialized writer with no ungoverned competing principal:** all relevant callers route through a proven authenticated, target/actor/permission-fenced executor; enforce ordered one-resource writes and independent postread with durable operation IDs and unknown-result reconciliation. It is necessary to establish which external GitHub App/CLI/native agents **can bypass** the executor and remove/control that bypass through separately approved owner/permission changes, not by an unproved shared label or chat agreement. #541 owns any future effectful gateway/Claim integration and must meet its own Human/security gate.
2. **Verified server-side atomic conditional mutation:** an actual supported GitHub endpoint/protocol enforces the old body/revision compare *at commit time*, with a tested stale refusal and no lost updates. Do not infer this from `updated_at` GET comparisons, ETags for reads, HTTP PATCH conventions or Git refs; require endpoint-specific empirical proof before declaring CAS.
3. **Avoid conflicting mutable full-body effects:** keep independent data as append-only owner-validated records or split state into separately owned resources where the workflow contract allows this, with safe idempotency/receipt verification; such a redesign must not silently replace the existing canonical Control body.

**Not a solution:** repeated extra GET calls, a client-only lock, GitHub Project display fields, the Actions job queue alone, the SQLite job queue alone, or an unauthenticated Issue comment claimed as a writer grant.

## R2 acceptance and next execution

R2 accepts *the negative proof and the decision boundary* when hosted tests/Review/Readiness/postmain succeed. **R2 does not accept a global strong GitHub Issue CAS or production runner cutover.** Further user-approved roadmap work:

- [#474](https://github.com/kinoko34077/devflow/issues/474): recheck actual same-receipt dispatch transport, unique scratch HEAD and no overlapping runs before *exact one* authorized workflow start. Without supported authenticated dispatch, retain per-owner HOLD and do not invent an equivalent.
- [#541](https://github.com/kinoko34077/devflow/issues/541): prove real independently callable *effectful* owner-host approval/identity, all bypass principals and resource-level serialization before integrating write operations. Existing F3C fixed Public read-only proof is not this approval.
- Other Public repo routes only if an actual named owner/operation and repository-local admission are verified; no blanket rollout by quota.

This decision is a real safety boundary and roadmap checkpoint, not approval to modify GitHub authorizations, external deployments or credentials.
