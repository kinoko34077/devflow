# Security audit continuation implementation plan

## Scope

Close confirmed security findings before widening the fleet audit. The first
bounded implementation slice is devflow trusted-principal authorization from
#178/#801. `kinotch-api` #111 is already satisfied on live main by PR #112 and
requires readback, not a duplicate dependency change.

## Acceptance

- A single canonical machine-readable trusted-principal allowlist contains only
  GitHub user ID `79015263` with `kinoko34077` as secondary evidence.
- Issue-derived authority fails closed for missing, malformed, unlisted, or
  login-only identities; `author_association` alone never grants authority.
- Project Sync and its shared MCP/Projection trust consumers preserve valid
  owner operations and reject an untrusted Issue before Project/secret access.
- Existing workflow event gates remain numeric-ID based and have a regression
  contract test.
- Full devflow tests, exact-head CI/Verify, independent security review, and
  post-main readback are recorded before acceptance. No credential, permission,
  deployment, or paid-provider operation is performed.

## Work sequence

1. Add RED tests for the shared principal boundary and Project Sync rejection.
2. Implement the shared fail-closed helper and migrate direct consumers in the
   scoped trust path.
3. Audit remaining authority-bearing association-only consumers and either
   migrate them or record a separate owner finding with evidence.
4. Run targeted and full tests, static workflow checks, then open a bounded PR
   linked to #801/#178 for review.
5. Reconcile #801/#800 and the devflow Control only after accepted merge and
   exact-main verification.
