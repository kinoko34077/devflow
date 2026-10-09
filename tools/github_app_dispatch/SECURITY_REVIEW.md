# Security review checklist — devflow#395 / PR #396

**Status:** independent reviewer NOT YET RECEIVED; PRIVATE prototype only.
This document is an implementer-supplied review map, **not** an independent review or authorization to deploy.

## Assets / adversaries / trust boundaries

Assets: account-wide GitHub App private key, App ID / installation ID,
private ChatGPT-to-gateway client credential, the Project Sync workflow,
the canonical devflow Issue and Project state, durable nonce ledger.
Adversaries: unauthorized Internet client, compromised client token,
stolen App private key, unexpected/malicious workflow input, repeated
or reordered requests, compromised gateway or hosting account, confused-deputy
request across repositories, ambiguous GitHub HTTP response, transient outage.

Trust boundaries: ChatGPT client -> public HTTPS gateway authentication;
gateway -> Durable Object serialized storage; gateway -> GitHub App JWT/token
issuance; installation access token -> GitHub Actions dispatcher; dispatched
workflow -> GitHub's own privileged `PROJECTS_TOKEN` and Issue state.

## Implemented controls (verify by inspection)

1. Gateway accepts only POST /v1/dispatch, strict JSON field layout, at most
   2,048 bytes, and exact workflow repository/ref/mode/full-scope inputs.
2. Static high-entropy bearer token is checked before the nonce ledger and
   GitHub calls; no token/header/upstream HTML returned in error bodies.
3. Only owner/repository `kinoko34077/devflow`, workflow
   `project-sync.yml`, ref `main`, `mode=verify|reconcile`,
   `issue_number=""` are permitted in v1.
4. One App JWT is signed with RS256 (short exp). Installation token is
   requested with `repositories:["devflow"]` and
   `permissions:{"actions":"write"}`. The account-wide installation itself
   has broader intrinsic authority; request-time attenuation is not isolation
   against compromised App credentials.
5. SQLite-backed Durable Object `DispatchGate` reserves one UUID v4 before
   any GitHub API mutation. Replay of the same ID is rejected (409).
   Admission limits to 12/hour and at least 3 seconds apart across the
   fixed globally serialized gate. Audit records `{id, time, repo, workflow,
   mode, decision}` persist for up to seven days (best-effort cleanup).
6. Ambiguous GitHub API results do not cause automatic replay. Completion
   status `REQUESTED` only means HTTP dispatch was accepted. The requesting
   agent must independently read GitHub Actions run and Sync Health #41.
7. Worker `workers_dev: false`; neither route, App secrets, GitHub App, nor
   ChatGPT private plugin are configured or deployed.

## Open blocking review findings

- **HIGH / independent review not yet performed.** Implementer-authored
  tests and reviews cannot establish independent security acceptance.
- **HIGH / key scope.** App installed for All repositories with Actions write
  may dispatch workflows on all repos if private key is stolen or gateway
  compromised; normal endpoint allowlisting cannot revoke the underlying
  GitHub App scope. Human admin must accept this trade-off. Consider GitHub
  native protected workflow rules / process-level separation / App revocation.
- **HIGH / gateway client identity.** Static single bearer token gives no
  per-human/user identity, strong device binding, or human approval prompt
  per dispatch. Production should use private plugin auth and validate
  binding/caller provenance rather than exposing secret in code/client logs.
- **MEDIUM / Durable Object reality check.** Cloudflare runtime class binding,
  exports-based SQLite namespace and transaction isolation are unverified on a
  deployed environment. Node tests cover state-machine behavior but cannot
  substitute an isolated platform integration test.
- **MEDIUM / exactly-once limit.** This design provides at-most-one *attempt*
  for a given nonce, not at-most-one GitHub workflow run across different
  request IDs. A caller with a valid credential may deliberately send new IDs
  subject to rate limits. The caller must inspect GitHub evidence before
  reissuing a logically identical operation.
- **MEDIUM / sequencing.** Gateway admits `reconcile` and `verify`
  independently. It does not prove that the corresponding reconcile run
  passed before dispatching verify. This ordering must be enforced by the
  invoking agent or in a later orchestrator with real run evidence.
- **MEDIUM / operational protections.** Production ingress DDoS protection,
  log redaction, secret rotation, Cloudflare account access controls,
  alerting, repeat-request support, and ledger storage usage need a
  deployable operator runbook and proof in the actual target environment.
- **LOW / hostname.** Gateway's externally reachable HTTPS URL is not yet
  provisioned. The ChatGPT private integration must not be configured
  against a placeholder or expose the App key.

## Exit criteria / evidence to attach

- Independent, identifiable reviewer reads **entire exact PR head**, provides
  Formal Review with blocking findings none and required review provenance.
- Required CI verifies the exact reviewed head; no changes thereafter without
  new review.
- User/admin explicitly authorizes selected App installation owner,
  `All repositories` and Actions write, plus private backend credential
  registration and external deployment as separate security/publication gates.
- In a controlled private endpoint environment, validate authentication,
  request IDs, nonce replay/rate-limit, App JWT, limited installation token and
  exact workflow request. No arbitrary workflows or implicit extra repo access.
- Call `reconcile`, verify its **actual GitHub run outcome**, then call
  `verify`, require machine #41 PASS with zero drift/errors/unresolved;
  if not, continue the #381 recovery without declaring success.
- Reconcile #395/#381/#382 and Base #380/#49 only after real evidence.

References:
- https://docs.github.com/en/rest/apps/apps?apiVersion=2022-11-28
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
- https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/
- https://developers.cloudflare.com/durable-objects/reference/durable-objects-migrations/
