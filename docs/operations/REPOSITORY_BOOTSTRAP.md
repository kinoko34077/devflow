# Repository Bootstrap Operations Manual

Canonical specification: `docs/spec/REPOSITORY_BOOTSTRAP.md`  
Machine contract: `.devflow/WORKFLOW.yaml`  
Owning Work Order: devflow #181

## 1. When to use this path

Use Repository Bootstrap when the user explicitly asks to create a **new repository** from context that is already available to the agent, for example:

> 今回の内容をもとに、新規リポつくって

Do not use it merely because a discussion could hypothetically become a repository. The creation request must be explicit.

The agent extracts the already-established responsibility, repository name, description, initial canonical material and useful initial Issue decomposition. It must not ask the user to repeat information already fixed by the current conversation/sources.

## 2. Safe defaults

Only these v1 defaults are automatic:

- `visibility`: `private` when not explicitly established;
- template: `minimal`;
- devflow-managed: true unless the repository is canonically excluded;
- `license`: null/omitted.

Public visibility must be explicit in the structured request. Words in prose such as “OSS” do not make the executor infer `public`.

V1 does not generate licence text. A non-null licence request is unsupported until a later contract defines exact licence material/attribution inputs. Do not guess a licence.

`minimal` does not mean Repository Base. Do not generate Base files or layout unless a later explicit request/specification owns that decision.

## 3. Create the request Issue

Create one Issue in `kinoko34077/devflow` titled exactly:

```text
[REPO CREATE] <repository-name>
```

Include human-readable source/context, then exactly one payload block:

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
      "title": "Initial scope / requirements",
      "body": "Durable initial requirements derived from the source discussion.",
      "role": "parent"
    }
  ],
  "devflow": {
    "create_control": true,
    "work_status": "WORK_ORDER_READY",
    "repository_state": "ACTIVE",
    "next_action": "[SPECIFY] Continue from the repository-local parent Issue."
  }
}
```
<!-- repository-bootstrap:v1:end -->
````

Stable Issue `key` values are request-local idempotency keys. Reusing the same Bootstrap Request after a partial failure must reuse the same keys.

## 4. What the workflow does

`.github/workflows/repository-bootstrap.yml` is triggered by Issue `opened`, `edited`, and `reopened` events.

The workflow has two security stages:

1. **validate** — no `REPOSITORY_BOOTSTRAP_TOKEN`; checks observed devflow Issue identity, exact request syntax, schema and trusted `author_association`.
2. **provision** — runs only when validation reports both `valid=true` and `authorized=true`; this stage receives the external bootstrap credential.

A normal Issue is ignored successfully. A malformed trusted `[REPO CREATE]` request is recorded as `FAILED / VALIDATION`. An untrusted Issue author cannot reach the secret-bearing provisioning job.

## 5. Idempotency

Repository Bootstrap is ensure-oriented.

On retry:

- a repository with matching `.github/repository-bootstrap.json` provenance is reused;
- a repository without matching provenance is a collision and fails closed;
- bootstrap-owned owner Issues are located through hidden request/key markers;
- an existing marked Issue may be reused even after it was closed;
- duplicate markers fail closed;
- exactly one matching open devflow `[REPO]` Control may be reused;
- duplicate/conflicting Controls fail closed;
- existing README/spec seed files are not overwritten merely because the request is retried.

Do not resolve identity collisions by deleting or overwriting resources automatically.

## 6. Failure recovery

Request comments use:

```text
Repository-Bootstrap-State: FAILED
Stage: <stage>
Safe-Retry: yes | after-human-decision
Created/Observed Resources:
- ...
Failure: ...
Next-Action: ...
```

`Safe-Retry: yes` means the same request can be edited/reopened/reprocessed after the transient cause is resolved.

`Safe-Retry: after-human-decision` means identity, credential, security or ambiguous ownership must be reconciled first.

Never create a second replacement repository merely because a partial bootstrap run failed.

## 7. Credential Human Gate

Actual repository creation requires `REPOSITORY_BOOTSTRAP_TOKEN` because the normal workflow `GITHUB_TOKEN` is repository-scoped and is not the account-wide repository-creation authority.

Creating, rotating, replacing or storing this token; creating/configuring a GitHub App/private key; or changing account/repository permissions is a **Human Gate**. Obtain explicit user authorization before performing any such credential/session/permission operation.

The implementation and tests may be merged without setting this secret. Until an approved credential is configured, valid requests will stop with a recoverable credential blocker instead of bypassing the boundary.

Never put a token in:

- Bootstrap Request bodies;
- repository files;
- logs;
- Issue comments;
- test fixtures.

## 8. After successful bootstrap

A successful request records:

- repository URL;
- accepted initial/default-branch SHA;
- initial owner Issue URLs;
- devflow Repository Control URL.

Continue work from the new repository's own canonical entry points and owner Issue(s). The `[REPO CREATE]` Issue is then provenance/history, not the continuing technical specification.

The long-lived cross-repository entry becomes:

```text
[REPO] <repository-name>
```

in devflow.

## 9. Real E2E boundary

Do not claim operational repository creation is verified from unit/static tests alone.

After an approved least-privilege credential is configured, run one bounded real E2E using a clearly test-scoped **private** repository request. Verify:

1. trusted request validation;
2. repository creation;
3. bootstrap provenance;
4. README/spec seed;
5. initial Issue creation;
6. actual SHA capture;
7. exactly one Repository Control;
8. terminal request links;
9. retry does not duplicate any resource.

Do not automatically delete the E2E repository. Repository deletion is destructive and remains separately confirmation-gated.

## 10. Operator diagnostics

Primary evidence order:

1. `[REPO CREATE]` request body/comments;
2. Repository Bootstrap workflow run and exact job logs;
3. target `.github/repository-bootstrap.json`;
4. target owner Issues;
5. devflow `[REPO]` Control;
6. target default-branch head.

If these disagree, fail closed and reconcile observed identity before further mutation.
