# F5E KAEP liveness evidence producer (read-only)

**Source of truth:** [devflow #542](https://github.com/kinoko34077/devflow/issues/542), under [devflow #516](https://github.com/kinoko34077/devflow/issues/516) and the existing KAEP v0.2 codec. **Downstream:** [execution-coordinator #138](https://github.com/kinoko34077/execution-coordinator/issues/138), merged readonly query PR #139.

## Goal
Translate actual GitHub REST Issue-comment KAEP PING/ANSWER evidence to the exact optional `gpt-liveness-observation.v1` downstream contract. No second KAEP decoder, no GitHub POST, no token administration, no executor Claim mutation, and no automatic ChatGPT wake.

The upstream checks complete GitHub comment pages using `tools.kaep_inbox_reader`, then validates exact comment issue identity, canonical comment URL, GitHub actor, server-created UTC timestamp, KAEP correlation, PING nonce/session/turn, challenge expiry and matching `ANSWER`. Invalid/forged reply never turns into model evidence. Valid `LONG_RUNNING` responses project a finite deadline; unanswered requests project `NO_RESPONSE`, not dead.

The output is still **producer-reported**. Only a trusted execution context can know that the supplied REST data came from GitHub; a copied JSON file cannot cryptographically prove GPT's model identity. The consumer therefore reports `UNATTESTED_UPSTREAM_REPORT` and `gpt_currently_alive_proven=false`.

## Native commands

From the devflow checkout in a supported authorized environment with `gh api` read access:

```sh
python -m tools.gpt_liveness_evidence \
  --repository kinoko34077/devflow --issue 519 \
  --session-id session_pilot20261014_1755 \
  --turn-id turn_pilot20261014_1755 \
  --expected-reply-actor kinoko34077 > liveness.json
```

Then, from execution-coordinator checkout in the **same authorized pipeline or via an explicitly provided local file**:

```sh
PYTHONPATH=src python -m execution_coordinator.query get_liveness \
  --evidence-json liveness.json --expected-mailbox kinoko34077/devflow#519
```

The historical 2026-10-14 17:58Z ANSWER should now project as `HISTORICAL_EVIDENCE`, not currently-alive GPT. Do not make the producer emit `model_identity_verified:true` or any Claim authority.

An offline fixture may be supplied using `--offline-pages path.json`, but such fixture use is *test only*, not live GitHub E2E proof.

## Pending evidence
- Native unit/CI and current-head review for the producer.
- Live **read-only** upstream command running on the accepted main, exact input/output readback.
- Native execution-coordinator consumer invocation with that exact producer output and expected historical classification; no new GitHub comment or agent launch.
- Cost-aware fleet scheduling, strong provider identity or out-of-turn wake remain separate future changes; this adapter does not change them.
