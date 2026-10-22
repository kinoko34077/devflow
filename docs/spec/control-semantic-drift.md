# Control semantic consistency: bounded evidence contract (devflow #726)

Status: **M1 bounded comparator accepted; M2 devflow-only native postmerge PR-stage and explicit owner-linked review pilots accepted on 2026-10-22**. Full multi-repository transition coverage, unlinked/undeclared PR relevance, M3 and M4 remain OPEN. No active Control authority, no repair bot, no replacement for Cursor #576 or SMC #588.

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

## M2 bounded native-read pilot (2026-10-22; accepted in one exact Public scope)

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
printed. Unit tests substitute the subprocess with synthetic REST shapes and
do **not** alone count as a real authenticated GET pilot. The real
one-shot and post-main Required CI have been independently completed:

- [devflow PR #768](https://github.com/kinoko34077/devflow/pull/768)
  merged at exact main `f7453ce4e018f8a834943c33fe31b3ab3df397a1`.
- Exact-head [Required #39639341465](https://github.com/kinoko34077/devflow/actions/runs/39639341465)
  SUCCESS, 2,093 tests including 14 new tests; native Formal Review
  #5603251343 and readiness [#39639341473 attempt 2](https://github.com/kinoko34077/devflow/actions/runs/39639341473) SUCCESS.
- [Post-main Required #39639606165](https://github.com/kinoko34077/devflow/actions/runs/39639606165)
  SUCCESS, authenticated owner CLI query.
- Real owner-PC existing authenticated `gh api` two-GET execution
  of the merged Python module returned `ALIGNED / SAME_SCOPED_STAGE`
  for Control #705 `MERGED` and PR #14 `MERGED`, exact
  PR head `f6ef6f9980a80e5fbfa881db766f8231d2bb3e38`.
  Direct request times 2026-10-21T17:00:16.629669+00:00 and
  2026-10-21T17:00:19.125984+00:00; process exit 0, transient
  files removed. [Owning acceptance #726](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6321748478).
  This evidence is confined to this one Public PR and does
  not prove a live detector for arbitrary Controls.
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

## M2 producer-invoked exact PR stage check (2026-10-22; bounded)

Reuses `tools/control_semantic_pilot.py` (does not create a second comparator).
At an accepted transition, an authorized producer may explicitly run:

`python -m tools.control_semantic_pilot --control 705 --repository kinoko34077/kinotch-editor-platform --pr 15`

The checker performs exactly two bounded native `gh api GET` reads of the
selected Control and owning PR; it does not fetch source code, change a
permission, update an Issue, watch other repos, or schedule a daemon.
Only canonical exact subject links in the CURRENT `## Next Action` with
an explicit stage label are comparable. Current `OPEN` means only GitHub
`state=open`, not 'review accepted', mergeable or product-ready; it is
distinct from AWAIT_REVIEW and AWAIT_MERGE. Comparing OPEN with either pending-review stage returns UNKNOWN (different granularity), not a false mismatch. A later merged PR with an
unchanged explicit OPEN claim yields a POTENTIAL_MISMATCH review candidate,
never a Control auto-write. Missing/ambiguous claim or inconsistent source
yields UNKNOWN. The no-arguments #705/PR14 invocation remains supported.

Producer-owned affected-surface reconciliation under
`docs/operations/DURABLE_PROGRESS_EXTERNALIZATION.md` §7 remains the
authority. A producer must actually call and interpret this advisory
at their transition; merely merging this code does not install a hook.
Full automatic merge/Close interception and all-repository semantic
monitoring are NOT accepted by this bounded command.
### Opt-in producer-exit status gate

After an accepted PR transition, the producing worker can execute the same
scoped native reader with `--require-aligned`:

`python -m tools.control_semantic_pilot --control 705 --repository kinoko34077/kinotch-editor-platform --pr 15 --require-aligned`

Exit code **0** means exactly `ALIGNED` for the one scoped PR stage;
**2** means `POTENTIAL_MISMATCH` needing producer-owned recheck/repair;
**3** means `UNKNOWN`/`NOT_COMPARABLE` (missing source or inadequate
proof). JSON output is kept for durable receipts. Without the flag, the
established diagnostic command retains exit 0 for compatibility. A merge,
CI success or emitted JSON is not enough to close a bounded task if the
actual producer-exit check has never been called and the relevant Control
was not verified. This does **not** block GitHub merges: it only allows
an explicitly participating producer to refuse premature `DONE`.
It does not install a webhook, modify branch protection, update an Issue,
or make a scheduler. A strict UNKNOWN is a reason to inspect the affected
canonical surfaces, not permission to mark failure/complete.

## M2 devflow-only automatic merged-PR event pilot (accepted for exact current claims)

The repository-local `.github/workflows/control-semantic-postmerge.yml`
subscribes to GitHub's native `pull_request.closed` event only in **devflow**
for a genuinely `merged=true` PR, using the existing read-only default
GitHub Actions token (`contents:read`, `issues:read`,
`pull-requests:read`). It invokes `tools/control_semantic_postmerge_event.py`
from the now-current main branch. This adapter reuses the previously
accepted `check_pr_transition_once` and `compare_claim` functions rather
than creating a second comparator or cross-repository cache. No webhook
server, periodic process, secret, broad permission, Control writer, or
automatic pull-request merger is introduced.

- Only a trusted exact devflow PR event and exact open Control #16 current
  `## Next Action` can be checked.
- A canonical linked claim matching the *triggering PR* that remains OPEN
  after the actual merge gives `POTENTIAL_MISMATCH`, the CI step exits 2
  and a sanitized report appears in the **run summary**; a failed gate is
  a producer reconciliation signal, not a rollback of the merged PR.
- A canonical claim already MERGED gives `ALIGNED` / exit 0.
- No *exact current PR link or scoped mention* gives `NOT_APPLICABLE` / exit 0:
  **not** an endorsement that the Control contains no drift. A loose exact-number
  PR mention without its canonical link, or an explicit target link with
  incomplete/ambiguous stage, gives `UNKNOWN` / exit 3; similarly numbered
  PRs must not be mistaken for the triggering PR.
- Unexpected repository, bad event identity, missing canonical source,
  API failures and malformed input all fail closed with `UNKNOWN`.

The event pilot does **not** automatically correct a Control or claim
every merged PR changed the repository-wide Next Action. A producer still
owns the targeted repair and readback under #251. It cannot cover PRs
in other repositories without their own authorized event routing and
matching owner Control. It does not verify product deployment/physical
acceptance or general semantics of unstructured old prose.

**Accepted first live event:** [devflow PR #776](https://github.com/kinoko34077/devflow/pull/776)
merged at `af280d0c9d6e23b31d31cdee949a030380240cf9`; Required
[#39695059094](https://github.com/kinoko34077/devflow/actions/runs/39695059094)
passed 2,132 tests, formal current-head Review/readiness accepted, and
post-main Required [#39695388127](https://github.com/kinoko34077/devflow/actions/runs/39695388127)
succeeded. A **real automatically GitHub-triggered**
[pull_request run #39695388458](https://github.com/kinoko34077/devflow/actions/runs/39695388458)
detected the actual stale Control #16 PR #776 `OPEN` claim after merge
and failed exit 2. The producing worker then repaired only its own
Control #16 stage to `MERGED` and reran the failed run: attempt 2
**SUCCESS**. Both the actual triggering event and its repair recovery
were independently observed. Durable owner receipt:
[devflow #726](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6329124725).

**Still unaccepted:** an event with no explicit current PR reference has
only offline `NOT_APPLICABLE` tests until an actual run confirms it;
this branch's normal documentation-only PR will provide a bounded native
negative control. Neither a missing PR reference nor a successful workflow
means all semantic claims are consistent. Other repositories do not inherit
this workflow, and M2 cross-repository propagation, M3, M4 remain OPEN.
No automatic Control writeback has been authorized.

## M2 bounded missing-PR anchor review (2026-10-22; live event accepted in devflow only)

The devflow-only native merged-PR event checker previously emitted
`NOT_APPLICABLE` when no canonical current PR link existed in Control #16.
This is not proof of non-impact: a PR can belong to an *already tracked*
Work Order even when its number has not yet entered Next Action.

To avoid introducing a second comparator or a general language heuristic, the
existing `tools/control_semantic_postmerge_event.py` optionally follows
a **single exact owner declaration** in the *merged* PR body:

`Owning-Issue: https://github.com/kinoko34077/devflow/issues/726`

Only when the actual owning PR and owner Issue are independently obtained
via read-only native GitHub GET, correctly identified and open, and the same
owner Issue is mentioned in Control #16 **current** Next Action, does the
checker emit `RECONCILIATION_REVIEW_REQUIRED` (exit 4). It is a *producer
review obligation*, **NOT** a proven stale Control, not an Issue mutation,
not a work-complete status or a merge rollback. Missing marker → `NOT_APPLICABLE`,
not `ALIGNED`; malformed/ambiguous marker, untrusted owner, missing current
owner reference, invalid response or failed GET → `UNKNOWN` (exit 3).
Exact current PR stage link continues to use the original M1 comparator.
Never infer owner scope from a similarly numbered Issue or broad prose.

The owner marker is author-supplied and not an authority grant. It only
raises a review signal, which requires the producer to compare actual
accepted scope against the Control's Current Action and update only truly
stale surfaces. It does not require adding every merged PR to a Control
without a substantive reason. No privileged writeback, GitHub App, new
token, additional repository runner, or background process.

**Actual native acceptance evidence:** [PR #778](https://github.com/kinoko34077/devflow/pull/778)
introduced the owner marker but its first real automatic
[run #39706303305](https://github.com/kinoko34077/devflow/actions/runs/39706303305)
exited 3: a quoted inline marker was miscounted as a second owner declaration.
This first failed pilot is **not accepted** as proof of exit 4. The real
defect was repaired in [PR #780](https://github.com/kinoko34077/devflow/pull/780),
merged as `986884445b0e6f8fcbe6d24350200dd818d9b5ab`, with **2,137
passing tests**, exact-head review/readiness, and
[post-main Required #39706669943](https://github.com/kinoko34077/devflow/actions/runs/39706669943)
SUCCESS. The fix counts only uniquely anchored complete declaration lines,
including CRLF, rather than prose quotations.

The actual unprompted GitHub
[merged-PR event #39706669809](https://github.com/kinoko34077/devflow/actions/runs/39706669809)
for #780, initially with no direct Control #16 PR #780 anchor but an
explicit owner marker and current Control #726 work reference,
**failed with exit 4** (producer reconciliation review candidate).
The producer independently checked actual merge main, corrected only the
meaningfully affected Control #16 current stage to PR #780 MERGED, and
reran the failed event job: **attempt 2 SUCCESS**. The raw job step-summary
JSON was not fetched; code's one-to-one exit4 status mapping and native job
exit evidence support this bounded finding.

This accepts one devflow-only owner-link trigger and producer repair,
**not** universal provenance of owner relevance or unattended writeback.
A PR lacking the optional marker still returns `NOT_APPLICABLE` without
validating absence of semantic drift; do not distribute the partial
detector broadly and claim complete fleet M2. Owning
[Issue #726](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6330598972)
holds the exact evidence and remaining gates.

## Follow-on full M2 producer-owned prevention and M3–M4, not accomplished here

1. Add a **trusted, source-complete GET adapter** using existing devflow read transport/projection contracts; do not build a new privileged crawler or let the comparator infer reliability from JSON submitted by the caller.
2. Select accepted exact subject refs in owning task/PR transitions; producer-owned `affected-surface reconciliation` remains the first-line preventive action.
3. Offer a read-only, source-cited mismatch report showing uncertainty, observation time and the specific stale field. Normal stage difference must not be reported as drift.
4. Validate against a bounded real pilot, independent review, exact-head regression/CI, and independently re-read any later approved Control correction; do not mutate Controls based on this candidate alone.

Exit/rollback: delete this isolated comparator and tests if it gives false confidence or overlaps the existing M3 source; no runtime job, schedule, remote service or authorization state is changed.
