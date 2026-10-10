# ChatGPT safe generic dispatch G2A — offline read-only preflight

Status: DRAFT / G2A only. Owner: devflow #413. Neither deployed nor a real generic dispatch implementation.

## Authority and non-goals

G1 is accepted on main. This G2A proposal composes the real G1 `admit_dispatch` classifier internally with additional pure checks and a single-file SQLite reservation proof. It does not authenticate anything itself, use network, invoke Actions, call GitHub or have power to perform an effect.

## Intended trust boundary

1. Future authenticated connector supplies trusted identity (`principal_id`, `actor_login`) from the actual GitHub account response, not from chat/Issue text.
2. Trusted adapter reads an exact reviewed catalog commit, compares actual returned source bytes/commit to the pin, and passes the catalog to G2A. `catalog_commit_sha` syntax here is NOT cryptographic attestation by itself.
3. Adapter observes target `repository`, `default_branch`, fresh head and `can_read` from the same authenticated connection and proves the fixed handler is actually available. `ObservedReadContext` is **inert data**, NOT an identity credential or trustworthy proof.
4. `inspect_read_request` runs G1 itself, requires G1 ADMITTED, and restricts to exactly `repo.status` / `github.repository_metadata` / `github_api`, checks actor, repo, exact default ref/head and read permission. It returns `PREFLIGHT_ONLY`, never EXECUTED.
5. If a later actual connector read is introduced, it requires a separately reviewed G2B runtime adapter, must re-observe current head immediately before and after the read, bind output to exact source and record failure/ambiguous completion. A mere `PREFLIGHT_ONLY` result is never execution permission.

## SQLite reservation proof

Single shared DB-file only: `BEGIN IMMEDIATE` serializes contenders and the composite `(principal_id, request_id)` primary key rejects both replays and payload/catalog changes. Request digest uses canonical bounded JSON with domain separation. Reservations never expire or release automatically. This models fail-closed crash state, not a distributed lock or execution-coordinator claim; a forged Python `ReadPreflight` can also be constructed, so it is not an authorization boundary.

## Security exclusions

- No production trusted operation catalog or real authenticated adapter constructed here.
- No credential, token, permission change, runner use, workflow_dispatch, private processing, Gateway, deployment, release, or arbitrary read/write executor.
- No GitHub Actions backend; reviewed_workflow_sha does not authorize dispatch.
- No runtime distributed fencing, E2E receipt, retry decision or real effect/terminal status.
- `private` in synthetic observations never proves a real Private repository has connector access.

## Verification and exit

`python -m unittest tests.test_safe_dispatch_g2a -v`

`python -m compileall -q tools/safe_dispatch_g2a.py tests/test_safe_dispatch_g2a.py`

Before merge: exact-head Required CI, different-model/system formal security Review Provenance v2, review-readiness pass, and post-main Required. G2B and G3 remain separate security/Human gates under #413.