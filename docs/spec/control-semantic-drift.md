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
- Each side supplies a verified GitHub source URL and its actual read timestamp (timezone required). `source_verified` / `source_complete` are trusted collector assertions, never user-input privileges.
- Results: `ALIGNED`, `POTENTIAL_MISMATCH`, `NOT_COMPARABLE`, `UNKNOWN`. A potential mismatch is a **review candidate only**; no automatic correction, claim/permission change or read-to-write promotion. Incomplete, unverifiable, historical, mismatched or otherwise ambiguous evidence does not become a positive finding.

The caller must still independently check whether the compared status refers to the same stage/version and whether the observed fact is later or otherwise authoritative. The present v1 comparator does not prove chronology, GitHub actor identity, review authenticity, actual public URL health or effective product acceptance by itself. A field name or GitHub-shaped URL is not proof of verified provenance.

## First observed cases (2026-10-19)

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
