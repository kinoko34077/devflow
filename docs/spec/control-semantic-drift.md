# Control semantic consistency: bounded evidence contract (devflow #726)

Status: **M1 read-only candidate**. Not active Control authority, not M3 work classification, not the task Cursor #576 verifier, not SMC #588, and not a repair bot.

## What causes the defect?

The controlling worker can accept a scoped PR/Issue transition without changing the directly affected human-readable `Next Action` on a Repository Control. GitHub Project / Repo Monitor can then present a snapshot that is structurally trusted and current but **semantically wrong** about that one task. Conversely `Work Status=AUDITED` and an open implementation PR are often perfectly compatible, because audit status and a task's implementation state are separate dimensions.

Changing a single status label, comparing a historical Audit SHA to latest main, or counting open PRs does not establish semantic mismatch.

## Explicit evidence (M1)

`tools/control_semantic_drift.py::compare_claim` accepts **one source-verified current Control claim** and **one independently verified complete observed fact**, with the same repository, exact subject and dimension. Caller is responsible for obtaining real current GETs and for classifying the specific active `Next Action` / `Active Work` statement; historical text is not a current claim. The comparator does not parse arbitrary prose, access GitHub, update Issues or select an implementation owner.

- `PR_GATE`: AWAIT_REVIEW, AWAIT_MERGE, MERGED, CLOSED_UNMERGED, UNKNOWN.
- `PUBLIC_ENTRY`: UNVERIFIED, VERIFIED, FAILED, UNKNOWN. This is about an actual published entry, not just a Pages build.
- `FIELD_ACCEPTANCE`: UNVERIFIED, ACCEPTED, REJECTED, UNKNOWN. Physical usability or audio experience cannot be inferred from CI.
- `BILLING_PREFLIGHT_DEPLOYMENT`: CODE_ONLY, READ_ONLY_LIVE, ROUTING_LIVE, UNKNOWN. `CODE_ONLY` means merged model/adapter/test code without an independently observed deployed authenticated reader; `READ_ONLY_LIVE` requires a real current preflight GET/retained result but NO job routing; `ROUTING_LIVE` requires an effect-time trusted route decision and independently observed action. A GitHub Actions CI pass cannot establish the latter two.
- `PRIVATE_EXECUTOR_ADMISSION`: NOT_ADMITTED, ADMITTED, UNKNOWN. `ADMITTED` requires independently authenticated owner/host authorization and protected Private source/isolation/resource constraints, not simply a manual immutable Public WSL job or a green test suite. `NOT_ADMITTED` is an explicitly verified negative operational decision, **not** inferred merely from a missing deployment receipt.

The last two axes were added after actual #752 R1/R2 code-only vs runtime confusion and [#726 2026-10-21 findings](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6316896155). They are comparison vocabulary ONLY, not runtime adapters. A current reader must independently acquire exact same-subject source facts and treat absence of evidence as UNKNOWN. `BILLING_PREFLIGHT_DEPLOYMENT` and `PRIVATE_EXECUTOR_ADMISSION` are intentionally different dimensions: a live billing GET does not grant access to a Private executor or native GitHub Checks.
- Each side supplies a GitHub source URL and its actual timezone-aware read timestamp. Control URL must be an exact devflow Issue; observed URL must identify the **same owning repository and Issue/PR number**, with a PR URL required for PR_GATE. The comparator rejects credentials, ports, query strings and unrelated paths. Those checks are necessary but **not proof** that a source was independently authenticated.
- For comparison, the observed read must be at or after the Control read and within one hour. Earlier or excessively separated reads return UNKNOWN rather than an ALIGNED/MISMATCH assertion. Actual event chronology/version authority requires upstream validation; timestamps by themselves cannot prove causality.
- `source_verified` / `source_complete` are caller-supplied assertions and **cannot themselves establish trusted provenance**. Only an authenticated, complete canonical GET adapter may populate them; do not feed the function ad hoc untrusted Issue text.
- Results: `ALIGNED`, `POTENTIAL_MISMATCH`, `NOT_COMPARABLE`, `UNKNOWN`. A potential mismatch is a **review candidate only**; no automatic correction, claim/permission change or read-to-write promotion. Incomplete, unverifiable, historical, mismatched or otherwise ambiguous evidence does not become a positive finding.

`UNVERIFIED` for FIELD_ACCEPTANCE or PUBLIC_ENTRY is an absence of recorded proof, **not a contradictory failure**; the comparator returns UNKNOWN unless both sides have affirmative, same-scope observations. The caller must still independently check stage/version equivalence and event chronology. The v1 comparator enforces read-order and freshness bounds but does not prove event causality, GitHub actor identity, review authenticity, actual public URL health or effective product acceptance. A field name or GitHub-shaped URL is not proof of verified provenance.

## M2 bounded native-read pilot (2026-10-22; pending acceptance)

The production-authority gap is **not** closed by a pure comparator. The
first bounded adapter lives at `tools/control_semantic_pilot.py`; it calls the
existing owner-authenticated `gh api` CLI with only two fixed GET paths:
`devflow/issues/705` and `kinotch-editor-platform/pulls/14`. This pilot is
intentionally **one public repository and one PR** and is not a fleet crawler,
GitHub App, new credential holder, scheduler, auto-writer or source of claims.

Source truth is created after successful native reads, not accepted as a
caller-provided JSON flag. It verifies exact open Control identity, one
current `## Next Action` claim with a canonical exact PR link and explicit
stage token, exact owning PR identity/base/head and result chronology.
`MERGED` and `CLOSED_UNMERGED` are determined from GitHub's PR terminal
fields. An open PR alone **does not prove review readiness**, so the adapter
reports `UNKNOWN`; ambiguous prose, multiple claims, historical sections,
unexpected fields, failed/unauthenticated reads and changing source shapes
also return `UNKNOWN` without effect. The existing
`compare_claim` remains the single comparator and returns a **candidate**
`POTENTIAL_MISMATCH`, never a Control mutation instruction.

Run once, explicitly, from an existing authorized CLI session:
`python -m tools.control_semantic_pilot`.
Output is a sanitized structured result with exact source URLs, observed
times and PR HEAD SHA; no raw Issue body or authentication credential is
printed. Unit tests substitute the subprocess with synthetic REST shapes
and therefore **do not count as a real authenticated GET pilot**. A real
successful one-shot and post-main CI are separate acceptance gates.
The static target/grammar intentionally avoids silently inferring arbitrary
Control prose. Extending to a different PR requires its own scope and
source-backed parser contract rather than guessing from status keywords.

This *pilot adapter* does not establish M2 comprehensive producer-owned
update prevention, M3 projection signals, M4 fleet coverage or durable
cross-repository automatically triggered detection. Results must be
correlated with an actual current Control text snapshot before a producer
edits only their directly affected fields, with independent readback.

## Historical M0 observed cases (as of 2026-10-19; non-normative, not live current state)

| Control | Current claim to investigate | Owning source | M0 disposition |
| --- | --- | --- | --- |
| devflow #59 / Repo Monitor | PR #85 still awaiting review/merge | #84, merged PR #85 and PR #88 | Stale Next Action; Pages deployment succeeded later, direct external HTTP readback still unverified |
| devflow #714 / Site Kit | Pre-implementation evaluation is next | Site Kit #10, merged PR #30 | Stale instruction; M0 gate itself OPEN |
| devflow #705 / Editor Platform | Bootstrap note limits the Control's initial evidence scope | Editor #9, merged PR #10 | Scope disclaimer; not a proven stale claim |
| devflow #500 / Frequency Warp | Several stages coexist | Web #183, native #172 | No status mismatch established |
| devflow #23 / LINE | AUDITED plus open successor PR | #47, PR #67 | No status mismatch established |

## Follow-on M2–M4, not accomplished here

1. Add a **trusted, source-complete GET adapter** using existing devflow read transport/projection contracts; do not build a new privileged crawler or let the comparator infer reliability from JSON submitted by the caller.
2. Select accepted exact subject refs in owning task/PR transitions; producer-owned `affected-surface reconciliation` remains the first-line preventive action.
3. Offer a read-only, source-cited mismatch report showing uncertainty, observation time and the specific stale field. Normal stage difference must not be reported as drift.
4. Validate against a bounded real pilot, independent review, exact-head regression/CI, and independently re-read any later approved Control correction; do not mutate Controls based on this candidate alone.

Exit/rollback: delete this isolated comparator and tests if it gives false confidence or overlaps the existing M3 source; no runtime job, schedule, remote service or authorization state is changed.
