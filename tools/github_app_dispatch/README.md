# Account-wide GitHub App guarded Actions dispatch bridge (devflow#395)

**Status: OFFLINE IMPLEMENTATION ONLY.** This folder is not deployed, connected, or authorized.
Nothing here registers/installs a GitHub App, changes repository settings, grants
`Actions: write`, or launches a real workflow.

## Purpose

One GitHub App can be installed by the owner for **All repositories**. This avoids
per-repository installations as new repositories are added. It does **not**
automatically authorize a chat client to launch any workflow. The gateway is
a separate, narrow access boundary. It mints a short-lived installation
token restricted to **one repository** and **Actions: write** for each request.

V1 authorizes only:
- `kinoko34077/devflow` / `project-sync.yml` / `main`
- `mode=verify` or `mode=reconcile`
- `issue_number=""` (entire synchronization scope)

Every other repository, workflow, ref, input field or nonempty Issue selection is
rejected. Permission to add other entries is **not** implicit in installing an
account-wide GitHub App.

## Service design

This proof-of-implementation is a Cloudflare Worker ES module
(`index.mjs` imports `worker.mjs` and a SQLite-backed Durable Object gate). It can be adapted to a different
trusted runtime without changing the accepted admission contract.

POST `/v1/dispatch` with
`Authorization: Bearer <client-specific secret>`, `x-request-id: <fresh UUID v4>` and `Content-Type: application/json`:

```json
{"repository":"kinoko34077/devflow","workflow":"project-sync.yml","ref":"main","inputs":{"mode":"verify","issue_number":""}}
```

The API replies HTTP 202 `DISPATCH_REQUESTED` after the GitHub dispatch
API accepts the request. It **never** claims the Actions run succeeded;
read back the exact run and Sync Health Issue #41 after execution.
The bridge must not be asked to sequence `reconcile` and `verify` without
checking the previous step's actual outcome.

### Environment (Cloudflare secret settings; NOT source or chat)

- `GITHUB_APP_ID`: numeric GitHub App ID
- `GITHUB_INSTALLATION_ID`: installation on authorized account
- `GITHUB_APP_PRIVATE_KEY`: PEM PKCS#8 private key, secret only
- `CLIENT_API_TOKEN`: independently generated strong client credential, secret only

PKCS#1 (`BEGIN RSA PRIVATE KEY`) must be converted into PKCS#8
(`BEGIN PRIVATE KEY`) **outside** the chat and never committed.
Use a secrets manager with key rotation and restricted deployment access.
Private key compromise may affect **all installed repositories**, even though
the gateway itself narrows access for normal requests.

Authentication between ChatGPT's private plugin and the gateway must be
reviewed for safe credential storage, request authorization, replay and rate limits,
before production. No plugin has been registered or connected at this stage.
No shared key is to be pasted into an Issue, PR, source file or conversation.

## Offline verification

On Node.js with built-in `node:test` (no packages/network):

```sh
node --test tools/github_app_dispatch/dispatch.test.mjs
```

This tests the closed allowlist, auth before upstream, repository-restricted
installation token request, exact dispatch body, sanitized failures and
real RSA JWT signing. It does NOT constitute a live GitHub integration test.

## Production gates — separate Human approval required

1. Formal independent security review of the entire App/gateway/client trust boundary,
   including abuse/replay protection; code readiness alone is insufficient.
2. User/admin creates their own private GitHub App; chooses **All repositories**
   for the intended owning account; grants only repository `Actions: write`
   plus minimum GitHub-required metadata access. Do not silently reuse existing App credentials.
3. User/admin provisions key + installation ID and client authentication to a trusted
   secret store; secure deployment and ChatGPT private plugin connection are
   separately gated publication/credential/permission changes.
4. Read-only integration validation, then one authorized full `reconcile`,
   verify the resulting Actions job and Health #41; only on success run full
   `verify` and require Health PASS/zero errors/drift/unresolved.
5. Expand allowlist by independent reviewed policy update **per workflow**, not by
   making the App installation globally executable.

GitHub documentation:
- https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app
- https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event

## Persistent request admission (not deployed)

The Worker requires the Cloudflare `DISPATCH_GATE` Durable Object binding. The
SQL-backed persistent ledger reserves a one-use UUID before any GitHub API call,
rejects a duplicate ID (HTTP 409), limits rapid requests (HTTP 429; at most 12
reservations per hour, 3 seconds minimum spacing) and records a bounded audit
of requested/rejected/ambiguous outcomes for seven days. On ambiguous GitHub
response or ledger failure it **never automatically dispatches again**; an
operator must use the GitHub run/Health readback. The request ID must be
carried unchanged on transport retries, including from the ChatGPT plugin.

Durable Object source: `gate-object.mjs`, storage contract: `gate-state.mjs`.
Wrangler `wrangler.jsonc` declares the SQLite-backed namespace using Cloudflare's
2026 declarative `exports` syntax. This file is NOT deployed by GitHub PR/CI.

Production still requires independent review of the privileged App key trust
boundary, private-client authentication, DO replay guarantees and deployment.
- https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/
- https://developers.cloudflare.com/durable-objects/reference/durable-objects-migrations/
