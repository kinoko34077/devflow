# Chat Worker Profiles v1

Status: accepted baseline under devflow#195; optional direct Review Provenance profile evidence is defined by devflow#211 and follows that owner's acceptance evidence
Authority: devflow cross-repository workflow specification
Depends on: [`CHAT_WORKER_BOOTSTRAP.md`](./CHAT_WORKER_BOOTSTRAP.md) section 12

A **worker profile** is the per-chat/session evidence that fills the identity and profile fields of a `chat-worker-bootstrap-request.v1` request. The required profile fields are `worker_system`, `worker_session_id`, `execution_attempt_id`, `capabilities`, `environment` and `tool_surfaces`; an optional direct `review_provenance` signature may be carried when the session has explicitly observed/declared the Review Provenance v2 `System + Model` it would submit.

A profile is:

- **per session**, not a permanent persona;
- **observed**, not declared by reputation;
- **reproducible**: the same observation always yields the same profile;
- **fail-closed**: anything unknown, stale, contradictory or secret-shaped produces no profile.

Reference implementation: `tools/chat_worker_profile.py` (pure, no I/O), tested by `tests/test_chat_worker_profile.py`.

## 1. Observation (`chat-worker-observation.v1`)

```json
{
  "schema_version": "chat-worker-observation.v1",
  "worker_system": "codex | claude | chatgpt",
  "worker_session_id": "<system>-<YYYYMMDDTHHMMSSZ>-<6 hex>",
  "cycle": 1,
  "observed_at": "2026-09-28T15:55:00Z",
  "probes": { "<probe>": true | false },
  "review_provenance": { "system": "Claude Code", "model": "Claude Sonnet 5" }
}
```

`review_provenance` is optional; the example shows it only to define its shape. Unknown fields and unknown probes are rejected. Every probe in the provider checklist (section 4) must be reported, as `true` or `false`. A missing report is an error, never an implicit `false`.

## 2. Identity rules

| Field | Rule |
| --- | --- |
| `worker_system` | the system the chat runs in: `codex`, `claude` or `chatgpt`. It is provenance only. |
| `worker_session_id` | generated **once** at the chat's first bootstrap as `<system>-<start UTC>-<6 random hex>`. It is reused for the whole chat and recorded as `Execution-Session-ID` in the chat's Session Record. It must start with its own `worker_system`. |
| `execution_attempt_id` | `<worker_session_id>:c<N>` with `N ≥ 1`. It increments for every discovery cycle, including after a claim rejection or refresh. |
| runtime `worker_id` | `<worker_system>:<worker_session_id>`, as defined by the bootstrap contract section 6. |
| optional `review_provenance` | direct `system + model` strings intended for Review Provenance v2; normalized for whitespace, not inferred from `worker_system`, and used only for explicit different-reviewer eligibility. |

The identifier grammar excludes secret-shaped values by construction. No credential, token, cookie or session material may appear in any profile field. Review provenance is self-asserted operational metadata, not authentication; provider/model identity does not grant capability, priority or rank.

## 3. Probe registry (closed for v1)

A tag is emitted **only** when its probe was actually performed by the session and passed. The provider/model name, the user prompt, repository language and past success never add a tag.

| Probe | Field | Tag | How the session verifies it |
| --- | --- | --- | --- |
| `exec.python3` | capabilities | `python` | `python3 --version` exits 0 |
| `exec.git` | capabilities | `git` | `git --version` exits 0 |
| `exec.node` | capabilities | `node` | `node --version` exits 0 |
| `exec.unittest` | capabilities | `tests` | the target repository's documented test command can be started |
| `fs.repository_checkout` | capabilities | `repo-checkout` | a working tree of the target repository is present and readable |
| `os.linux` / `os.macos` / `os.windows` | environment | `linux` / `macos` / `windows` | platform query; at most one may be true |
| `net.github_api` | environment | `github-network` | an HTTPS request to `api.github.com` succeeds |
| `lane.github_actions` | environment | `github-actions-lane` | the session can observe execution-coordinator Actions runs |
| `surface.github_read` | tool_surfaces | `github:read` | the session read live `devflow/AGENTS.md` in this bootstrap |
| `surface.github_write` | tool_surfaces | `github:write` | a tool for branch/commit/PR/comment on the target is available in this chat |
| `surface.coordinator_claim` | tool_surfaces | `coordinator:claim` | the session can dispatch the execution-coordinator `mutate-state.yml` lane |

`tool_surfaces` stay availability evidence. They never participate in capability matching (bootstrap contract section 8).

## 4. Initial provider checklists

Each provider must report **every** probe above.

| Provider | Typical outcome (informative, not granted) |
| --- | --- |
| Codex | shell probes usually pass inside its sandbox; the network and coordinator surfaces depend on the environment configuration |
| Claude / Claude Code | the same as Codex when it has a shell; a chat without a shell reports `exec.*` false |
| ordinary ChatGPT | `exec.*` and `fs.*` are usually false; the `github:*` surfaces depend on the connected GitHub integration; `coordinator:claim` is usually false |

The "typical outcome" column is informative. Only the actual probe results count. A provider that lacks `coordinator:claim` receives `PROVIDER_SURFACE_MISSING` for work dispositions (bootstrap contract section 8). This is a provider-local limitation, not a reason to weaken authority.

## 5. Freshness and normalization

- `observed_at` must not be in the future, and the profile is valid for **60 minutes**. After that the probes must be re-run.
- The request's `observed_at` is the time the profile is converted into a request.
- Tags are sorted, optional review provenance is whitespace-normalized, and the output must pass `chat-worker-bootstrap-request.v1` validation. A profile that cannot form a valid request is rejected.
- Contradictory probes, such as two operating systems, are rejected.
- Changing credentials, session or permission state to make a probe pass is Human-gated. A worker must not do it on its own.

## 6. Compatibility

- **execution-coordinator:** the emitted tags are exactly the strings used by `CandidateRequirements.required_capabilities` / `required_environment`. Matching stays an exact subset check.
- **Bootstrap contract:** a profile only fills request fields. Selection, ranking and claim authority are unchanged. Provider differences affect evidence/tool availability, never task priority. A direct Review Provenance signature may act only as the hard eligibility check for an explicit different-reviewer demand under #211.
