# GPT liveness F7 — central KAEP dispatch dry-run

**Owner:** [devflow #550](https://github.com/kinoko34077/devflow/issues/550). Parent protocol [#516](https://github.com/kinoko34077/devflow/issues/516), accepted F4 PING/ANSWER pilot [#519](https://github.com/kinoko34077/devflow/issues/519), accepted KAEP producer [#542](https://github.com/kinoko34077/devflow/issues/542), F6 read-only admission [#545](https://github.com/kinoko34077/devflow/issues/545).

## Contract and effects

The native module `tools/gpt_liveness_dispatch_preview.py` composes only already accepted read-only APIs: F6 explicit target manifest/Issue snapshot admission, F5 exact GitHub comment validation, and F4 existing KAEP liveness `plan`. No second KAEP codec, no network write, no Issue comment POST, no new workflow/schedule, no credentials, no runtime Claim/Lease mutation, no model wake or provider launch.

**The output is an advisory preview, never an execution grant.** The fields `read_only=true`, `simulation_only=true`, `deployment_authorized=false`, `any_current_gpt_alive_proven=false`, `claim_authority=false` are invariant for all outputs. Any `would_ping_if_authorized=true` is **not** `may_send=true` and does not prove that GPT is currently running. A dummy nonce is used internally to exercise the idempotency planner, but no generated PING payload/nonce is exposed to callers and no comment is posted.

## Invocation

Default empty manifest in `docs/spec/gpt_liveness_fleet_allowlist.sample.json` deliberately produces zero targets. For a **single bounded historical live GET example**, create a temporary manifest (do not commit an active registration):

```json
{"schema":"gpt-liveness-fleet-plan.v0.1","targets":["kinoko34077/devflow#519"]}
```

Then call:

```sh
python3 -m tools.gpt_liveness_dispatch_preview --manifest /path/to/manifest.json --live
```

This calls only `gh api GET` for allowlisted exact owning Issues; it reads GitHub Issue comments **only for active** enrollments. Closed/expired/disabled/long-running enrollment returns a suppressed state. For isolated deterministic fixtures use `--fixture /path/to/data.json` with `{"snapshots":{"owner/repo#519":{...}},"pages":{"owner/repo#519":"[[...raw GitHub comment JSON ...]]"}}`. Current supported preview count maximum is 12 exact targets; no discovery of arbitrary public repos.

Malformed/duplicate targets, Issue identity mismatches, malicious comment source identity, duplicate registration, already-PINGed 5min bucket, expired/disabled owner, and 3 unanswered probes fail closed or yield `would_ping_if_authorized=false`. The body is read from the owning Issue, not public comments. When an active target is admitted, all supplied comment pages go through existing KAEP strict parser; attacker-authored PING does not suppress authorized bot PING planning.

## Operational gate and known limits

The former hardcoded five-minute pilot was **archived** in [devflow #544](https://github.com/kinoko34077/devflow/issues/544), [PR #546](https://github.com/kinoko34077/devflow/pull/546): `.github/workflows/gpt-liveness-pilot.yml` has only `workflow_dispatch`, no recurrence or Issue fanout. The F6 docs originally describing an active 5-minute pilot schedule are historical and superseded. F7 does not restart it.

A future effectful central scheduler must be separately admitted with least-privilege repository/Issue authorization, trusted enrollment origin, server-side challenge generation, safe concurrency/idempotency, writable token bounds, rollback and costs. A preview must **never** be blindly mapped into an Issues POST. GitHub Actions scheduled triggers cannot interrupt ChatGPT; a model-mediated tool ANSWER remains weaker than a cryptographic model identity attestation. Runtime Claim takeover is a different authority.

## Verification

```sh
python3 -m unittest tests.test_gpt_liveness_dispatch_preview -v
```

Run repository Required CI and, where available, a native GitHub read-only #519 smoke. Neither can prove current GPT liveness from historical answers. Full fleet activation is **not** part of F7 acceptance.
