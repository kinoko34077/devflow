# ChatGPT-safe generic dispatch — G1 admission contract

Status: PROPOSED / offline only. Owning Work Order: devflow #413. Not a deployed or authorized execution interface.

## Goal and separation

ChatGPT -> authenticated request adapter -> reviewed operation catalog -> pure G1 admission -> G2/G3 live gates -> approved GitHub API, Actions or separate compute backend -> verified execution evidence.

G1 only returns a classification. ADMITTED is NOT dispatched, running, or succeeded. G1 never invokes GitHub, writes secrets, or authenticates identities.

## Request v1

~~~json
{
  "schema": "dispatch-request.v1",
  "request_id": "req_g1_00000001",
  "repository": "kinoko34077/devflow",
  "action": "repo.status",
  "ref": "main",
  "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "inputs": {}
}
~~~

All fields required and extras denied. No caller-supplied actor, backend, executor, URL, shell, token, approval or workflow ID.

- request_id: bounded opaque idempotency key; G1 syntax only, G2 must implement durable replay fencing.
- repository/action: match a trusted reviewed catalog record exactly.
- ref/head_sha: declared ref and syntactically valid 40-hex commit. G2 must verify the current immutable head and reject movement before effects. G1 cannot see GitHub state.
- inputs: finite typed declared enum, boolean or bounded integer values. Unknown/missing-required keys denied. No arbitrary shell interpolation.
- ref: exactly catalog-bound and Git branch-ref syntax-constrained, including rejection of dot-prefixed components, trailing dot and `.lock`; G1 cannot resolve its target.

Use parse_json_object at the transport boundary: it rejects duplicate JSON keys (including nested), non-object, oversized documents, invalid JSON and NaN/Infinity. Untrusted Issue text must not substitute for authenticated GitHub event identity.

## Catalog v1

~~~json
{
  "schema": "dispatch-catalog.v1",
  "operator": "kinoko34077",
  "actions": {
    "repo.status": {
      "repository": "kinoko34077/devflow",
      "backend": "github_api",
      "executor": "github.repository_metadata",
      "ref": "main",
      "effects": "read",
      "human_gate": false,
      "inputs": {}
    },
    "ci.verify": {
      "repository": "kinoko34077/devflow",
      "backend": "github_actions",
      "executor": ".github/workflows/required.yml",
      "reviewed_workflow_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "ref": "main",
      "effects": "read",
      "human_gate": false,
      "inputs": {
        "mode": {"type":"choice","required":true,"choices":["verify","inspect"]}
      }
    },
    "sync.reconcile": {
      "repository": "kinoko34077/devflow",
      "backend": "github_actions",
      "executor": ".github/workflows/project-sync.yml",
      "reviewed_workflow_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "ref": "main",
      "effects": "write",
      "human_gate": true,
      "inputs": {}
    }
  }
}
~~~

Examples only; no production catalog is installed by G1. Catalog authority is an external invariant: G2 MUST load from a trusted reviewed commit, not from request text, untrusted Issue or PR code. An executor label alone is NOT proof of GitHub token permission or read-only implementation.

- github_api executors are symbolic typed handler names; G2 must bind each to reviewed code, NOT dynamic URLs.
- github_actions executors are fixed reviewed repository-local workflow paths **plus a mandatory `reviewed_workflow_sha` 40-hex Git blob SHA loaded exclusively from the trusted catalog** (the `b...` values shown above are illustrative placeholders, not deployable identities). API entries must not carry this field. G1 passes the trusted SHA through Admission; the request cannot override it. G2 must obtain the actual workflow file blob identity from the immutable reviewed source, prove the live intended target/ref and reviewed workflow blob match, check authorization/permission and capacity before any effect. A mutable workflow path/ref or caller-supplied `head_sha` alone is insufficient. GitHub Actions dispatch by a mutable branch/ref is not made atomic by G1: G2 must design and separately review ref-change/TOCTOU controls before activation.
- effects=write requires human_gate=true. G1 always returns NEEDS_HUMAN for any such operation; a claimed approval field is rejected.
- effects=read/human_gate=false may be ADMITTED, but still requires authenticated execution checks.
- Unknown schema keys, unlisted backends or invalid input definitions cause DENIED.

## Output and future states

Admission fields are status, reason, request_id, repository, action, backend, executor, ref, head_sha and the trusted `reviewed_workflow_sha` (Actions only; `null` for API). Denials never disclose an executable target. No request inputs, secret text or arbitrary shell content is echoed.

- DENIED: invalid trust, request, catalog or input.
- NEEDS_HUMAN: valid request but separately trusted approval is mandatory.
- ADMITTED: offline authorization-policy result only.

G2/G3 must implement real REQUESTED -> ADMITTED/NEEDS_HUMAN/DENIED -> QUEUED -> RUNNING -> SUCCEEDED/FAILED/CANCELLED, with verified per-repository scopes, request-id replay protection, concurrency fence, fresh target/head, trusted actor proof, safety gates and durable Issue evidence. Never equate a created Issue/comment with actual authorization.

## Private split and non-goals

GitHub API-only Private operations can avoid Actions runner usage, subject to permissions and verified adapter connection. Builds, tests or code execution need a compute backend (GitHub-hosted capacity, separately approved self-hosted runner, or external service).

G1 does NOT install an App, token, Runner, Gateway, webhook, action or permission; it does NOT perform API calls; it does NOT migrate existing repositories; it does NOT authorize broader workflow dispatch, publication, release or deployment. Existing #395 public pilot and #384 generated-file writer authority are separate. execution-coordinator#3 remains sole agent-claim runtime authority, not replaced by this dispatch contract.

## Verification and next phases

- Unit: python -m unittest tests.test_safe_dispatch_contract -v
- Compile: python -m compileall -q tools/safe_dispatch_contract.py tests/test_safe_dispatch_contract.py
- G1: Draft PR + negative tests + independent different-reviewer exact-head security review before merge.
- G2: authenticated connector/Gateway + bound executor + durable idempotency, one real read-only allowed-action pilot.
- G3: bounded verified Private GitHub API-only read pilot, write operations only with separate approval.
- G4: Private compute fallback and actual billing/quota check — deferred Human Gate.
- G5: GitHub UI-created and existing-repo migration — separate deferred #395 S5.

Reference: devflow#413, #395, docs/spec/REPOSITORY_BOOTSTRAP.md, devflow/AGENTS.md.
