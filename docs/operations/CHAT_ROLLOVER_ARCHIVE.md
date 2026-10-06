# Chat Rollover Archive / Handoff

This document defines the canonical end-of-chat archival and handoff procedure for KiNoTch. managed development work.

It exists so the user does not have to restate a long instruction every time a chat approaches saturation or is intentionally rolled over.

## 1. User command and standing authority

The preferred exact user command is:

> **kinoko34077/devflow#361を読んで、このチャット全体を議事録化し、後続チャット用資料を作成**

Read the Issue named by the command, **`kinoko34077/devflow#361`**, first. It is the stable standing operational entry point for this procedure.

The action direction is explicit: the current worker creates the records, the current chat is the source, and the successor chat is the future consumer. The command means **create the records; do not take over or resume successor work**.

A semantic equivalent may invoke the same procedure only when that direction is explicit. The former phrase **「ガイドライン読んで引き継ぎ」** is legacy/ambiguous and is not the recommended trigger.

Do not ask the user to repeat the longer procedure when the exact issue-addressed command or an equally explicit equivalent is present.

This operation is different from broad work pickup. It does not select new work. It records and closes the current chat boundary in a recoverable form.

## 2. Authority boundary

The rollover records are archival/recovery records, not a new source of current technical truth.

Before writing them, read and reconcile the live authority needed for the affected repository:

1. `devflow/AGENTS.md`;
2. the repository's open devflow `[REPO] <repository>` Control Issue;
3. the active repository-local owning Issue / Work Order;
4. accepted Task Checkpoint Cursor when eligible;
5. designated durable progress surface;
6. active/latest relevant Execution Session Record(s);
7. branch / PR / exact head / live checks / Review when relevant;
8. repository Current State / specification only where needed to establish the current accepted state.

If chat narrative conflicts with live repository canon, live canon governs current state. The minutes may record that the chat contained an older or superseded statement, but the handoff must identify the corrected live state.

## 3. Conversation source boundary

For the minutes, cover **all substantive repository-relevant content from the current conversation that is actually accessible to the worker**, not only the last few messages or final conclusion.

Include material such as:

- the starting objective and context;
- user instructions and corrections;
- decisions and their reasons;
- proposals that were later superseded or rejected;
- investigations and findings;
- implementation, Issue, PR, review and verification progress;
- changes of direction;
- unresolved questions and explicit non-goals;
- relevant operational/process decisions made during the chat.

Do not invent content from portions of a conversation that are no longer accessible. If an earlier portion is truncated, unavailable or not exposed to the worker, state the gap in the minutes. Use durable GitHub evidence to reconstruct **current state and execution evidence**, but do not present reconstructed GitHub facts as if they were verbatim lost chat content.

Routine pleasantries and content with no repository, decision, implementation, investigation, recovery or rationale value need not be copied merely to claim literal message-by-message completeness.

## 4. Repository routing

### 4.1 Single-repository chat

Create or update one archival pair in the affected repository:

- one `[MINUTES]` Issue;
- one `[HANDOFF]` Issue.

### 4.2 Multi-repository chat

Split records by **substantive ownership**, not by every repository name mentioned.

Create a pair in each repository whose own requirements, decisions, implementation, investigation, verification or next action were materially handled in the chat.

Do not create a pair for incidental references.

If the chat also contains a genuine cross-repository/control-plane decision that is owned by devflow rather than any one child repository, create the corresponding devflow archival pair for that cross-repository portion.

### 4.3 No valid repository owner

Do not invent a repository or dump unrelated chat into devflow merely to satisfy the trigger. Record/report the placement ambiguity or absence of a repository owner.

## 5. Canonical Issue naming

Historical repositories contain several record-title styles. New rollover archives standardize on the already common paired prefixes:

```text
[MINUTES] <descriptive chat scope / progression>
[HANDOFF] <current state / resume point>
```

Examples of accepted historical usage include paired records in UniverseGenome, gesture-ime, dev_agent and japanese-orthography.

Combined forms such as `[RECORD/HANDOFF]`, `[HANDOFF / MINUTES]` and older `[RECORD]` chat-minute titles remain valid historical records. Do not rename them solely for conformity. **Do not use the combined form for new rollover archives unless a newer repository-local canonical rule explicitly supersedes this contract.**

A date may be included when it improves disambiguation, but the date is not the machine type. The machine-significant title prefixes are `[MINUTES]` and `[HANDOFF]`.

## 6. Pair provenance and duplicate avoidance

Each newly created pair should cross-link the other record and include enough provenance to distinguish it from unrelated archival records.

Recommended metadata near the top of each body:

```text
Archive-Type: CHAT_MINUTES | CHAT_HANDOFF
Archive-Pair-ID: <same opaque id on both records>
Conversation-Title-At-Start: <exact observed title | UNAVAILABLE>
Execution-Session-ID: <current session id | UNAVAILABLE>
Related-Minutes: <repo#issue>
Related-Handoff: <repo#issue>
```

`Archive-Pair-ID` is archival correlation metadata only. It is not authentication, execution ownership, a lease, a fence or reviewer identity.

Before creating a pair, search open **and closed** Issues for an existing archival pair for the same current chat/session using available provenance, reciprocal links and descriptive scope.

- If exactly one existing pair is unambiguously the current chat's pair, update it instead of duplicating it.
- If only one side exists and its provenance is unambiguous, update that side and create/link the missing mate.
- If candidate identity is ambiguous, do not merge unrelated records. Create a new pair and cross-link it explicitly.

## 7. `[MINUTES]` responsibility

The minutes are the comprehensive **chat chronology / decision history** for the affected repository portion.

They should make it possible to answer later:

- what the chat started from;
- what the user requested;
- what changed during the discussion;
- what was decided and why;
- what was corrected, superseded or rejected;
- what work was actually performed;
- what evidence or repositories/Issues/PRs were consulted;
- what unresolved points remained at the chat boundary.

Prefer chronological organization when sequence affects causality. Use thematic grouping only where chronology would obscure rather than clarify the history.

Distinguish when materially relevant:

- user instruction/decision;
- live GitHub/repository fact;
- tool-observed result;
- inference/hypothesis;
- superseded statement.

The minutes may be long. Their purpose is historical completeness, not current-state authority.

## 8. `[HANDOFF]` responsibility

The handoff is the compact **resume index / current-boundary packet**.

It must prioritize the current verified state and provide a successor with, as applicable:

- the repository and live devflow Control reference;
- active owning Issue / Work Order;
- designated durable progress surface;
- accepted Task Checkpoint Cursor / `first_unfinished`;
- active/latest Execution Session Record(s);
- branch / PR / exact current head;
- current CI/check and formal Review state;
- current accepted requirements/specification/Current State entry points;
- completed acceptance conditions;
- remaining acceptance conditions;
- current blocker / Human gate;
- explicitly superseded or invalid paths that should not be retried;
- exact first unfinished action / Next Action;
- link to the paired `[MINUTES]` Issue.

The handoff must say that live canon must be re-read on resume. It must not become the only owner of an active requirement, blocker or next action.

## 9. Reconcile durable task state before finalizing the archive

The archive is the **last projection**, not a substitute for normal durable-progress rules.

Before finalizing the pair:

1. update the owning Issue / Work Order if its status, blocker or Next Action is stale;
2. update the designated durable progress surface with the latest completed checkpoint;
3. advance/reconcile the Task Checkpoint Cursor when eligible;
4. record current branch / PR / exact head / checks / Review as needed;
5. update repository Current State only when accepted repository-level state actually changed;
6. update devflow Repository Control only when its cross-repository summary actually changed;
7. update the current Execution Session:
   - `HANDOFF` when unfinished work is intentionally transferred to a successor;
   - `RELEASED` when the session has no remaining execution responsibility and no successor handoff is needed;
   - preserve the normal visible transition comment rule.

Do not leave a stale active task merely because the new `[HANDOFF]` Issue contains a correct snapshot.

## 10. Archive Issue lifecycle

The `[MINUTES]` and `[HANDOFF]` Issues are normally **closed as completed after the pair is finalized**.

Unfinished work remains open on its actual owning Issue / Work Order. The archival handoff points to that work; it does not stay open as a second task tracker.

If a repository has a newer explicit local rule assigning active task ownership to a handoff Issue, follow that local rule, but do not infer such ownership from historical titles alone.

## 11. Final response to the user

After the trigger completes, keep the chat response compact. Report:

- which repository archival pair(s) were created or updated;
- the exact `[MINUTES]` and `[HANDOFF]` Issue references;
- the first unfinished action / current blocker, if any;
- whether any conversation range was inaccessible and therefore explicitly marked as a gap.

Do not repeat the entire minutes or handoff body back into the chat unless the user asks.

## 12. Success condition

The operation is complete when:

- every substantively affected repository has the correct archival coverage;
- the minutes preserve the accessible chat's substantive history;
- the handoff points to current live authorities and an exact resume frontier;
- normal owning task/progress/session/cursor surfaces are reconciled;
- the archive pair is cross-linked and duplicate-safe;
- no inaccessible conversation content has been fabricated;
- a successor can resume from GitHub evidence without requiring the previous chat narrative.
