# Public-only main protection in Repository Bootstrap

## Goal

Implement devflow #1058 in the existing deterministic Repository Bootstrap executor. New managed-repository request emitters declare the policy; new Public repositories receive the accepted #78 classic branch-protection baseline and an API readback. Private repositories are explicitly not applicable. Requests without the new policy retain historical v1 retry behavior.

## Boundaries

- Reuse the existing GitHub API adapter, Bootstrap request, provenance, and retry path.
- Use the existing bootstrap credential only. Do not change tokens, secrets, Apps, Actions permissions, or repository permissions.
- Never overwrite a divergent existing branch-protection policy.
- Do not create a Public fixture, mutate existing repositories in bulk, or perform #1050 writer E2E / #386 rollout.
- The generic mechanism lifecycle principle is already present in the Issue Manual and Cross-Repository Control spec; preserve it and avoid duplicate policy text.

## Design

1. Add optional `bootstrap.main_protection: public-only-v1`. Omission is the legacy compatibility boundary. Current new managed-repository instructions/examples require the marker.
2. After identity/provenance validation and seed writes, re-read repository visibility and the default branch. For a marked Private repository, make no protection API calls and report `NOT_APPLICABLE/PRIVATE_REPOSITORY`. For an unmarked request, make no protection API calls and report legacy policy as not applicable.
3. For a marked Public repository whose default branch is `main`, GET classic protection. If absent, PUT the #78 baseline (required PR, zero approvals, universal `verify` check, resolved conversations, admin enforcement, no bypass, no force-push, no deletion), then GET and verify. If present and exact, accept without writing. If divergent or identity/branch readback is uncertain, fail closed with stage and resources; never replace it.
4. Expose only narrow branch-protection GET/PUT methods on `GitHubApi`. Preserve credential-safe diagnostics. Classify authorization/configuration failures as `after-human-decision`; transient transport/server failures remain safely retryable.
5. Update request schema, normative spec, operations guide, and agent/request-emitter instructions. Keep all #1050 lifecycle and #386 rollout ownership separate.

## Test-first checkpoints

1. Add RED tests for policy normalization/legacy omission, Public apply and readback, Private N/A with zero protection calls, no overwrite on mismatch, permission/API failure status, retry after partial success, and adapter endpoint/payload.
2. Implement the request field and API adapter, then Public/Private/legacy executor behavior.
3. Run focused tests, then the full test suite; review changed files and permission/workflow diff.
4. Push branch, create PR, verify exact-head formal review and required CI, then update #1058 with evidence and the separate live Public E2E Human Gate.

## Acceptance boundary

Local tests prove behavior and idempotence. They do not prove the existing bootstrap token has Administration:write or that a real new Public repository is protected. Keep #1058 open until the authorized live Public bootstrap readback is completed.
