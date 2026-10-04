# Repository Projection

Status: Canonical specification
Milestone owner: devflow#332
Roadmap: devflow#326
Policy source: devflow#325

## 1. Purpose

Repository Projection is a devflow-owned deterministic **read model** for repository-local work.

It exists to remove manual duplication between owning-repository Issues and devflow Repository Controls without creating:
- a second task database;
- a scheduler;
- a runtime claim authority;
- a Project-to-Issue reverse synchronization path.

Canonical authority remains:
1. owning repository Issues / Work Orders / requirements / specs / Current State for repository-local truth;
2. devflow Repository Controls for cross-repository/lifecycle facts that are not safely derivable locally;
3. PR/tests/CI for implementation evidence;
4. GitHub Project as display-only.

M1 is read-only shadow projection. Persisted/write projection belongs to M2 and is not authorized by this specification section alone.

## 2. Repository-local Issue metadata block

A repository-local Issue may contain at most one machine-owned metadata block:

```text
<!-- DEVFLOW_ISSUE_METADATA_V1_BEGIN -->
```json
{
  "schema_version": 1,
  "record_role": "TASK",
  "type": "BUG",
  "work_status": "READY_FOR_IMPLEMENTATION",
  "scope_ready": true,
  "requires_user_confirmation": false,
  "external_wait": false,
  "priority": "P1",
  "risk": "HIGH",
  "blocked_by": [],
  "work_order_ref": null,
  "implementation_ref": null,
  "next_action_tag": "IMPLEMENT"
}
```
<!-- DEVFLOW_ISSUE_METADATA_V1_END -->
```

Markers:
- `<!-- DEVFLOW_ISSUE_METADATA_V1_BEGIN -->`
- `<!-- DEVFLOW_ISSUE_METADATA_V1_END -->`

Rules:
- zero blocks is valid legacy state;
- exactly one begin and one end marker are required when present;
- duplicate, missing-pair, out-of-order, empty, malformed JSON, unsupported schema or malformed field values fail closed;
- unknown fields fail closed in v1;
- the block does not duplicate GitHub-native Issue number/URL/title/open-state/created_at/updated_at/author/assignee.

Machine schema reference:
- `docs/spec/schemas/repository-issue-metadata.v1.schema.json`

Runtime enum authority:
- `type`, `work_status`, `priority`, and `risk` are validated against the live checked-in `.devflow/WORKFLOW.yaml` through `tools/workflow_contract.py`;
- the JSON schema intentionally does not duplicate those workflow enum lists.

## 3. record_role

Allowed v1 roles:

- `TASK` — executable owning work item;
- `TRACKER` — roadmap/progress/parent aggregation;
- `REFERENCE` — specification/research/audit/decision/reference record;
- `SYSTEM` — machine/control/system record.

An open Issue is not a TASK merely because it is open.

A `TASK` requires:
- `type`;
- `work_status`;
- `scope_ready`;
- `requires_user_confirmation`;
- `external_wait`.

Optional fields do not become authoritative merely because they exist. They are used only according to their owning semantics.

## 4. Legacy and invalid metadata

Issues without the machine block remain visible.

Title-based classification may produce a non-authoritative `LEGACY_HINT`, but that hint alone cannot:
- make an Issue actionable;
- publish execution supply;
- satisfy auto-advance;
- bypass Human/security/reviewer gates;
- authorize mutation.

Malformed machine metadata is `INVALID_MACHINE` and remains non-actionable with diagnostics.

Do not bulk-backfill historical Issues only for format conformity. Add/fix metadata lazily when a materially active Issue is edited and the owning repository accepts the metadata contract.

## 5. M1 read model

The pure repository projection returns:
- `schema_version: 1`;
- `authority: SHADOW_READ_ONLY`;
- repository identity;
- observation time;
- source status/error;
- per-Issue classification;
- open Issue count;
- machine TASK count;
- legacy/unclassified count;
- invalid-machine count;
- machine-only counts by canonical type;
- newest open Issue;
- most recently active open Issue;
- actionable refs;
- blocked refs;
- external-wait refs;
- Human-gated refs.

Newest-created and most-recently-updated are separate concepts.

M1 does not write:
- Repository Controls;
- GitHub Project fields;
- owning Issues;
- Repo Monitor state;
- execution supply or runtime claims.

## 6. Actionability boundary

In M1, `actionable` is a **shadow read classification**, not mutation authority.

A machine `TASK` can be projected as actionable only when all are explicit:
- Issue is open;
- `scope_ready = true`;
- `requires_user_confirmation = false`;
- `external_wait = false`;
- `work_status` is one of the accepted implementation-ready/active states defined by the projection implementation.

Legacy hints and invalid metadata are never actionable.

Any future use of the projection for mutation gates requires a separate accepted authority decision and does not follow automatically from this M1 field.

## 7. Source/freshness semantics

Live MCP reads use direct GitHub Issue API reads through the existing devflow reader.

M1 source state:
- `OK` — exact live source read succeeded;
- `ERROR` — source read failed and no task/action classification may be inferred;
- `UNKNOWN` — source state cannot be established and no task/action classification may be inferred.

A non-OK source returns an explicit safe empty projection plus the source error.

Persisted stale/last-known-good semantics belong to M2.

## 8. MCP and portfolio boundary

M1 adds read-only repository and portfolio projection queries.

They:
- reuse one pure projection implementation;
- read current owning-repository Issues;
- expose source/freshness failures explicitly;
- do not become scheduler/runtime authority;
- do not write canonical state.

M2 may later add a bounded machine-owned cached projection with digest/generation/freshness semantics after M1 evidence is accepted.

## 9. External consumer boundary

Repo Monitor and other external consumers must not independently reimplement bootstrap provenance or repository-work classification.

Repo Monitor migration remains owned by `kinotch-repo-monitor#46` and waits for the M2 devflow-owned machine projection transport.

## 10. Safety

Unchanged:
- GitHub Project is display-only;
- execution-coordinator remains runtime claim authority;
- no synthetic task creation;
- no per-repository sync workflow fleet;
- no reverse Project sync;
- release/deploy/publication/security/destructive boundaries remain Human-gated.
