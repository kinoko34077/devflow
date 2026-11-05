# Feature Route Catalog

Use this catalog to enter the smallest relevant documentation, implementation,
and test surface for a feature. Each route is index-only: it points to existing
owners and does not duplicate normative contracts or live operational state.
Each manifest records the exact source snapshot used for its path-existence
check; a snapshot is evidence for the index, not a replacement for live state.

| Feature | Start here | Use when |
|---|---|---|
| [KAEP](kaep/README.md) | `kaep/` | Inbox, discovery, send, reply, and source-route work |
| [Devflow read/MCP](devflow-read/README.md) | `devflow-read/` | Bootstrap, work view, Inbox, workspace, or advisory assessment |
| [Repository Bootstrap](repository-bootstrap/README.md) | `repository-bootstrap/` | Repository creation and bootstrap evidence |
| [Task Checkpoint Cursor](task-checkpoint-cursor/README.md) | `task-checkpoint-cursor/` | Resume frontier, cursor, or checkpoint reconciliation |
| [Chat Worker](chat-worker/README.md) | `chat-worker/` | Existing-worker bootstrap, profile, or fixture boundaries |
| [Reconciliation / Projection](reconciliation-projection/README.md) | `reconciliation-projection/` | Evidence reconciliation, publication, or repository projection |
| [Project Sync](project-sync/README.md) | `project-sync/` | Canonical Issue/Control to display-only Project synchronization |
| [Maintenance](maintenance/README.md) | `maintenance/` | Standing maintenance selection, audit, Ledger, or manual workflow |
| [GPT Liveness](gpt-liveness/README.md) | `gpt-liveness/` | Opt-in liveness, identity/routing, or evidence boundaries |
| [Generated Artifact](generated-artifact/README.md) | `generated-artifact/` | Verified artifact contract, pilot, or bounded writer admission |
| [Cross-Repository Core](cross-repository-core/README.md) | `cross-repository-core/` | Shared bootstrap, Issue/Goal, handoff, or semantic Control work |

Read the route README only for navigation. Follow its linked specification,
schema, code, tests, and live owner records for actual behavior and current
state. Unknown, stale, partial, or filtered observations remain unknown; this
catalog never authorizes execution, writes, merges, credentials, or publication.
