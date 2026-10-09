# GitHub App single-install administrative setup — NOT EXECUTED

Work Order: devflow#395. **No app, permissions, secrets, deployment or ChatGPT plugin connection have been created as part of this PR.**

## Human security gate / account setting

The following is an operator checklist only, **not** permission to carry it out automatically.

1. Review the exact admission policy, gateway code, threat model, and independent security review. Keep the GitHub App private and limited to **Only on this account** (GitHub App visibility), not public marketplace publication.
2. In the intended GitHub owner's Settings → Developer settings → GitHub Apps, register a new GitHub App for the Actions dispatch bridge. Disable webhooks if unused. Configure repository **Actions: Read and write**; `Metadata: Read-only` is mandatory by GitHub. Do not request Contents write, Secrets, Administration, Deployments, Pull requests, Issues write, Organization privileges or unrelated permissions.
3. Through the App's `Install App` page select the intended GitHub account and **All repositories**. This is one account-wide installation, including newly added repositories; a different owning account/organization needs a distinct installation.
4. Generate a GitHub App private key only through GitHub's admin UI; keep it in a trusted secret store, never in chat, GitHub Issues, code, or logs. The gateway expects a PKCS#8 PEM key. Convert as needed in a trusted local environment; destroy temporary copies. Do not upload the private key into ChatGPT files.
5. Configure worker secrets (`GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY`, `CLIENT_API_TOKEN`) using the hosting platform's secure admin/deploy workflow. CLIENT_API_TOKEN is a **different**, high-entropy gateway caller secret; minimum 32 characters. Nothing is committed or printed.
6. Deploy privately to a trusted HTTPS endpoint, after security approval. The ChatGPT private integration must use an authenticated connection to this endpoint; it must not own or see the GitHub App private key. Do not enable wildcard methods, anonymous API access, arbitrary repository/workflow dispatch, or generic GitHub proxying.
7. Review monitoring, abuse/rate limiting, replay/retry handling, runtime access logs, key rotation and revoke/rollback before accepting the production gate. If a dispatch API call times out ambiguously, inspect GitHub Actions before trying again.
8. Start only `devflow/project-sync.yml` on `main` with `mode=reconcile`, `issue_number=""`; inspect actual Actions run and Health #41. Only upon confirmed successful reconcile, issue `verify` and confirm Health PASS, zero drift/errors/retained failures.

## Integration contract

`POST /v1/dispatch`

Headers:
- `Authorization: Bearer <gateway-client-secret>`
- `Content-Type: application/json`
- `x-request-id: <fresh UUID v4>; reuse same ID on transport retry`

Request:
```json
{"repository":"kinoko34077/devflow","workflow":"project-sync.yml","ref":"main","inputs":{"mode":"reconcile","issue_number":""}}
```

Successful response:
```json
{"state":"DISPATCH_REQUESTED","repository":"kinoko34077/devflow","workflow":"project-sync.yml","ref":"main","mode":"reconcile","verification":"REQUIRED"}
```

A 202 indicates acceptance by the GitHub dispatch API, **not** success of the workflow itself. The existing GitHub connector can read subsequent run details and Sync Health without new permissions.

## Security constraints

- `All repositories` extends **GitHub-side permission** to the whole installation. Gateway allowlist only limits normal app calls; a compromised App private key could obtain wider tokens. This risk must be consciously accepted before installation.
- The app key remains exclusively in the trusted gateway. Per-request installation tokens request only one repo and `actions:write`, and expire in about one hour.
- Current prototype authenticates a single static gateway client secret. The Durable Object already implements persistent request-ID replay rejection, a basic 12/hour and 3-second global rate limit, and a bounded audit trail. Per-caller audit identity, production abuse monitoring and live-runtime replay verification remain unverified. The scoped installation token is revoked after dispatch when GitHub confirms revocation, with uncertainty explicitly reported otherwise.
- Do not expose administrative "install", "rotate", "change allowlist" or arbitrary GitHub API tools via the ChatGPT integration.
- GitHub App installation is not a license to execute third-party/untrusted Actions. Adding a new workflow requires another reviewed exact-policy update.
- Emergency rollback: revoke client secret, disable gateway endpoint, revoke App private key and/or uninstall the GitHub App. Uninstalling/credential revocation is a security-sensitive user/admin action.

Official references:
- https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app
- https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
