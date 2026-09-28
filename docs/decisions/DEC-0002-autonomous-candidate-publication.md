# DEC-0002: Scope of autonomous candidate publication after the chat-worker pilot

- Status: Accepted
- Date: 2026-09-28
- Related issues: #190 (Phase G item 4), #201, #198, #189, #202

## Question

After the #190 pilot, should real Repository Controls begin publishing autonomous execution candidates (`DEVFLOW_EXECUTION_CANDIDATES_V1`) more broadly?

## Evidence

- A live scan of all 39 Controls found 0 published candidates (#198).
- The pickup path works end to end on the real lane for Claude and for ChatGPT with local execution (#197, #201). Selections were disjoint across concurrent workers, no duplicate claim occurred, and 3C held.
- Every chat still pays a local setup cost: Python ≥ 3.11, checkouts, a token and UTF-8 output (#201). Codex is unverified (#201).
- Adoption mode is `PILOT` (#189).

## Decision

1. **No broad publication yet.** Controls publish candidates **opt-in, per repository**, and only for bounded, reversible tasks. The owner, or an agent acting on an accepted owning Issue, adds the projection block to that repository's Control. Publication and consumption stay separate attempts (3C).
2. Revisit broader publication after the Actions-side transport (#202) is accepted, because that removes the per-chat local prerequisites.
3. Cross-repository pickup stays deferred (#198) until at least two repositories publish candidates.
4. This decision does not change adoption mode. `PILOT -> REQUIRED_FOR_AUTONOMOUS` remains a separate explicit decision.
