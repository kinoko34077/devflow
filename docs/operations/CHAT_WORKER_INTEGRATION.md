# Chat Worker Integration (already-open chats)

Status: operational procedure for devflow#199 (#190 Phase E), updated by #203 with the #201 pilot evidence
Contracts: [`CHAT_WORKER_BOOTSTRAP.md`](../spec/CHAT_WORKER_BOOTSTRAP.md), [`CHAT_WORKER_PROFILES.md`](../spec/CHAT_WORKER_PROFILES.md)
Runtime: `kinoko34077/execution-coordinator` → `python -m execution_coordinator.bootstrap_pickup`

This document tells an **already-open, manually-started** Codex, Claude/Claude Code or ordinary ChatGPT chat how to turn a broad instruction such as 「このリポ側に合わせてなんか作業して」 into the common bootstrap path.

There is no provider launch and no provider-to-provider spawning. Every provider uses the same contract, the same classifier and the same claim authority. Provider differences show up only as probe results and tool surfaces.

## 0. Preferred path: Actions-side transport (devflow#205)

A chat that can comment on GitHub needs **no local Python, checkout or token**. Post the command on the request Issue kinoko34077/execution-coordinator#83 (or on any execution-coordinator Issue):

```text
/pickup
target: <owner/repo>
worker_system: <codex|claude|chatgpt>
capabilities: <tags you actually verified, e.g. python, tests>
environment: <e.g. linux>
intent: <the user's words>
```

Then do the following:

1. The `chat-pickup.yml` workflow replies on the same Issue with the typed result. On `CLAIMED` it also returns `claim_id`, `generation`, the ready-made release command and `next_cycle`.
2. Do the bounded work, then post the returned release command.
3. For the next discovery cycle, pass `session: <worker_session_id>` and `cycle: <next_cycle>`.

Notes on the transport:

- Only OWNER, MEMBER or COLLABORATOR comments are processed; anything else is ignored silently.
- Capabilities and environment are the worker's own declaration; Actions adds only the transport surfaces.
- It uses the same contract, the same serialized claim lane and one claim per request.
- A `---` line ends the command, so appended footers are ignored.
- Reading a **private** target repository needs the `COORDINATOR_READ_TOKEN` Actions secret. Creating it is a credential change, so it is Human-gated. Public targets work without it.

Section 1 below remains the local fallback.

## 1. Common path (every provider, local fallback)

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

## 2. Prerequisites (from the #201 pilot)

The ChatGPT pilot leg needed each of these fixed by hand. Check them before the first cycle:

1. **Python ≥ 3.11.** execution-coordinator uses `enum.StrEnum`, so older interpreters fail at import.
2. **Checkouts on the `execution-coordinator` import path**, for example `PYTHONPATH=<execution-coordinator>/src`, plus a **current devflow checkout** (`git -C <devflow> pull --ff-only`). A stale devflow checkout lacks the contract tools.
3. **A GitHub token in the environment** (`GH_TOKEN` or `GITHUB_TOKEN`) with Issues-write and Actions-dispatch on execution-coordinator. A missing or invalid token shows up as HTTP 401, or as no `coordinator:claim` surface.
4. **UTF-8 output**, especially on Windows: set `PYTHONUTF8=1` and use a UTF-8 console. Otherwise Japanese text in posted comments degrades to `??`.

These prerequisites apply only to the local fallback. The Actions-side transport (section 0, #205) removes them.

## 3. Provider status

| Provider | Surfaces | Status |
| --- | --- | --- |
| **Claude / Claude Code** (cloud session with a shell) | `github:read`, `github:write`, `coordinator:claim`; `python`, `git`, `node`, `tests`; `linux` | **Verified.** #197 ran end to end live, and #201 ran two concurrent sessions that made disjoint selections with no duplicate claim. |
| **ordinary ChatGPT with local execution access** | the same surfaces once the prerequisites hold | **Verified in #201.** It went from the broad instruction to `CLAIM_AND_WORK` on canary#7, then claim, acknowledge, comment and release, with the same canonical interpretation as Claude. |
| **ordinary ChatGPT with GitHub comment/write access** (including connector-only sessions) | chat needs only a trusted GitHub Issue-comment write surface; accepted Actions-side transport supplies `github:read` / `github:write` / `coordinator:claim` inside the workflow | **Verified via #202/#205.** Post `/pickup` on the execution-coordinator request Issue; GitHub Actions performs the canonical classify/claim/ack path and returns the typed result. No local Python, checkout or chat-visible token is required. |
| **ordinary ChatGPT local fallback without Actions/comment transport or coordinator access** | may have `github:read` / `github:write`, but no usable `coordinator:claim` path | **Limitation.** Local fallback work dispositions remain `PROVIDER_SURFACE_MISSING`; do not start uncoordinated work. Prefer the accepted Actions-side transport above when GitHub comment/write access exists. |
| **Codex** | expected to match Claude when its sandbox has network access and a token | **Deferred / unverified.** The pilot leg was postponed by the user because of a Codex usage limit; the procedure above applies unchanged. |

## 4. Minimal user invocations

```text
Codex / Claude:  このリポ側に合わせてなんか作業して    (with the target repository open in the session)
ChatGPT:         kinoko34077/<repo> に合わせてなんか作業して
```

The user does not name an Issue. The worker runs section 1 and reports the disposition when there is nothing to claim.
