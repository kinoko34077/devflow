# Codex Cloud — reusable GitHub access and Issue-first reporting

Status: bounded operational runbook / no new credential, permission or writer enabled.
Owner: [devflow #570](https://github.com/kinoko34077/devflow/issues/570). Source of truth for development authority remains [devflow AGENTS](../../AGENTS.md) and the owning repository's Control/Issue.

## Purpose and current evidence

Codex Cloud task isolation does **not** imply that a GitHub CLI token is automatically valid for Issue comments, even when the task can fetch code, open a PR or run read-only Devflow tools. Avoid repeated per-task token setup; use the account's documented **reusable environment and personal credential management**, with the smallest explicitly approved repository/write scope.

- **Accepted read**: [#531 normal task sandbox](https://github.com/kinoko34077/devflow/issues/531#issuecomment-6190065102) confirms existing GET-only `tools.devflow_read_cli` `bootstrap`, `work-view`, and `inbox` against live GitHub data. MCP tool registration is not required for that route. A filtered empty Inbox with INCOMPLETE coverage does not imply zero work; keep manual Control and #503.
- **Observed write gap**: a particular UniverseGenome Codex Cloud task reported `GH_TOKEN` invalid and inability to append a result on [UniverseGenome #363](https://github.com/kinoko34077/UniverseGenome/issues/363). That is an *individual task's reported access condition*, not proof that Codex Cloud cannot write Issues at all.
- **Existing write/dispatch is narrower than requested**: [#413](https://github.com/kinoko34077/devflow/issues/413) fixed comment → read-only workflow commands; [#465](https://github.com/kinoko34077/devflow/issues/465)/[#386](https://github.com/kinoko34077/devflow/issues/386) selected generated-artifact writeback/testapp scratch. Do not repurpose these as unrestricted Issue-comment endpoints.
- **Separate safety gate**: [UniverseGenome #363](https://github.com/kinoko34077/UniverseGenome/issues/363) genuine E0 physical experiment remains platform-blocked. Fixing GitHub Issue permissions does not grant authorization to run that experiment.

## M1: access capability matrix — verify each action separately

| Capability | Native evidence / safe probe | Meaning of success | Not evidence of |
| --- | --- | --- | --- |
| Checkout/source refresh | `git status --short`; `git fetch origin main` only on permitted network; fast-forward **only if clean and ancestor** | Source transport and selected branch can be refreshed | API identity / Issue POST scope |
| Public repository and Issue GET | `gh api repos/OWNER/REPO/issues/NUMBER` or accepted `tools.devflow_read_cli` | Live source can be read | An authenticated actor or write ability |
| Identity | `gh api user --jq .login` with existing authorized connection; capture **login/status only** | Request identity for *that same credential path* | Permission on any other repo or request path |
| Native PR publish | Actual PR URL/readback from Codex/GitHub, if supported | That PR operation succeeded | Issue comments on arbitrary repositories |
| Issue comment POST | One **already authorized** harmless comment on one explicitly selected test Issue, followed by GET readback | Proven only for that repo, actor, endpoint and execution surface | Fleet-wide write; later tasks; security policy bypass |
| Devflow work discovery | Existing GET-only bootstrap/work-view/inbox | Live observed task records with exact completeness fields | Claim/lease or Issue POST |
| Cloud-native MCP tool discovery | Actual client tool list + invocation | Native registration/use in that task | A required prerequisite for the accepted CLI route |

Do not label failures `401`/`403` without a real HTTP status. A proxy/socket exception before HTTP is transport/policy failure; `404` can mask absent access, wrong identity or a moved resource. A `GH_TOKEN` environment variable's presence is not an authentication test. A GitHub Connector in **this ChatGPT session** does not automatically authenticate a **Codex Cloud** sandbox, nor vice versa.

## M2: one-time setup, **only if an authorized Issue write is actually necessary**

**Step A: native route first (no new secrets).** Check that the user-connected GitHub integration and the current Codex Cloud task expose a supported Issue comment action. If they do and a real test POST/readback succeeds, use that route. Do not create an extra token simply because `gh auth status` prints an unrelated invalid credential.

**Step B: exact requested scope.** When the Cloud task itself must append Issue-first evidence and has no authorized Issue writer, specify:
1. **Allowed repositories** — start with *one named target repository and one designated test Issue*, not all private/public repositories.
2. **Allowed operation** — only `POST /repos/{owner}/{repo}/issues/{issue_number}/comments` for bounded progress notes; no Issues PATCH/close, contents write, Actions dispatch, secret or deployment permissions by implication.
3. **Credential origin** — a reviewed fine-grained GitHub App installation or PAT for selected repositories with `Issues: write` (GitHub REST supports `Pull requests:write` as an alternative for the comment endpoint). Any selection, addition or change of credentials/permissions is **security-sensitive and requires explicit user authorization**.
4. **Delivery mode** — prefer controlled environment-specific **Network secret** to `api.github.com` if the actual GitHub client/proxy transport is proven compatible, otherwise explicitly evaluate the risk of a direct Environment variable exposed to generated scripts. Never paste the token into chats, issue comments, source, shell commands, `AGENTS.md` or test logs. Host allowlisting is not per-Issue or per-repo authorization.
5. **Environment assignment** — prefer `Settings → Codex Cloud → Personal vault` scoped to **Selected environments** and require only that environment to request the credential key. `All environments` is **not the default for a write-capable token**; avoid enabling all-repo privileges to reduce setup clicks.
6. **Activation** — save/republish existing environment if its credential requirements change, then verify in a *new independent task*. Do not alter existing task credentials or force-reset active worktrees.

Official Codex Cloud documentation:
- [Reusable cloud environments, update, and Personal vault](https://learn.chatgpt.com/docs/environments/cloud-environments) — environment variables are passed into the task and can be seen by its processes; network secrets use HTTPS proxy placeholder substitution; credentials are only supplied to environments that request them; new tasks use published state, existing tasks keep theirs.
- [Using Codex Cloud](https://help.openai.com/en/articles/20001545-using-codex-cloud) — each user/repo GitHub connection, branch/code access, Git config and push behavior require distinct checks.
- [GitHub REST: create issue comment](https://docs.github.com/en/rest/issues/comments) — validate `Issues:write` or supported `Pull requests:write` on exact repository.

**No user token action is necessary until a real Cloud Issue POST is selected and the standard/native route has been checked.** The first user operation, if required, is a single account-side permission/credential enrollment into the existing personal environment; the assistant cannot inspect or edit a user's Personal vault through repository files.

## M3: reuse, do not build a second writer by default

1. Reuse [Devflow MCP GET-only tools / CLI](DEVFLOW_MCP.md) for repository state.
2. Reuse the connected GitHub tool in ChatGPT **only in an execution surface where it is exposed**, with source Issue and postread verified. Do not pretend Codex Cloud inherits it.
3. Existing [#413](https://github.com/kinoko34077/devflow/issues/413) and [#465](https://github.com/kinoko34077/devflow/issues/465) are **not general-purpose Issue write services**. Expanding a trusted receiver needs a separate, reviewed exact-operation owner and credential boundary, not a field added to its generic payload.
4. Follow [#487](https://github.com/kinoko34077/devflow/issues/487) for **read → plan → safety/actor/permission check → fresh read → bounded effect → independent readback**. GitHub Issue PATCH does not carry proven native body CAS; for an append-only comment record exact source/readback and avoid replay/duplicate comments.

## M4: diagnostic and recovery without repeated configuration

For every blocked write, first produce a short **minimum recovery packet** on the owning work record or an authorized durable alternative:

- **What worked**: exact repo/Issue, branch/HEAD, Cloud environment identity if known, GET/CLI/auth status and whether a native GitHub comment action exists.
- **Where write failed**: distinguish missing tool, invalid credential, unsupported auth, transport/socket failure, HTTP 401/403/404, insufficient repo scope and platform safety denial. Redact tokens, Authorization headers, credential-bearing URLs and private response bodies.
- **What happens next**: which agent can execute an existing authorized route; only if none, which single user **account-side** permission/enrollment is needed, exact repository, endpoint and least privilege.
- **How to prove recovery**: one designated harmless issue comment with unique stable receipt string, independent matching GET URL/body/author verification, no duplicate send. Never infer a negative from GET-only checks.
- **What remains blocked**: separate native MCP registration, M3 work inventory coverage, autonomous agent wake, E0 platform approval, and private-repo/fleet write permissions.

Where the current worker cannot write the owner Issue, do **not** silently claim Issue-first reporting complete. Keep evidence as an explicit `REPORT_PENDING_EXTERNAL_WRITE` state in a reversible connected PR/task artifact *if that route is already authorized*; identify exact owner Issue/expected comment and arrange a legitimate authorized delivery, not an unverified ACK or a second queue.

## M5: proof and stop rule

Do not claim cross-repository Cloud Issue-writing E2E from unit tests, an old Cloud task, `gh auth status`, a published configuration, an Issue comment made by **another** connected agent, or a successful Git fetch/PR.

Minimum real acceptance:
1. Named existing published Cloud environment, *new independent task*, exact checkout/HEAD and actual available GitHub tool/credential path.
2. Identity and allowed repository confirmed without printing the credential.
3. One explicitly authorized test Issue comment POST, one independent GET readback proving correct URL, author and payload; append-only; record no duplicate on replay.
4. Re-enter from a second independent Cloud task or a second selected environment **only if multi-task persistence / multi-environment reuse is a user acceptance condition**, rather than manufacturing unnecessary tests.
5. Exactly named additional repository admission only after its own permission approval and separate positive proof.
6. Reconcile the owning work Issue and stop. Credentials, repo permissions, Cloud environment publish, new writer services, schedules and privileged workflows require their own approvals.

If M5 cannot proceed because the account-side write credential or actual Cloud tool is not exposed, classify `HOLD / WAITING_SECURITY_DECISION` with one concrete permitted setup action, while preserving the accepted read-only Devflow operation and unrelated UniverseGenome experiment hold.
