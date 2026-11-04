# Repository Bootstrap feature route

This entry is an index-only route for the repository-bootstrap feature. The
manifest's `source_ref`, `3dce241581dd8dc931d2aafaef3af546ff522845`,
identifies the audited source snapshot for the indexed paths, not the live
`main` head.

For current behavior or status, read the live Repository Control and current
`main` head, then recheck the linked sources at that revision. The normative
contract remains in the linked devflow documents and source files.

This route does not emit a bootstrap request, create or provision a repository,
grant credentials or permissions, bypass a Human Gate, or become runtime
authority. Re-read live Repository Control and the owning Issue before any
effectful operation. Invalid, incomplete, untrusted, or stale evidence remains
fail closed.

## request

Use when a user explicitly requests a new repository from an established
context. Start with the bootstrap request contract and its request-path test;
the request is still a proposal subject to live identity, ownership, and
approval checks.

- Documents: `docs/spec/REPOSITORY_BOOTSTRAP.md`,
  `docs/operations/REPOSITORY_BOOTSTRAP.md`
- Code: `scripts/repository_bootstrap.py`
- Tests: `tests/test_repository_bootstrap.py`

## validation

Use when reviewing schema, trust, identity, visibility, or repository-boundary
validation. Keep schema validation separate from authorization and preserve the
fail-closed behavior for missing or contradictory evidence.

- Documents: `docs/spec/REPOSITORY_BOOTSTRAP.md`,
  `schemas/repository-bootstrap.v1.schema.json`
- Code: `tools/repository_bootstrap.py`
- Tests: `tests/test_repository_bootstrap_policy.py`,
  `tests/test_repository_bootstrap_security_boundaries.py`

## provisioning

Use only for an already authorized bootstrap or recovery flow. Provisioning is
an effectful operation with its own ownership, credential, permission, and
Human Gate requirements; this index does not grant any of them.

- Documents: `docs/spec/REPOSITORY_BOOTSTRAP.md`,
  `docs/operations/REPOSITORY_BOOTSTRAP.md`
- Code: `tools/repository_bootstrap.py`, `scripts/repository_bootstrap.py`
- Tests: `tests/test_repository_bootstrap_executor.py`,
  `tests/test_repository_bootstrap_repo_native_dispatch.py`

## control-trust

Use when reading bootstrap-derived Repository Control or deciding whether
derived metadata may be trusted. Control remains the cross-repository
operational authority, while the owning repository remains the technical
authority; a local bootstrap result cannot replace live control evidence.

- Documents: `docs/spec/REPOSITORY_BOOTSTRAP.md`,
  `docs/operations/DEVFLOW_MCP.md`
- Code: `tools/devflow_mcp_core.py`
- Tests: `tests/test_devflow_mcp_core.py`

## workflow

Use when auditing event triggers, secret fencing, or workflow-level safety
boundaries. Workflow execution must preserve the existing read-only and
Human Gate boundaries and must not be inferred from an index entry.

- Documents: `docs/operations/REPOSITORY_BOOTSTRAP.md`
- Code: `.github/workflows/repository-bootstrap.yml`
- Tests: `tests/test_repository_bootstrap_workflow.py`


