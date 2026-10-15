# F3C GitHub Issue → Existing Windows PC → WSL2 (manual one-shot)

Owner: [devflow #610](https://github.com/kinoko34077/devflow/issues/610); parent #541. User previously approved **existing** WSL2 for bounded Public READ_ONLY tests. No paid service or permissions added.

## Purpose

This is a real, no-GitHub-Actions data path, **not** unattended service: the connected GitHub actor records a narrowly formatted *Public-only* request comment on owner Issue #610; the existing Windows `gh` CLI fetches exactly one selected comment via authenticated GitHub REST GET; the program checks GitHub-supplied author/issue ID and exact fixed schema, reserves comment ID+nonce in a local durable SQLite ledger before invoking the existing `wsl_fixed_public_bridge.run_once` fixed public SHA256 recipe. The WSL2 code never receives GitHub tokens, arbitrary command text or Private source; the result contains no source, comment text, stderr or secrets.

**No new PAT/App, per-repo secret, local listener/port, service registration, polling loop, startup task, Docker daemon or public endpoint.**

## One-shot request format

Issue #610, a top-level GitHub **issue comment** with exactly:

```text
F3C-WSL-PUBLIC-ONCE-V1
{"schema_version":"devflow.f3c.wsl-public-request.v1","repository":"kinoko34077/devflow","task_ref":"kinoko34077/devflow#610","recipe_id":"wsl-fixed-public-v1","effect":"READ_ONLY","nonce":"f3c-0123456789abcdefghij"}
```

The nonce must match `f3c-` plus 20 lowercase alphanumeric characters. A new comment/nonce is needed per trial; already reserved comments cannot be replayed. Author must be `kinoko34077` (GitHub REST user type User), attached to the exact owner Issue and unedited. This is **GitHub-reported author attribution, not proof of the physical human or cryptographic origin of a GitHub App actor**.

## Run from an already trusted Windows devflow checkout

```powershell
python -m tools.wsl_github_fixed_pull --comment-id 6199999911
# On a specifically approved PUBLIC-only trial, one-shot:
python -m tools.wsl_github_fixed_pull --comment-id 6199999911 --execute
```

Default is admission-only `CANDIDATE_ONLY`. The `--execute` flag uses installed `gh api` and the previous approved WSL2 bridge. SQLite at `%LOCALAPPDATA%/KiNoTch/devflow/f3c_wsl_public_attempts.sqlite3` stores only comment ID, nonce SHA256 and terminal state. It is local user state, not a GitHub Claim ledger. Reserving before execution makes post-crash retry HOLD/UNKNOWN; no automatic replay. The local database file is deliberately retained for idempotence (do not erase casually).

Tests: `python -m unittest tests.test_wsl_github_fixed_pull -v`. A real on-PC authenticated GET proof and real WSL execution, if actually verified, must be separately recorded in #610; mocked tests alone do not establish them.

## Security and acceptance boundaries

- GitHub `gh api` GET reads only the exact comment and reuses **existing Windows authentication**. It does not enable a new token or a GitHub Issue writer; the comment can be created with the already connected ChatGPT GitHub tool.
- GitHub API actor identity plus a nonce and local replay ledger are **not** a trusted production issuer, claim authority or cryptographically signed remote job; the same account can have multiple agents. No arbitrary PR source, command or repository workflow is eligible.
- WSL2 inherits the Windows user's trust boundary and can access Windows-mounted paths; **not an untrusted code sandbox**. Fixed immutable public job only.
- No unattended wake, remote daemon/service, guaranteed PC uptime, Private code, authenticated GitHub Checks or Claim cutover. Those remain distinct F3C/F4/F5 acceptance gates and security approvals.
- Human money decision is frozen; no unrelated 2,000 JPY budget.

If the local GitHub credential is missing, API is unavailable, stored ledger cannot be opened, or any receipt flag indicates privileges, exit HOLD with a fixed reason. Never echo secrets, trust an Issue body as shell, or auto-retry an uncertain result.
