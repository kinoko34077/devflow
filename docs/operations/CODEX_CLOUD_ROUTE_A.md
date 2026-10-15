# Codex Cloud Route A — owner-PC CLI preflight

Status: read-only diagnostic only. Owner: devflow #597; parent #541.

## Observed 2026-10-16

- Authorized KiNoTch. Windows PC online with gh/Git/Python/Node. Codex CLI v0.155.1 exists as a shim under the owner's AppData\Roaming\npm path, but was not on the current PowerShell PATH.
- Explicit codex.cmd --version and codex cloud exec --help succeeded. The official CLI supports cloud exec --env ENV_ID, but it was NOT invoked.
- codex cloud list --json exited 0 and returned zero tasks in the devflow checkout. Task-list access is NOT environment discovery, dispatch permission, Cloud task creation or Issue write authority.
- Current/legacy environment catalog mismatch: https://github.com/openai/codex/issues/50182 . Do not infer a new published Cloud environment is visible to this CLI.

## Safe preflight (no installation or credential changes)

From a locally authorized devflow repository checkout, set two operator-verified local paths, then run:

    python -m tools.codex_cloud_route_probe --cli "C:\Users\kinok\AppData\Roaming\npm\codex.cmd" --checkout "C:\Users\kinok\Documents\Programs\devflow-main"

The module invokes only codex --version and codex cloud list --json without a shell, with bounded output/timeouts. It returns status, CLI version, task count only; it never prints task details or authentication secrets. A status of TASK_LIST_ACCESSIBLE_ONLY does NOT authorize cloud exec.

## Next gate (not yet accepted)

1. Identify a documented native CLI environment picker that actually lists the existing published project Cloud environment; distinguish legacy vs current catalog without guessing private endpoint URLs or IDs.
2. Ensure the target repository/branch and one fixed innocuous task are explicitly permitted, using current trusted identity and task-provenance evidence.
3. Only then submit exactly one official codex cloud exec attempt with an authorized environment. Verify task ID, actual Cloud task, output and zero duplicates. No speculative task submission merely to test version compatibility.
4. Treat native Codex Cloud Issue POST under devflow #570 as a separate authorization and test, not a consequence of this read-only probe.
5. PC Worker with outbound-polling independently of Actions is a distinct F3 slice; do not equate GitHub-hosted self-runner or this CLI probe with an operational replacement.

Payment, paid plans, permissions, Cloud/PC configuration and resident process changes remain Human-gated under #541; no JPY 2,000 budget is inherited.
