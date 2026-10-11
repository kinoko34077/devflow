# G2B0 C2 — immutable catalog provenance (offline Git object verifier)

Status: **PURE OFFLINE CODE / NOT AN AUTHENTICATED CATALOG ROOT**. Owner: devflow #432, parent #413 and C1–C6 spec #420.

The verifier accepts a human-reviewed **build-time pinned** source repository numeric ID, commit Git SHA-1 object ID, relative catalog path, blob SHA-1 ID and SHA-256 content hash. Given externally fetched raw commit/tree/blob bytes, it recomputes Git object OIDs, traces the exact commit-root tree and nested path, enforces regular file mode 100644, verifies expected blob SHA/length and SHA-256, then invokes the current G1 catalog validator. Unknown inputs, duplicate or ambiguous tree names, symbolic links, submodules, executable and noncanonical content all fail closed. It does **not** fetch, authenticate, or execute anything.

This implementation is an **integrity check on already-supplied raw bytes**, not proof that a GitHub API returned them, that the source repository ID matches, that the commit is protected/reviewed, or that build-time pins are trustworthy. SHA-1 Git object hashes are Git's existing object-address format, **not a modern collision-resistant signing scheme**: the reviewed SHA-256 catalog hash additionally pins bytes, but the runtime still needs a trusted immutable source and protected deploy configuration. A caller-supplied `CatalogSourcePin` remains forgeable. Future authenticated adapter MUST validate connection/principal, source repo stable ID, protected-review provenance, runtime pin authority, complete GET transport, and durable receipt separately. `OFFLINE_SOURCE_MATCHED` is **never** `ADMITTED`, `READ_VERIFIED`, `EXECUTED`, or permission to dispatch.

The verifier deliberately does not modify G1, G2A or the existing G2B fixture. No OAuth, token, Private GitHub operation, new external service, Action, writing, shared journal or deployment is added. Human C3-B/C6 gates and #424 HOLD_B are unchanged.

Verify with `python -m unittest tests.test_safe_dispatch_catalog_source -v` and `python -m compileall -q tools/safe_dispatch_catalog_source.py tests/test_safe_dispatch_catalog_source.py` in the devflow repository. Merge only after exact-head Required CI, **genuinely independent** different-system Formal Security Review, readiness and post-main Required. Synthetic fixtures do not contain private repository bytes.

## Explicit follow-on integration gate

The source repository ID and build-time pin configuration in this module are inert data. The eventual G2B0 runtime needs a separately reviewed authenticated client which fetches the exact immutable GitHub commit/tree/blob source, validates source repository identity, binds each API request to the approved App token, and invokes G1/G2A and durable receipt handling in the *same trusted backend*. This component does not turn the ChatGPT GitHub connector into a deployable runtime, or prove Metadata-only Private HEAD feasibility.
