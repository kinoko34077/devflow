# G2B fixture-only adapter seam — design/security proof

Status: DRAFT / offline proof only. Work Order: devflow #413. Source user continuation: 2026-10-10. This file does NOT authorize a new authenticated runtime.

## Purpose

Exercise accepted G1 `admit_dispatch` and G2A `inspect_read_request` in one Python code path using static, injection-provided test fixtures. Demonstrate possible ordering and fail-closed checks without treating separately sequenced ChatGPT tool calls as an atomic service.

```text
synthetic trusted-startup pins (fixed actor ID/login, repo ID/name/ref,
                              reviewed catalog commit syntax and raw SHA-256)
  + bounded strict raw JSON request, raw catalog from synthetic trusted source
  + fake provider's current_actor() SINGLE response
  + fake provider's repo metadata + branch HEAD
  -> G1 + G2A actual Python policy in one process
  -> repeat fake metadata + branch HEAD
  -> SIMULATION_ONLY / BLOCKED, never EXECUTED
```

## What these tests actually prove

- Exact candidate source bytes must match a trusted-startup SHA-256 digest before JSON parsing; parsing refuses duplicate keys, arbitrary backend and write operations.
- The one fake actor object contains both ID/login, compared against independently supplied fixed pins. The stable repo ID, canonical name, visibility, default ref, read permission and exact request HEAD are cross-checked. Before/after evidence catches head/ref/permission movement.
- The metadata provider is a Python Protocol and all test instances are fake. No GitHub connection is created, OAuth identity established, network request sent, secret configured or runtime tool delegated. No production catalog registry created.
- All synthetic outcomes are `SIMULATION_ONLY` or `BLOCKED`; no execution/authorization status. There is no live GitHub handler, no cached credential and no durable success receipt.

## Security limits and next gates

- Pin SHA-256 to catalog *bytes* does not prove those bytes were obtained from the reviewed GitHub commit or blob: the **future trusted adapter** must fetch the immutable reviewed source and verify commit-tree-blob content provenance from the connector/REST result. Fixed pins must be injected solely by a reviewed trusted deployment, not user input.
- An attacker can freely construct `StartupPins` and `MetadataFixture` in standalone Python. They are not identity authority. Future plugin/connector binding must obtain numeric user ID and login in the same authenticated connection and bind target metadata to the same permission context.
- This is not a production idempotency solution. The local SQLite demo from G2A is not shared distributed fencing or agent claim. Before effects, choose a separate reviewed transactional shared store and audit trail. Read-only metadata simulation does not need an at-most-once guarantee to be a valid offline check, but MUST NOT be labeled live dispatch.
- Any real authenticated GitHub API read, private repo processing, generic workflow_dispatch, new App/Plugin/Gateway, permission/credential change, deploy, release, or write effect requires separately admitted G2B/G3 security/Human gates and an independent different-model exact-head security review.
- Reviewer carryforwards: G2A N1 SQLite closing, N2 immutable reviewed catalog source binding (only partial byte digest modeled here), N3 same-response actor identity under actual OAuth, N4 canonical stable repo ID/name and branch handling.

## Verify

`python -m unittest tests.test_safe_dispatch_g2b_fixture -v`

`python -m compileall -q tools/safe_dispatch_g2b_fixture.py tests/test_safe_dispatch_g2b_fixture.py`

Risk: mock policy integration can pass while an actual connector/provider is impossible. A successful fixture test is **never** evidence of ChatGPT's production OAuth or cross-run idempotency, Private code execution, Runner availability, or GitHub Actions dispatch.
