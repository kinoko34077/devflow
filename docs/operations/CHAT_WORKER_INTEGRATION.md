# Chat Worker Integration (already-open chats)

Status: operational procedure for devflow#199 (#190 Phase E)
Contracts: [`CHAT_WORKER_BOOTSTRAP.md`](../spec/CHAT_WORKER_BOOTSTRAP.md), [`CHAT_WORKER_PROFILES.md`](../spec/CHAT_WORKER_PROFILES.md)
Runtime: `kinoko34077/execution-coordinator` → `python -m execution_coordinator.bootstrap_pickup`

This document tells an **already-open, manually-started** Codex, Claude/Claude Code or ordinary ChatGPT chat how to turn a broad instruction such as 「このリポ側に合わせてなんか作業して」 into the common bootstrap path.

There is no provider launch and no provider-to-provider spawning. Every provider uses the same contract, the same classifier and the same claim authority. Provider differences show up only as probe results and tool surfaces.

## 1. Common path (every provider)

```text
1. read live devflow/AGENTS.md, then the target [REPO] Control (live GitHub is the source of truth)
2. run one discovery cycle:
     python -m execution_coordinator.bootstrap_pickup pickup \
       --target <owner/repo> --worker-system <codex|claude|chatgpt> \
       --devflow <path to devflow checkout> --intent "<user's words>" [--execute]
3. act on the disposition:
     CLAIM_AND_WORK / REVIEW_WORK / RECOVERY_WORK
         (only after --execute printed a claim_id and the acknowledge succeeded)
         -> post/resume the Execution Session Record on the task Issue
            (Execution-Session-ID = worker_session_id)
         -> bounded work -> PR -> review -> reconcile
         -> python -m execution_coordinator.bootstrap_pickup release \
              --claim-id <id> --generation <n> --idempotency-key <attempt>:release
     NEEDS_HUMAN        -> ask the user about that gate only
     WAIT_EXTERNAL      -> report the named blocker; recheck later
     NO_ELIGIBLE_WORK   -> report it; do not invent a task
     NEEDS_EVIDENCE     -> report reason_code; resolve evidence; never guess
4. after a rejection or any non-work result: new cycle later
   (the session file advances the attempt id automatically)
```

Rules that bind every provider:

- Do not ask the user to pick an Issue when the classifier returned a work disposition.
- A chat without the `coordinator:claim` surface must not start implementation on a candidate. It receives `PROVIDER_SURFACE_MISSING`, and there is **no uncoordinated fallback**.
- The session file `.chat-worker-session.json` holds only chat identity (`worker_session_id`, cycle). It is never task truth and must never contain secrets.
- Tokens come from the environment (`GH_TOKEN` / `GITHUB_TOKEN`). They are never pasted into chat text, profile fields or Issues. Creating or broadening credentials is Human-gated.

## 2. Provider status

| Provider | Access path | Surfaces | Status |
| --- | --- | --- | --- |
| **Claude / Claude Code** (cloud session with a shell) | the repository checkout and a shell run the command directly; GitHub through the session token | `github:read`, `github:write`, `coordinator:claim`; `python`, `git`, `node`, `tests`; `linux` | **Verified.** A live end-to-end run for #197 went from the broad instruction to `CLAIM_AND_WORK` → claim → acknowledge → work → release on the real lane. The read-only CLI run for #199 matches. |
| **Codex** (already-open Codex session with a repository sandbox) | the command runs in the Codex sandbox from a checkout of execution-coordinator plus devflow | expected to match Claude **only if** the Codex environment grants network access to `api.github.com` and supplies a token with Issues-write and Actions-dispatch on execution-coordinator | **Not yet verified.** It must be verified from inside a Codex session (Phase F). Without network or token, its probes report no surfaces and it gets `PROVIDER_SURFACE_MISSING`; that is a provider-local limitation, not a reason to weaken authority. |
| **ordinary ChatGPT** (chat with a GitHub connector) | the connector reads Issues/files; there is no shell | at most `github:read` and possibly `github:write` via the connector; **no `coordinator:claim`**, because it cannot dispatch the `mutate-state.yml` lane | **Limitation recorded.** Work dispositions become `NEEDS_EVIDENCE` / `PROVIDER_SURFACE_MISSING`. ChatGPT may still perform the read-only bootstrap: it reads the Control and reports the non-work disposition. It must not implement unclaimed candidates. Removing this limitation would need a supported claim transport for ChatGPT, which is a separate future Issue. |

## 3. Minimal user invocations

```text
Codex / Claude:  このリポ側に合わせてなんか作業して    (with the target repository open in the session)
ChatGPT:         kinoko34077/<repo> に合わせてなんか作業して
```

The user does not name an Issue. The worker runs section 1 and reports the disposition when there is nothing to claim.
