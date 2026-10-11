# Native-first GitHub dispatch fallback — decision contract (offline only)

Owner: [devflow #448](https://github.com/kinoko34077/devflow/issues/448), parent [#413](https://github.com/kinoko34077/devflow/issues/413). User decision 2026-10-12: **normal workflows and Public repositories use the connected GitHub app; fallback exists only for operations the app lacks or when Private GitHub-hosted runner free capacity is exhausted**.

## Delimit responsibilities before picking a provider

| Concern | Default | Fallback trigger | What a fallback must NOT imply |
| --- | --- | --- | --- |
| GitHub API data / PR / Issues | Existing connected GitHub typed tools, existing owner authorization | Required **exact** operation not offered or denied by actual connection | An external Cloudflare/Deno service has no inherited GitHub token, consent, scopes or user identity |
| GitHub Actions fixed reviewed operation | Supported repo-native fixed trigger + standard GitHub-hosted runner when runnable | Verified Private hosted-minute/budget exhaustion | Missing general `workflow_dispatch` is NOT cured by changing the runner |
| Compute outside hosted Actions | None by default | Private hosted runner exhausted, or an operation cannot run under Actions | Self-hosted is not free operationally, has persistence/security risks, and cannot bypass **all Actions disabled** |
| Reliable one-time dispatch | Existing execution-coordinator#3 claim/lease and #384 verified writer when applicable | Genuine missing authorized transport | Never add a parallel claim queue, silently weaken exact SHA, or treat an Issue comment as privileged authorization |

### Evidence and zero-base decision order

1. **Does the current installed GitHub connection support this exact operation?** Inventory actual typed tools or invoke allowed read-only metadata; do not infer broad capabilities from a connector name. If supported, stay native. The existing connector can read Private canary metadata/HEAD but does not expose general workflow_dispatch.
2. **Is the requested operation API-only or does it need real process/OS compute?** An API-only operation should NEVER consume runner minutes merely because a workflow exists.
3. **For fixed Actions:** prove a trusted trigger for exactly that versioned/pinned operation; `#395` seeded fixed /kinotch status Public pilot is **not general-purpose command execution**. GitHub REST `workflow_dispatch` needs `Actions:write` and a separately authorized trusted caller; `repository_dispatch` needs `Contents:write` and is NOT a least-privilege replacement.
4. **If PRIVATE Actions doesn't start, diagnose rather than guess:** distinguish paid-hosted minutes used, exhausted included quota, zero-dollar blocking budget, account Actions disabled, runner unavailable, workflow disabled, bad permissions, and first-job error. A single failed run cannot prove budget exhaustion. GitHub official budget document says exhausted Actions **product budget can block GitHub-hosted runners**; it does not establish universal self-hosted scheduling under all account disablement causes.
5. **If only Private hosted minutes are exhausted:** a pre-approved, isolated, dedicated single-repository **self-hosted** runner can be a non-GitHub-billed candidate if Actions remains enabled, matching fixed workflow+trigger+permissions. No self-hosted infrastructure is currently admitted here. If Actions itself is disabled, use a **separately approved external compute/transport** or HOLD; no automatic fallback. Never run untrusted PR code in a persistent secrets-bearing host.
6. **If no fixed authorized route exists:** HOLD with a concrete missing requirement. Do not create a new App/OAuth session, token, paid resource or public bridge merely to keep progress moving. Human security/expense gates remain separate.

## Supported sources — verified official documentation

- GitHub hosted/free/Private usage: [billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage), [2026 GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [budget blocks](https://docs.github.com/en/billing/how-tos/set-up-budgets).
- GitHub self-hosted: [self-hosted runners](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners), [secure use](https://docs.github.com/en/actions/reference/security/secure-use), [runner labels](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow).
- Workflow/API auth: [workflow_dispatch REST](https://docs.github.com/en/rest/actions/workflows), [Private branch GET](https://docs.github.com/en/rest/branches/branches) and [Git ref GET](https://docs.github.com/en/rest/git/refs). HEAD requires `Contents:read` for the existing tested Private App path. C3-B `Metadata:read` GraphQL trial is **FAIL_B**; no retries.
- Independent server candidates are **conditional**, not alternatives to GitHub auth: [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [Cloudflare Workflows Free pricing](https://developers.cloudflare.com/workflows/reference/pricing/) (10ms CPU/step, 3000 steps/day at the stated Free limits), [Deno Deploy Free pricing](https://deno.com/deploy/pricing) (HTTP/JS service free, **Sandbox microVM not included**).

## Offline planning module

`tools/safe_dispatch_fallback.py` has a pure `plan_fallback(G1Admission, EvidenceSnapshot)` interface. It is NOT connected to GitHub transport. `EvidenceSnapshot` is **untrusted caller-supplied evidence** until a future adapter independently verifies its provenance.

- Returns only `PLAN_ONLY` (possible route, no authority) or `HOLD`. Never `ADMITTED`, `EXECUTED`, `READ_VERIFIED`, run ID, credential or receipt.
- Preserves the accepted trusted G1 backend; no request-selected replacement backend, credential, runner command, arbitrary URL or user-provided shell.
- `GITHUB_CONNECTOR_INTERACTIVE` means a currently typed interaction only, not a G1/G2A certified machine result. `GITHUB_HOSTED_FIXED_WORKFLOW` and `PRIVATE_SELF_HOSTED_FIXED_WORKFLOW` are **candidates**; no invocation, runner registration or scheduler proof.
- `private_quota_exhausted` is an evidence value from an independently checked account/billing state, **not** inferred from a failed workflow. `all_actions_disabled` explicitly prevents self-hosted runner selection.
- Unreviewed API path, unknown quota, missing fixed dispatch and missing isolation/Human approval all return HOLD. Tests run entirely offline.

### Closure vs next owner

Acceptance here is a reviewed **decision fixture only**; production routing is not enabled by merging it. Live headless/private API fallback remains parent #413 C3/C6-gated. New App authorization, private `Contents:read`, installing runner, paying any provider, deploying Worker/Workflow or adding execution authority require a future explicit owner Work Order and independent security assessment of the **real** effectful boundary. Do not pursue any of these merely to test an alternative. Re-evaluate from original objective at each subsequent checkpoint and STOP if a native operation already satisfies it.
