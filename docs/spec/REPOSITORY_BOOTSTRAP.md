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
    "devflow_managed": true,
    "standard_features": [
      "repo_native_dispatch",
      "generated-artifact-writeback"
    ],
    "main_protection": "public-only-v1"
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

## 4. Visibility choice and safe defaults

Repository visibility is a first-class agent/user choice with two supported values: `private` and `public`.

Agent-facing selection occurs before deterministic execution:

- an explicit `private` or `public` choice in current context MUST be preserved;
- when visibility is not established and an agent can interact with the user, it MUST ask for the `private / public` choice before emitting the Bootstrap Request;
- public visibility MUST NOT be inferred from words such as “OSS”, “public”, or “open-source” appearing elsewhere in prose;
- if interaction is unavailable, or the user explicitly delegates the choice without establishing publication intent, the agent may use the safe `private` fallback.

The executor remains deterministic and fail-safe. If a structured request reaches it without `repository.visibility`, normalization still defaults to `private`.

Other V1 defaults that do not invent semantic/project policy are:

- missing `bootstrap.template` -> `minimal`;
- missing `bootstrap.devflow_managed` -> `true`, except canonical excluded repositories;
- missing `initial_content.license` -> null;
- Repository Base adoption is never implied by `minimal`;
- no release, deployment, publication, repository deletion, shared-history rewrite, credential change or permission expansion is part of bootstrap.
- for **new** managed repositories, request emitters MUST include `bootstrap.standard_features` with the supported default IDs `repo_native_dispatch` and `generated-artifact-writeback`, without asking the user to visit repository settings. The older `bootstrap.repo_native_dispatch` field remains a compatibility alias. An absent `standard_features` field preserves historical v1 request replay behavior and does not seed new files.
- for **new** managed repositories, request emitters MUST include `bootstrap.main_protection: "public-only-v1"`. Bootstrap applies and verifies the accepted `main` protection only for a new Public repository. Private repositories report `NOT_APPLICABLE/PRIVATE_REPOSITORY` and do not call the protection API. An absent field preserves historical v1 replay behavior and does not change branch protection.

V1 does not automatically generate licence text. A non-null licence request is unsupported until a later version defines exact licence material and attribution inputs; it MUST fail validation rather than be silently ignored or guessed.

## 5. Supported v1 template

Required template:

- `minimal`

`minimal` means only the explicitly requested seed and bootstrap provenance. It does not create `.kinotch/`, repository-local `AGENTS.md`, `CURRENT_STATE.md`, Repository Base directories, package scaffolding, CI, release workflows, or language-specific files unless the request schema/version explicitly adds them.

Template taxonomy MUST NOT be expanded merely for cosmetic uniformity.

### 5.1 Optional repository-local Actions command receiver (#395)

`bootstrap.standard_features` including `repo_native_dispatch` (valid only for
`devflow_managed=true`)
automatically seeds `.github/workflows/kinotch-repo-command.yml` from the
version-controlled `templates/bootstrap/kinotch-repo-command.yml`.
No new secret, App installation, **per-repository** manual permission setting,
universal token or privileged runtime workflow is introduced for each repository.
**One-time Human Gate:** the existing `REPOSITORY_BOOTSTRAP_TOKEN` used to seed
`.github/workflows/*` must already have workflow-file writing authority:
classic PAT `repo` + `workflow` scopes, or fine-grained `Contents: write`
+ `Workflows: write` on future managed repositories. This is an additional
privilege compared to creating README files and must be explicitly reviewed
and authorized **once**, never silently added by Bootstrap. Credential compromise
could then modify Actions logic; runtime `GITHUB_TOKEN` isolation does not
eliminate the bootstrap credential risk. If the credential lacks that permission,
GitHub rejects workflow creation, Bootstrap records failure at `SEED` with
`Safe-Retry: after-human-decision`, does not create a partial workflow,
and does not proceed to new Issue/Control creation; already-created README/
specification files remain for an identity-safe recovery. No privileged
permission or credential mutation is performed by this PR.
GitHub issues a temporary
repository-scoped `GITHUB_TOKEN` to the read-only job. v1 only accepts the
exact `/kinotch status` Issue comment from the owner account on an
owner-created Issue (not a pull request); any arbitrary shell/workflow name,
unknown actor, deploy/release, secrets or write permission is rejected.
A later approved repo-specific operation requires normal reviewed code, **not**
manual repository authorization by the owner.

Historical Bootstrap Requests without `bootstrap.standard_features` still use
their original contract and do not gain new files or feature mutations on
replay. This is essential for idempotent recovery. New agents generating
managed-repo Bootstrap Requests must add the standard feature list
automatically; no user checkbox. For generated-artifact writeback, the
executor also records the installed capability under `.devflow/` as described
in section 5.2.
Repositories created directly in the GitHub UI are outside this automatic
bootstrap path unless a separate user-approved external creation hook or
template path exists. Do not claim zero-touch setup for every GitHub creation route.

### 5.2 Standard generated-artifact writeback capability (#1050)

When `bootstrap.standard_features` includes `generated-artifact-writeback`,
Bootstrap seeds `.devflow/standard-features.json` using the strict
`devflow-standard-features.v1` contract and installs the native read-only
status receiver plus a pinned read-only Caller at
`.github/workflows/verified-artifacts-rollout.yml`. The Caller invokes the
existing reusable `.github/workflows/generated-artifact-rollout.yml` at the
exact `GITHUB_SHA` of the Bootstrap executor. It accepts only `dry-run` and
grants `contents:read`, `actions:read`, and `pull-requests:read`. The manifest
is an installed-capability record, not an eligibility or authorization claim.

The manifest identifies the existing fixed-recipe admission and shared writer
(`tools.generated_artifact_rollout.select_fixed_recipe` and
`tools.generated_artifact_writer.verified_writeback`). The native receiver
displays the manifest. The Caller reaches the existing unprivileged producer
and independently authenticated read-only verifier/planner; recipe commands
run only in the contents-read, secret-free producer job. If there is no
generated output at Bootstrap time, the normal result is
`NOT_APPLICABLE/NO_GENERATED_OUTPUT`. An output without an exact admitted
repository/recipe/caller fails closed. Installing the capability does not add
a recipe or activate the disabled generic writer. Effectful writing still
requires a separately reviewed exact-recipe Caller and narrowly scoped
`contents:write` permission. Recipe admission, permission, and credential
changes remain separate Human/security gates.

The feature manifest is ensured without overwriting existing files. A
mismatch fails at `SEED` with `Safe-Retry: after-human-decision`. A historical
request without `standard_features` does not gain this manifest during retry.

### 5.3 Public-only main protection (#1058)

For a new managed-repository request, `bootstrap.main_protection` is the
explicit default policy marker. After seed files are ensured, Bootstrap
re-reads the repository identity and visibility plus its default branch. A
Public repository is eligible only when the verified default branch is exactly
`main`.

After verifying that the repository is Public with default branch `main` and
before protection is applied, Bootstrap seeds the trusted
`.github/workflows/verify.yml` workflow. It emits a job named `verify` for
pushes to `main` and every pull request targeting `main` (without path
filters), requests only `contents:read`, and runs `git diff --check` without
executing repository scripts. The seed push starts the required `verify`
check; Bootstrap waits for its successful completion before configuring
branch protection. On pull requests, the workflow
fetches the event's base SHA explicitly so its shallow checkout can compare
branches whose histories have diverged. A conflicting existing workflow is
left untouched and fails closed. Private repositories do not receive this
workflow. Historical requests without the protection marker do not gain this
workflow on retry.

Bootstrap first reads classic branch protection. If it is absent, the existing
`REPOSITORY_BOOTSTRAP_TOKEN` is used to apply the accepted #78 baseline: require
a pull request, require the stable `verify` Actions check, allow zero native
approvals, require resolved review conversations, enforce the rule for admins,
allow no bypass actors, block force-pushes, and block branch deletion. The
policy is then read back and checked before Bootstrap records `DONE`. If the
current policy already matches, Bootstrap verifies it without writing. A
divergent policy, unexpected repository identity/visibility, or non-`main`
default branch fails closed and is not overwritten.

Before protection is written, Bootstrap reads the exact seeded `main` head and
polls the Public repository's check-runs endpoint without sending the
Bootstrap credential. It waits at most nine observations, 15 seconds apart,
and proceeds only when the latest `verify` run for that SHA has completed
successfully under GitHub Actions app `15368`. A failed run requires human
review; a missing or still-pending run times out without issuing a protection
PUT and can be retried. This uses public read-only check data and adds no token
permission. See GitHub's
[List check runs for a Git reference API](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference).

For the required check, the protection PUT sends `contexts: ["verify"]` after
that successful app-bound run. Bootstrap then requires the GET readback to
contain both `contexts: ["verify"]` and `checks: [{"context":"verify",
"app_id":15368}]`. This keeps the accepted app-bound check while using the
required request field for the full branch-protection endpoint. See GitHub's
[Update branch protection API](https://docs.github.com/en/rest/branches/branch-protection#update-branch-protection).

The optional push `restrictions` field is owner-type aware. GitHub only
supports user, app, and team push restrictions for organization-owned
repositories. For a personal (`User`) repository, Bootstrap omits this field
from the PUT and treats an absent or `null` readback as no push restriction; a
non-null value is divergent and fails closed. For an organization-owned
repository, Bootstrap sends `restrictions: null` and requires an explicit null
readback. An unknown owner type fails closed before the protection mutation.
This preserves the #78 baseline without sending an unsupported field to a
personal repository. See GitHub's
[protected-branches API documentation](https://docs.github.com/en/rest/branches/branch-protection?apiVersion=2022-11-28).

If GitHub rejects the protection PUT with HTTP 422 despite the successful
check preflight, Bootstrap fails closed immediately at `MAIN_PROTECTION` with
`Safe-Retry: after-human-decision`. GitHub uses 422 for both validation errors
and endpoint spam, so Bootstrap does not automatically repeat this write. A
later explicit request first reads the current protection state and may
continue only if it already matches the accepted baseline; divergent or
unreadable state fails closed. This does not change credentials, permissions,
or an existing protection policy.

The branch-protection API requires an already-authorized credential with
administration write access for the target repository. Confirm that the
existing bootstrap credential covers future Public repositories before live
provisioning. Missing permission is recorded at `MAIN_PROTECTION` with
`Safe-Retry: after-human-decision`; Bootstrap never expands credential scopes,
changes secrets, or widens workflow permissions. A protection failure leaves
the created repository and seed files available for identity-safe recovery and
does not proceed to new owner Issues or the Repository Control.

Private repositories report `NOT_APPLICABLE/PRIVATE_REPOSITORY`, do not call
branch-protection APIs, and do not require `main.protected=true`. Requests
without `main_protection` report the legacy policy as not applicable and do not
gain protection changes on historical v1 retry. This policy is never applied
to an existing-repository batch; that rollout has a separate owner.

## 6. Trust boundary

The public devflow repository receives Issue events from arbitrary GitHub users. A title prefix is therefore never authorization.

Secret-bearing provisioning requires all of the following:

1. exact devflow event repository identity;
2. exact GitHub Issue identity and canonical URL;
3. title exactly matches `[REPO CREATE] <repository.name>`;
4. one valid `repository-bootstrap.v1` payload;
5. initiating Issue-event sender is the canonical allowlisted numeric principal and matches the GitHub Actions actor ID, actor login, and triggering actor;
6. request author has the allowlisted numeric GitHub `user.id` `79015263`; if GitHub supplies a login, it must match `kinoko34077`. `author_association` may be checked as supplementary defense-in-depth, but never grants trust by itself;
7. an approved `REPOSITORY_BOOTSTRAP_TOKEN` is configured.

The current canonical human allowlist is owned by `tools/github_issue_trust.py`
and contains only user ID `79015263` (`kinoko34077`). `author_association`
is defense-in-depth metadata and MUST NOT grant authority by itself. Event
sender and Issue author are separate identities; both must pass the applicable
numeric-principal check.

A minimal no-secret actor-admission job runs before validation and has only
`contents:read`. It fails closed on missing, malformed, mismatched or
non-allowlisted event identity. Both the validation and secret-bearing
provisioning job conditions also require `github.triggering_actor ==
github.actor`, in addition to the admission output; this prevents a partial
rerun by a different writer from reusing successful prerequisite outputs to
start a privileged job. The `actor-admission` and `validate` jobs do not receive
`REPOSITORY_BOOTSTRAP_TOKEN`; failed admission or validation prevents the gated
`provision` job from starting. The workflow injects `REPOSITORY_BOOTSTRAP_TOKEN`
into the gated provision step environment before Python performs the final Issue
recheck. A failed final check prevents Python from reading or using that value
and from constructing the executor; it does not mean the credential was absent
from the step environment. Python first reads `DEVFLOW_TOKEN` to fetch the
current Issue. After request parsing and the final current-Issue and trusted
author checks, it reads the external bootstrap token and constructs the executor.

### 6.1 Current request freshness

The GitHub event payload is a historical Issue snapshot and may be replayed by a workflow rerun. Before validation, the executor MUST fetch the current source Issue using the existing `DEVFLOW_TOKEN`. The fetched Issue MUST match the event's positive numeric Issue ID, number, canonical URL, `updated_at`, title, and body, and MUST still be open. Validation MUST use the fetched current Issue for title, author, and request-body checks. A missing token, failed read, identity mismatch, closed Issue, or changed revision fails closed.

Immediately before Python reads `REPOSITORY_BOOTSTRAP_TOKEN` from its environment, the provisioner MUST repeat the current-Issue comparison and trusted author check after parsing. A stale, closed, or untrusted final Issue MUST NOT cause Python to read or use the external bootstrap credential or construct or invoke the provisioning executor. When the current Issue identity, its `[REPO CREATE]` title, and trusted author are verified, validation records a `FAILED / VALIDATION` status comment explaining the stale or closed snapshot; read failures and unverified identities MUST NOT mutate the Issue.

Re-running a stale or closed historical snapshot is expected to fail freshness checks; an unchanged open snapshot remains retryable. Edit or reopen the current request to create a fresh Issue event when needed.

This is a freshness fence, not an atomic compare-and-swap. A change concurrent with the final read and the first external effect is not excluded by the GitHub Issue API.

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
When native-dispatch seeding fails for missing workflow-file credentials,
the failure is explicitly Human-gated at `SEED` and the executor does not
proceed to Issues/Control. Partial README/specification seed is retained
for safe, provenance-checked recovery after approval.

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
   repository, its author has an allowlisted numeric user ID with supplied-login
   consistency checked (`author_association` is supplementary only), and contains
   one valid `repository-bootstrap.v1` payload for the same target with
   management and Control creation enabled;
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
3. preserve explicit user choices such as visibility, licence intent and exclusions;
4. resolve repository visibility before emitting the request: preserve an established `private`/`public` choice; otherwise ask the user when interaction is available; if interaction is unavailable or the user delegates the choice without publication intent, use the safe `private` fallback;
5. use other safe defaults only where this specification defines them;
6. create one `[REPO CREATE] <repository-name>` Issue carrying `repository-bootstrap.v1`;
7. allow the deterministic bootstrap workflow to create/initialize/register the repository;
8. report resulting repository, initial owner Issue(s) and Repository Control;
9. continue detailed work from the new repository's own canon.

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
- exact trusted-principal identity tests;
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
- automatic credential/secret/permission setup (even if workflow-file writes
  require a one-time `REPOSITORY_BOOTSTRAP_TOKEN` scope change);
- forced Repository Base adoption;
- automatic release/deploy/publication;
- automatic repository deletion;
- replacement of repository-local specs, Issues or Current State with the Bootstrap Request.
