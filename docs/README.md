# Documentation entrypoint

Use the smallest route that matches the task.

1. For feature work, start with [`../features/README.md`](../features/README.md)
   and follow one feature route. The route is an index only; live Control,
   Issues, PRs, CI, and current specifications remain authoritative.
2. For cross-cutting policy or repository work, start with [`../AGENTS.md`](../AGENTS.md)
   and the live `devflow#734` entrypoint before reading a category below.
3. Read only the linked current contract, procedure, code, or test needed for
   the task. Do not treat a directory name, date, or historical note as proof
   of current validity.

## Category fallback

These categories are a fallback for documents that are not yet represented by
a feature route. They describe placement, not authority.

| Directory | Use for | Entry |
|---|---|---|
| [`spec/`](spec/) | Current cross-repository contracts and schemas | [`spec/README.md`](spec/README.md) |
| [`operations/`](operations/) | Runbooks and operational procedures | Read the procedure named by the current Issue or Control |
| [`decisions/`](decisions/) | Durable design decisions that affect later work | [`decisions/README.md`](decisions/README.md) |
| [`project/`](project/) | Display-only GitHub Project synchronization material | [`PROJECT_SYNC.md`](project/PROJECT_SYNC.md) |
| [`superpowers/`](superpowers/) | Dated plans, designs, and bounded execution records | Read only when the owning Issue links them |
| [`mobile-actions/`](mobile-actions/) | Existing read-only mobile/public presentation surface | [`README.md`](mobile-actions/README.md) |

## Authority boundary

This page is navigation metadata. It does not create a new specification,
current-state cache, work assignment, permission, review result, merge grant,
or publication authority. History remains in its existing Issue, PR, commit,
CI, or decision record; practical rules belong to their current owner.
