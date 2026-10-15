# Shared Operation Safety — Live Mutation-Path Inventory (M1 / First M2 Adopter)

Status: bounded implementation and evidence record, not an account-wide fleet certification  
Owner: [devflow #487](https://github.com/kinoko34077/devflow/issues/487) / [Work Order #614](https://github.com/kinoko34077/devflow/issues/614)  
Evidence snapshot: live `kinoko34077/devflow` main before branch `fb1f353ddf5438407a5e806682a4b37611cf346d` (2026-10-16). Refresh actual HEAD and owning Issue for every effect.

## M1 — Verified devflow code paths, not exhaustive across other repos

| Mutation kind | Concrete in-repo entrypoint | Accepted/current safety | Remaining limits and owner | M2 decision |
| --- | --- | --- | --- | --- |
| PR guarded merge | `tools/development_reconciler.execute_merge` | Observes open PR and exact expected HEAD; calls native `merge_pr` with expected HEAD; independently reads merged PR back. Review/CI admission is separate. | Does not confer generic authority or replace GitHub/owner review. PR-head compare enforced by merge API rather than arbitrary Issue PATCH. | **Keep**; do not fork |
| Generated artifact writeback | `tools/generated_artifact_rollout_writer.py`, `tools/generated_artifact_rollout_testapp_write.py` | #465 producer/run/manifest/recipe checks; #474 testapp scratch real write, stale-head denial, exact-head CI and forward-only rollback verified. | One same-receipt `COMMITTED → NO_OP_REPLAY` positive workflow run missing; no fleet permission. #474 owns. | **HOLD on #474 scope**; no second writer |
| Pure bounded Issue metadata plan | `tools/operation_issue_metadata_preflight.py` | Exact repository/issue/open timestamp/body observation, unique anchored `###` section, stale/no-op/postread classification. | Non-effectful by design; no GitHub-side atomic expected-old-body CAS. #487 owns semantics. | **Reuse strict observation in a real existing writer** |
| **Public Repository Control Issue update** | `scripts/maintenance_audit.py::_SyncCheckGitHubTransport.update_control_body → update_issue_body`; `tools/maintenance_sync_check.execute_sync_check` | Manual gated `--apply` and caller admission; GET body SHA freshness; only bounded candidate transition; caller independently checks post-write body. Other maintenance supply/withdraw flows also call Control writer. | Pre-existing last GET checked only body digest, not Control title/trust/open/owner repository if changed independently of body. GitHub Issue PATCH remains weak-consistency; high-impact concurrent edits require serialized or native conditional effect. | **M2 selected**: reuse #487 `snapshot_issue` and validate live Control title/trust/open/identity and desired body repository before *existing* PATCH; skip exact NO_OP |
| Maintenance Ledger Issue update and comment | Same `scripts/maintenance_audit.py` `update_issue_body`, `post_issue_comment` | Separate Ledger run/attempt guards and immediate postread in its owner; not a source-of-truth replacement. | GitHub Issue PATCH and comment POST have no verified server-side expected-old-body/once CAS here; SMC #588 is concurrently active. | **Preserve** Ledger behavior, do not touch #588 writer |
| Owner-only fixed read-only Issue comment dispatch | `tools/safe_dispatch_*`, devflow #413 | Fixed allowlisted read-only commands and proven native GitHub issue-comment trigger. | This is not permission for arbitrary write or external workflow dispatch. | **Keep** |
| Central backend-neutral gateway and queue | `tools/central_execution_gateway.py`, `tools/central_gateway_queue.py`, #541 / #577 / F3C #610 | Fake-only trusted catalog/claims prototype, SQLite job-queue CAS; separate independent CPU/loopback experimental proofs. | Queue-CAS does **not** serialize actual GitHub Issue PATCH. Actual trusted independent host/runtime remains separately gated. | **No duplicate executor** |

## M2 — Named real existing Public adoption

The selected adopter already performs authenticated GitHub GET and REST PATCH on devflow Repository Control metadata. Its last live GET is the right place to call #487's existing `snapshot_issue` for **identity/open/timestamp/body validation**, plus canonical Control title, trusted original Issue author association, `## Repository` ownership and desired postbody identity. This guards against a Control becoming closed/renamed/untrusted while retaining the same body digest. The caller's already accepted body-digest freshness/Review/Human gates and postwrite readback remain intact. Identical desired body is a native **NO_OP**, not a redundant PATCH.

Importantly, `snapshot_issue` here is read-only data checking, **not** actor authentication; authentication is from `get_issue`'s existing GitHub transport. `READY` never authorizes a write, and a final GET and PATCH can still race. Do not claim full GitHub Issue write serializability, universal runtime enforcement, or permission expansion from M2.

## M3 — Targeted validation and global replan

Negative probes on the existing transport include closed/retitled Control, wrong canonical target/issue number, untrusted original author, changed body/desired owner, invalid timestamp, stale old digest, duplicate no-op, ambiguous network error and credentials redaction. Valid existing Control update emits precisely one native PATCH. The unrelated Ledger update remains on its existing path.

M4 #474 same-receipt live dispatch and M5 gateway integration are **separately owned**. This child does not install workflow callers, reconfigure permissions/credentials or invoke live scratch writes. M6 requires named repo owner admission; no opt-in quota or broad fleet enablement. Re-evaluate after M2 merged and verified rather than continue speculatively.
