# Repository Bootstrap Specification

Status: Canonical devflow specification
Schema: `repository-bootstrap.v1`
Owning Work Order: devflow #181

## 1. Purpose

Repository Bootstrap is the GitHub-native boundary for an explicit request to create a new KiNoTch. repository from already-established conversation, source, or specification context.

The intended human interaction is:

```text
"今回の内容をもとに、新規リポつくって"
        ↓
trusted agent interprets current context
        ↓
[REPO CREATE] <repository-name>
        ↓
deterministic devflow bootstrap executor
        ↓
repository + initial canonical seed + initial Issues + [REPO] Control
```

The agent owns semantic interpretation. The executor owns deterministic provisioning. The executor MUST NOT contain an LLM or infer missing semantic intent from free-form prose.

## 2. Authority model

Repository creation uses two distinct Issue authorities.

### 2.1 Bootstrap Request

Title:

```text
[REPO CREATE] <repository-name>
```

Purpose: finite creation command, input contract, execution/recovery evidence.

The request remains the provenance record for how the repository was created. It is not long-lived repository Current State.

### 2.2 Repository Control

Title:

```text
[REPO] <repository-name>
```

Purpose: cross-repository current-state and routing summary after onboarding.

After bootstrap completes, detailed requirements, specifications, implementation tasks and Current State belong in the new repository. The Bootstrap Request MUST NOT become a second durable technical authority.

## 3. Request contract

The request Issue contains exactly one machine-readable block:

````markdown
<!-- repository-bootstrap:v1:start -->
```json
{
  "schema": "repository-bootstrap.v1",
  "repository": {
    "owner": "kinoko34077",
    "name": "example-repo",
    "description": "Example repository",
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
    "readme": "# example-repo\n",
    "specification": null,
    "license": null
  },
  "issues": [
    {
      "key": "scope",
      "title": "Initial scope",
      "body": "Define the initial scope.",
      "role": "parent"
    }
  ],
  "devflow": {
    "create_control": true,
    "work_status": "WORK_ORDER_READY",
    "repository_state": "ACTIVE",
    "next_action": "[SPECIFY] Define the first implementation slice."
  }
}
```
<!-- repository-bootstrap:v1:end -->
````

The documentary JSON Schema is `schemas/repository-bootstrap.v1.schema.json`. Runtime validation in `tools/repository_bootstrap.py` is authoritative for execution.

## 4. Safe defaults

V1 applies only defaults that do not invent semantic/project policy:

- missing `repository.visibility` -> `private`;
- missing `bootstrap.template` -> `minimal`;
- missing `bootstrap.devflow_managed` -> `true`, except canonical excluded repositories;
- missing `initial_content.license` -> null;
- public visibility is never inferred from words such as “OSS”, “public”, or “open-source” appearing elsewhere in prose;
- Repository Base adoption is never implied by `minimal`;
- no release, deployment, publication, repository deletion, shared-history rewrite, credential change or permission expansion is part of bootstrap.

V1 does not automatically generate licence text. A non-null licence request is unsupported until a later version defines exact licence material and attribution inputs; it MUST fail validation rather than be silently ignored or guessed.

## 5. Supported v1 template

Required template:

- `minimal`

`minimal` means only the explicitly requested seed and bootstrap provenance. It does not create `.kinotch/`, repository-local `AGENTS.md`, `CURRENT_STATE.md`, Repository Base directories, package scaffolding, CI, release workflows, or language-specific files unless the request schema/version explicitly adds them.

Template taxonomy MUST NOT be expanded merely for cosmetic uniformity.

## 6. Trust boundary

The public devflow repository receives Issue events from arbitrary GitHub users. A title prefix is therefore never authorization.

Secret-bearing provisioning requires all of the following:

1. exact devflow event repository identity;
2. exact GitHub Issue identity and canonical URL;
3. title exactly matches `[REPO CREATE] <repository.name>`;
4. one valid `repository-bootstrap.v1` payload;
5. request author association is exactly `OWNER`, `MEMBER`, or `COLLABORATOR`;
6. an approved `REPOSITORY_BOOTSTRAP_TOKEN` is configured.

Validation runs without the repository-creation credential. Untrusted Issue authors MUST NOT cause that credential to enter their job environment.

## 7. Credential boundary / Human Gate

Repository creation requires authority outside the normal repository-scoped `GITHUB_TOKEN`.

The executor consumes `REPOSITORY_BOOTSTRAP_TOKEN` only after trust and schema validation. Creating, rotating or replacing the token; creating/configuring a GitHub App/private key; storing/changing Actions secrets; or expanding account/repository permissions is a **Human Gate** and requires explicit user confirmation under devflow safety policy.

Absence of an approved credential is a valid operational blocker, not permission to weaken the boundary.

The devflow-local `GITHUB_TOKEN` remains limited to the devflow operations required to comment on the request and create/reuse the Repository Control.

## 8. Idempotency and provenance

Each created repository records:

```text
.github/repository-bootstrap.json
```

with schema `repository-bootstrap-provenance.v1`, request reference, request URL and target repository identity.

Retry rules:

- repository absent -> create;
- repository exists with matching provenance -> reuse;
- repository exists without provenance -> fail closed;
- repository exists with mismatched provenance -> fail closed;
- requested owner Issue is identified by a request-scoped hidden marker and reused even if already closed;
- multiple matching Issue markers -> fail closed;
- exactly one matching open Repository Control may be reused;
- duplicate or conflicting Controls -> fail closed.

Existing user-edited seed files are never silently overwritten during a retry.

### 8.1 Downstream Control trust

The bootstrap-generated `[REPO] <name>` Control is a derived operational
record, not an independently trusted bot identity. The read-only Devflow MCP
may accept a non-`OWNER`/`MEMBER`/`COLLABORATOR` Control only when all of the
following are true:

1. the observed devflow repository is exactly `kinoko34077/devflow`;
2. the Control title is exactly `[REPO] <name>`, it is open, and it is unique;
3. the Control contains one valid `repository-bootstrap-control.v1` provenance
   block, or the canonical legacy generated-Control provenance text;
4. the referenced open `[REPO CREATE] <name>` request is in the exact devflow
   repository, has a trusted author association, and contains one valid
   `repository-bootstrap.v1` payload for the same target with management and
   Control creation enabled;
5. the request has a terminal `DONE` bootstrap comment emitted by the GitHub
   Actions bootstrap executor, naming the exact target repository and this
   exact Control URL; and
6. the target's `.github/repository-bootstrap.json` parses as
   `repository-bootstrap-provenance.v1` and exactly matches the request and
   target identities.

This rule derives trust from a verifiable request/provisioning/registration
chain. The executor marker is checked only on the terminal bootstrap comment;
it does not globally trust `github-actions[bot]` or any other bot. Any
missing, malformed, mismatched, non-terminal or duplicate chain fails closed.
The MCP retains legacy-text compatibility so an already-created Control does
not need to be recreated solely to adopt the stronger machine-readable block.

## 9. Execution lifecycle

Conceptual lifecycle:

```text
REQUESTED
-> VALIDATED
-> PROVISIONING
-> REPOSITORY_CREATED
-> INITIALIZED
-> REGISTERED
-> DONE
```

Failure terminal:

```text
FAILED
```

The implementation may compact intermediate states, but a failure record must expose:

- stage;
- bounded failure reason;
- created/observed resources;
- safe retry disposition;
- exact next action.

Stable failure stages are:

- `VALIDATION`
- `REPOSITORY`
- `PROVENANCE`
- `SEED`
- `ISSUES`
- `CONTROL`
- `FINALIZE`

Identity/collision failures require human reconciliation before retry. Transient failures after identity-safe partial creation may be retried through the same request.

## 10. Provisioning order

For a trusted valid request:

1. revalidate event and request in the secret-bearing executor;
2. record `PROVISIONING` on the request;
3. ensure target repository identity;
4. ensure bootstrap provenance;
5. ensure requested README and optional specification seed without overwrite;
6. observe actual default-branch head SHA;
7. ensure requested repository-local Issues by stable request-local keys;
8. ensure exactly one devflow `[REPO] <name>` Control when managed;
9. record `DONE`, actual SHA and canonical links on the request.

The Control's Audit SHA is the observed accepted bootstrap head, never a guessed/pending SHA.

## 11. Agent protocol

When a user explicitly asks an agent to create a new repository from current context, and that context already fixes the substantive requirements, the agent should not ask the user to manually repeat fields it can derive.

The agent should:

1. confirm relevant live devflow canon when managed state matters;
2. determine one repository responsibility/name/description/kind from the current context;
3. preserve explicit user choices such as public/private, licence intent and exclusions;
4. use safe defaults only where this specification defines them;
5. create one `[REPO CREATE] <repository-name>` Issue carrying `repository-bootstrap.v1`;
6. allow the deterministic bootstrap workflow to create/initialize/register the repository;
7. report resulting repository, initial owner Issue(s) and Repository Control;
8. continue detailed work from the new repository's own canon.

If bootstrap is blocked only because the approved credential is absent, report the Human Gate rather than bypassing it with an unrelated credential path.

## 12. Implementation boundary

Canonical implementation surfaces:

- `.github/workflows/repository-bootstrap.yml` — event/trust orchestration only;
- `scripts/repository_bootstrap.py` — event CLI;
- `tools/repository_bootstrap.py` — contract, validator, idempotent executor, bounded REST adapter;
- `tools/devflow_mcp_core.py` — read-only Control discovery and derived bootstrap provenance verification;
- `schemas/repository-bootstrap.v1.schema.json` — documentary schema;
- `tests/test_repository_bootstrap*.py` — deterministic contract/security/recovery tests;
- `docs/operations/REPOSITORY_BOOTSTRAP.md` — operator/request instructions.

Workflow YAML MUST NOT become the primary provisioning implementation.

## 13. Verification boundary

Credential-independent acceptance requires:

- parser/normalization tests;
- malformed/unknown schema rejection;
- exact trust-association tests;
- idempotency/collision tests;
- partial-failure recovery evidence tests;
- static workflow secret-fencing tests;
- full devflow regression suite;
- compile checks;
- exact-head PR Review under current devflow policy.

A real repository-creation E2E is separate. It may run only after an approved least-privilege credential is configured. The initial E2E repository should be private and clearly test-scoped. Automatic deletion is not part of E2E because deletion is destructive and separately gated.

## 14. Non-goals

- LLM inference inside the executor;
- arbitrary GitHub-operation proxying;
- second durable task database;
- GitHub Project as authority;
- automatic public visibility;
- licence guessing;
- automatic credential/secret/permission setup;
- forced Repository Base adoption;
- automatic release/deploy/publication;
- automatic repository deletion;
- replacement of repository-local specs, Issues or Current State with the Bootstrap Request.
