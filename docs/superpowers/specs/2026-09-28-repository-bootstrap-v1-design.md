# Repository Bootstrap v1 Design

Status: implementation design for devflow Work Order #181

## 1. Goal

Allow a trusted agent to turn a natural-language instruction such as「今回の内容をもとに、新規リポつくって」into one durable devflow request that deterministically provisions a repository, seeds its initial canonical material, creates requested initial Issues, and registers one devflow Repository Control.

The agent interprets meaning. The executor does not.

```text
conversation / source material
  -> agent
  -> [REPO CREATE] request + repository-bootstrap.v1 JSON
  -> deterministic devflow workflow
  -> repository + seed + owner Issues + [REPO] Control
```

## 2. Authority boundaries

- `[REPO CREATE] <name>` owns the finite bootstrap request and recovery evidence.
- The new repository owns its README/specification/Issues after creation.
- `[REPO] <name>` owns only long-lived cross-repository state/routing.
- GitHub Project remains display-only.
- Chat is never bootstrap state authority.
- The executor does not contain an LLM or infer missing semantic intent.

## 3. Canonical request serialization

V1 uses one fenced JSON object because Python stdlib can parse it deterministically without adding YAML/schema-library dependencies.

Issue body contains exactly one block delimited by markers:

```text
<!-- repository-bootstrap:v1:start -->
```json
{ ... }
```
<!-- repository-bootstrap:v1:end -->
```

The JSON root must contain `schema: "repository-bootstrap.v1"`.

Required normalized fields:

```json
{
  "schema": "repository-bootstrap.v1",
  "repository": {
    "owner": "kinoko34077",
    "name": "example",
    "description": "...",
    "visibility": "private"
  },
  "classification": {
    "kind": "library",
    "priority": "P2",
    "risk": "MEDIUM"
  },
  "bootstrap": {
    "template": "minimal",
    "devflow_managed": true
  },
  "initial_content": {
    "readme": "# example\n",
    "specification": null,
    "license": null
  },
  "issues": [],
  "devflow": {
    "create_control": true,
    "work_status": "WORK_ORDER_READY",
    "repository_state": "ACTIVE",
    "next_action": "[SPECIFY] Define the first implementation slice."
  }
}
```

Safe normalization rules:

- missing `visibility` -> `private`;
- missing `bootstrap.template` -> `minimal`;
- missing `bootstrap.devflow_managed` -> `true` unless repository is canonically excluded;
- missing licence remains null; never guess one;
- public visibility is only accepted when request JSON explicitly says `public`;
- only `minimal` template is required in v1;
- Repository Base files are never implied by `minimal`.

## 4. Validation

The core validator rejects before mutation when any of the following is true:

- schema is unknown;
- Issue title is not exactly `[REPO CREATE] <repository.name>`;
- owner/name syntax is invalid;
- owner is not an allowed bootstrap owner (`kinoko34077` in v1);
- visibility is not `private|public`;
- priority/risk/work-status/repository-state are outside canonical devflow values;
- template is unsupported;
- duplicate request-local Issue keys exist;
- an Issue key/title/body is malformed;
- `create_control=true` while `devflow_managed=false`;
- explicit values conflict with canonical exclusions.

The workflow separately checks request author trust before any secret-bearing job is eligible.

## 5. Trust model

Workflow trigger: `issues` events `opened`, `edited`, `reopened`.

A non-secret validation job may inspect any candidate request. The provisioning job is eligible only if all are true:

1. title starts with `[REPO CREATE] `;
2. parser/validator succeeds;
3. author association is one of `OWNER`, `MEMBER`, `COLLABORATOR`;
4. `REPOSITORY_BOOTSTRAP_TOKEN` is available.

The secret is exposed only to the provisioning job/step. Validation never receives it.

`GITHUB_TOKEN` is used only for devflow-local Issue comments/Control creation. The external bootstrap token is used only for account/new-repository operations.

## 6. Credential boundary

The code supports a least-privilege external token but does not create or configure it.

Expected capabilities for a fine-grained user token, subject to current GitHub product constraints at setup time:

- Repository creation / Administration write sufficient for `POST /user/repos`;
- Contents write on created repositories;
- Issues write on created repositories.

Credential creation, secret storage and permission changes remain an explicit Human Gate under #181.

## 7. Repository provenance and idempotency

Every repository created by this protocol receives `.github/repository-bootstrap.json` containing:

```json
{
  "schema": "repository-bootstrap-provenance.v1",
  "request_ref": "kinoko34077/devflow#181",
  "request_url": "https://github.com/kinoko34077/devflow/issues/181",
  "repository": "kinoko34077/example"
}
```

This file is bootstrap provenance only; it is not Current State or Repository Base adoption.

Retry behavior:

- repository absent -> create it;
- repository exists + matching provenance -> reuse;
- repository exists + provenance absent/mismatched -> fail closed as collision;
- requested owner Issue has hidden marker `<!-- repository-bootstrap:<request_ref>:issue:<key> -->`; matching Issue is reused, conflicting duplicates fail closed;
- devflow Control is reused only when exactly one open `[REPO] <name>` exists and its Repository field matches the target; duplicates/conflicts fail closed.

The executor never deletes/replaces conflicting resources automatically.

## 8. Provisioning sequence

Provisioning is serial and checkpointable:

1. validate request/event again inside secret-bearing executor;
2. comment request state `PROVISIONING`;
3. ensure repository;
4. ensure provenance file;
5. ensure requested seed files (`README.md`, optional `docs/SPECIFICATION.md`);
6. obtain actual default-branch head SHA;
7. ensure each initial owner Issue by stable request-local key;
8. ensure one devflow Control when managed;
9. comment terminal `DONE` with canonical links and SHA.

If any stage raises a deterministic/API error, comment `FAILED` with stage, error class/message, already-created resources and `safe_retry` disposition, then exit non-zero.

## 9. Initial repository creation

V1 creates an empty personal repository through GitHub REST, then uses the Contents API serially. The first provenance/README write initializes an empty repository and creates a branch/commit; subsequent seed files are separate deterministic commits.

The contract requires an initialized repository and accepted initial SHA, not a fabricated one-commit history. Template generation may be introduced later without changing the request contract.

## 10. GitHub API boundary

`tools/repository_bootstrap.py` contains pure validation/planning plus a narrow `GitHubApi` adapter using Python stdlib `urllib`.

`GitHubApi` methods are explicit operations rather than a generic arbitrary REST proxy, including:

- get/create repository;
- get/create/update file content;
- get default-branch head;
- list/create issues;
- create devflow comment/control.

Tests use a fake adapter and never require network credentials.

## 11. Workflow / CLI boundary

`.github/workflows/repository-bootstrap.yml` owns event trigger, permissions, checkout/Python setup, trust gating and token injection.

`scripts/repository_bootstrap.py` provides two commands:

- `validate-event --event <path> --github-output <path>`: parse and validate without secrets; emit `valid`, `authorized`, `repository_name`.
- `execute-event --event <path>`: revalidate and execute with `DEVFLOW_TOKEN` + `REPOSITORY_BOOTSTRAP_TOKEN`.

Workflow YAML does not contain provisioning logic.

## 12. Files

New:

- `tools/repository_bootstrap.py` — contract, parser, validator, planner/executor, bounded GitHub REST adapter.
- `scripts/repository_bootstrap.py` — CLI only.
- `tests/test_repository_bootstrap.py` — core behavior/idempotency/recovery tests.
- `tests/test_repository_bootstrap_workflow.py` — static trust/workflow checks.
- `.github/workflows/repository-bootstrap.yml` — Issue trigger/orchestration.
- `docs/operations/REPOSITORY_BOOTSTRAP.md` — agent/operator protocol and Human Gate.
- `schemas/repository-bootstrap.v1.schema.json` — documentary/machine-readable contract schema using JSON Schema draft 2020-12.

Modified:

- `.github/workflows/project-sync-tests.yml` — include new bootstrap modules/workflow/docs in required gate and compile check.
- `.devflow/WORKFLOW.yaml` — declare bootstrap request/control boundary and credential gate.
- `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md` — canonical repository onboarding/bootstrap section.
- `AGENTS.md` — agent instruction for explicit new-repository requests.

## 13. Failure semantics

Failures are classified at the smallest stable stage:

`VALIDATION`, `REPOSITORY`, `PROVENANCE`, `SEED`, `ISSUES`, `CONTROL`, `FINALIZE`.

The request comment includes:

```text
Repository-Bootstrap-State: FAILED
Stage: <stage>
Safe-Retry: yes|no|after-human-decision
Created/Observed Resources:
- ...
Failure: <bounded text>
Next-Action: <exact recovery action>
```

Conflict failures use `Safe-Retry: after-human-decision`; transient API failures after identity-safe partial creation use `yes`.

## 14. Testing

TDD coverage must prove at least:

- valid minimal request defaults to private/minimal/managed;
- explicit public is preserved but never inferred;
- malformed/unknown schema rejects;
- untrusted author never becomes authorized;
- title/name mismatch rejects;
- duplicate Issue keys reject;
- repository collision without matching provenance fails closed;
- retry with matching provenance reuses repository;
- existing marked owner Issue is reused;
- duplicate Controls fail closed;
- partial failure reports stage/resources/retry disposition;
- workflow secret is present only in the provisioning job/step and provisioning depends on successful trusted validation.

Full `python -W error -m unittest discover -v` and compile checks remain required.

## 15. Acceptance / current boundary

Credential-independent implementation is acceptable to merge when tests/review are green because it is repository-only and revertible.

Operational E2E is **not** complete until an approved external bootstrap credential is configured. No credential/App/secret/permission mutation is authorized by this design or Work Order #181 alone.
