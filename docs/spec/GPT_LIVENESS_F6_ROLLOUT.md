# GPT liveness F6 — central read-only admission planning

**Owner:** [devflow #545](https://github.com/kinoko34077/devflow/issues/545). F4 pilot accepted [#519](https://github.com/kinoko34077/devflow/issues/519); F5 producer accepted [#542](https://github.com/kinoko34077/devflow/issues/542) and consumer [execution-coordinator #138](https://github.com/kinoko34077/execution-coordinator/issues/138). Canonical cross-repository requirements [#516](https://github.com/kinoko34077/devflow/issues/516).

## Purpose and separation

Historical rationale: the original F4 pilot had a best-effort 5-minute GitHub Actions `schedule`, **even when no target was enrolled**. It did not POST without enrollment but could consume idle runner invocations. **Current state:** [devflow #544](https://github.com/kinoko34077/devflow/issues/544) / merged PR #546 archived that pilot and removed its recurring schedule and Issue-edit fanout; the workflow is now **manual `workflow_dispatch` only**. Replicating a future independently scheduled workflow into every repository would multiply idle executions; scheduled GitHub Actions cannot force a paused interactive ChatGPT to answer.

F6 first provides a **purely advisory allowlisted fleet planning layer**. No fleet sender, Issue POST, duplicate KAEP decoder, runtime Claim/Lease mutation, permission change, cloud service, browser/ChatGPT wake, or persistent task database is created. The authoritative Session/Turn enrollment remains in the **owning Issue body**, parsed by existing `gpt_liveness_pilot.enrollment()`. The allowlist is owner-supplied *observation scope only*, not authorization to send. The upstream producer remains `tools/gpt_liveness_evidence.py`; coordinator `get_liveness` remains a read-only consumer.

## CLI and default-empty scope

An explicit manifest containing only exact Issue identifiers is required:

```json
{"schema":"gpt-liveness-fleet-plan.v0.1","targets":[]}
```

Example with a previously accepted single test target: `"targets":["kinoko34077/devflow#519"]`. Adding a target to this JSON **does not enable any monitoring**. This prototype does not load a default fleet or scan arbitrary public Issues. It accepts at most 12 distinct targets. All exact target records must be supplied: fail closed on missing, duplicate, malformed, wrong-repository or stale registrations. Non-open/disabled/expired registrations are non-active.

Read-only live inspection, using an already authorized `gh api GET` identity:

```sh
python3 -m tools.gpt_liveness_fleet_plan --manifest /path/to/allowlist.json --live
```

Deterministic offline inspection:

```sh
python3 -m tools.gpt_liveness_fleet_plan --manifest /path/to/allowlist.json \
  --snapshots /path/to/issue-snapshots.json
```

The snapshot JSON maps each exact target to a four-field object: `{"repository":"owner/repo","number":519,"state":"closed","body":"..."}`. Neither snapshots nor allowlists confer GitHub permission. **All output is `projection_only=true`, `read_only=true`, `deployment_authorized=false`, `any_current_gpt_alive_proven=false`, `claim_authority=false`**. A positive registration is called `ACTIVE_ENROLLMENT_REPORTED`, never `GPT_ALIVE`. Long-running registration is `LONG_RUNNING_DECLARED`, not a Claim renewal.

## Cost, scheduling and rollout decision

Five-minute cron has **288 nominal triggers/day and 8,640 nominal triggers/30 days/workflow**. Per-repo replication multiplies triggers by N independent repository workflows. A single central monitor stays at the 8,640 nominal trigger *opportunities* per 30 days, subject to GitHub scheduling delays/drops. This is **not** a measured run count, billed runner time, dollar cost, guaranteed polling SLA or provider-model liveness. Actual GitHub event and minutes accounting must be sampled before adoption.

Choose between:
- One central authorized GitHub scheduler + explicit finite enrollment (keeps idle invocations but avoids per-repo duplication).
- A centrally deployed low-cost scheduling gateway (e.g. Cloudflare) **only via separately authorized credentials/service deployment**.
- A provider/browser host adapter when actual ChatGPT-turn observation is needed; this is a distinct security/freshness gate.

F6A–C implement the **non-effectful planning side only**. No fleet-side PING is activated, no new repo token is registered and no existing scheduler is disabled by this plan. Before moving to F6E actual deployment, require measurable idle/active actions accounting, least-privilege cross-repo access, Source identity and correct stale/no-response semantics, rollback plan, and explicit approval of any credential/service/release changes.

## Live read-only historical Issue smoke (no fleet deployment)

`.github/workflows/gpt-liveness-fleet-smoke.yml` runs **only** for PR changes to the F6 planner/test/workflow files and for the workflow/planner's initial main push. It has `contents:read` and `issues:read` permissions only, a 3-minute upper job bound, and **no schedule, POST, Issue edit, or Claim operation**. It reads the real already-closed historical devflow #519 Issue with an explicit one-target ephemeral allowlist and verifies `CLOSED_OR_NO_ENROLLMENT`, `deployment_authorized=false`, `gpt_alive_proven=false` and the nominal 8,640 opportunities/30-day arithmetic. This is **a real GitHub GET smoke**, not a successful active-worker monitoring trial or a credential/rollout approval.

## Tests

```sh
python3 -m unittest tests.test_gpt_liveness_fleet_plan -v
```

Covers empty manifest, issue state, expired/disabled, bounded long-running, exact mailbox identity, duplicate entries/registrations, target count/cost multiplication, read-only GitHub command construction, and non-authority of every classification. This does not replace a future live authenticated E2E sender pilot.
