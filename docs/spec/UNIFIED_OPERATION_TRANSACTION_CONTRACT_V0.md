# Unified Operation Transaction Contract v0 — Read-first, bounded effect, verified outcome

Status: **PROPOSED / non-operative cross-operation design** (2026-10-12). Owner: [devflow #487](https://github.com/kinoko34077/devflow/issues/487). This document is not an active dispatch API, executable permission, approval receipt, or override of any repository-local contract. User authorized the shared design direction; effectful activation remains subject to each already accepted technical/security/Human gate.

## 0. Sources, ownership, non-duplication

| Existing contract | Verified state | Preserve / share / exclude |
| --- | --- | --- |
| [#413](https://github.com/kinoko34077/devflow/issues/413) G1 safe dispatch | Offline proposed G1; two real Public owner-only read-only comment commands accepted | G1 owns request transport, trusted command catalog selection and initial classification. **Never derive authorization from an Issue comment**. Share strict request/schema parsing and catalog identity; not an arbitrary shell/Workflow ID facility. |
| [#439](https://github.com/kinoko34077/devflow/issues/439) review/Human gates | Closed accepted | Determine review and Human gate from **actual changed surface**, explicit protected decisions and irreversibility. Old G1 v1 forces all write requests to NEEDS_HUMAN: preserve that v1 fail-closed rule until a separately reviewed v2 policy migration; do not silently weaken it. |
| [#384](https://github.com/kinoko34077/devflow/issues/384) + [JO #300](https://github.com/kinoko34077/japanese-orthography/issues/300) | Accepted S0–S5, immutable v1 trusted pin | Separate source generation/verification and privileged writer; exact caller/producer and archive manifest, limited target, non-force branch update, post-write verification/replay. **Keep JO pin and runtime unchanged**. |
| [#465](https://github.com/kinoko34077/devflow/issues/465) R1, [PR #470](https://github.com/kinoko34077/devflow/pull/470) | R1 actually merged at ebd20bb76d38a1c18b85f730a0a96753c02390e7 | Owns static recipes, source producer, run/triggering actor/caller provenance GET verification, trusted source bytes, bounded ZIP/manifest, read-only preview and **dormant** write adapter. Reuse through an adapter, do not recode or edit its active lane without coordination. |
| [#474](https://github.com/kinoko34077/devflow/issues/474), [PR #475](https://github.com/kinoko34077/devflow/pull/475) | Distinct effectful testapp writer pilot **HOLD** | Owner of actual writer branch, target protection/PR-only constraint, independent final security review, live replay/revert evidence. testapp default main presently not demonstrated protected/PR-only; #487 must NOT bypass or activate. |
| [execution-coordinator](https://github.com/kinoko34077/execution-coordinator) / [Control #107](https://github.com/kinoko34077/devflow/issues/107) | Existing claim/lease/generation/fencing authority | Agent task ownership/dispatch only. Contract may require valid external coordinator claim for an agent-owned task, but never starts a second queue, lease DB or claim state. |
| Repo-local owner Issue/PR | Durable technical truth | Owns actual resource-specific constraints, observed HEAD, CI/readiness, job permissions and accepted effect/rollback. devflow owns generic vocabulary, not local feature implementation. |

## 1. Central principle and non-equivalence

**Every mutation MUST pass a genuine read-only observation and a plan validation before effect.** This is an invariant of the effect path, not a requirement to start a separate GitHub Actions job for trivial API mutations. For low-risk Issue/PR metadata edits, a bounded inline GET+diff+validation suffices; for untrusted code/artifacts or privileged effects, isolate a separate read-only producer/planner job from a job holding write privileges. The writer MUST independently obtain fresh target/auth context before effect regardless of the earlier read.

A successful read/plan does **NOT** grant write permission, prove the requester's identity, guarantee fresh state, establish runtime claim ownership, or prove an effect will commit. A hash/digest proves equality only with a verified original; an untrusted manifest or Issue comment cannot authenticate itself. A read-only job can still run hostile code or consume expensive computation; treat compute execution and third-party output as separate exposure.

### Sequence (semantic states, not necessarily six separate processes)

1. **Identify:** a pre-reviewed versioned operation from an immutable trusted catalog; verified actor/caller/source and exact target identity (not text-input assertions).
2. **Observe (READ):** use only the minimal trusted reader to fetch the exact relevant target, capability/permission snapshot, branch/ruleset, PR/CI/review, active owner/collision if required, and current version/head.
3. **Plan (READ):** compare requested transition against allowed effects, bounded deltas, static paths/fields, budgets, safe reversibility and trust conditions. Produce a non-authorizing plan plus evidence/provenance and an observed-state fingerprint.
4. **Gate (READ):** separately decide required Human/reviewer policy, actual actor rights, runtime coordinator fence when relevant, plan version, immutable trusted source, source verification and current target. Reject incomplete/missing evidence.
5. **Effect:** a narrowly permitted operation-specific writer re-fetches the latest target/state immediately before write, checks an endpoint-specific conditional update/concurrency rule and imposes caps. Never execute untrusted PR/artifact contents inside a privileged writer. Changes must be constrained to a reviewed resource/field/path, not general repository privileges just because a token can access them.
6. **Verify/reconcile (READ):** inspect actual resulting target, changed paths or PR state, accepted source/CI and any external effects. Record a scoped receipt; uncertainty triggers read-only reconciliation BEFORE any retry or correction.

Each request has a finite idempotency key and target/version scope, but the key alone does not provide deduplication. Implement replay prevention in the effect-owning existing durable/serialized surface, with independent authenticated run/attempt and target outcome evidence.

## 2. Three separate data domains (strict no-trust transfer)

**OperationDefinition — trusted catalog record.** Versioned action identifier; owning component/technical handler; fixed backend and reviewed executable/file SHA; exact repository/resource class; allowed read capabilities; allowed effects and path/field set; target-comparison mechanism and its guarantee level; source/caller/actor provenance requirements; resource limits; expected postconditions; idempotency mode; compensation/recovery class; Human/reviewer predicate aligned with accepted policy. The requester MUST NOT choose raw URL, shell, arbitrary workflow file, executor module, token, arbitrary ref or new action name. Definitions loaded only from immutable reviewed source, never from Issue/PR input.

**PreflightEvidence — no-authority result.** Request ID, schema/definition version+trusted catalog source SHA, normalized resource IDs, authenticated *observation provenance* (e.g. actor, GitHub run ID/attempt/verified Workflow/caller SHA), observed versions/PR-head/base/head/ETag where supported, minimal bound diff/action intent, explicit read/validation results, dependency/CI/reviewer state, time/freshness class and digest. Redact credentials/private content. The planner does not mint executable bearer capabilities.

**EffectReceipt — observed effect and verification.** Validated request/definition ID, authenticated writer identity/source/run+attempt, target exact prior/current identities, permitted mutations and observed commit/field deltas, status, verification proofs, risk containment/rollback, replay link and durable owner Issue. Neither a planner `PASS` nor command exit code 0 alone constitutes successful completion.

Reject missing/extra security-critical fields; never substitute a self-asserted actor, archive manifest or generic timestamp for separately authenticated GitHub evidence. Distinguish raw data hashing from authentically signed/verified provenance; canonical hashing should include schema/version and exact target to prevent cross-target replay.

## 3. Endpoint-specific concurrency and freshness — essential correction

| GitHub effect | Supported guard from verified docs/implemented path | Guarantee / operational disposition |
| --- | --- | --- |
| PR merge endpoint | GitHub REST merge accepts expected PR HEAD sha and returns conflict if mismatched | Use exactly the server-checked expected HEAD, plus required CI/review and target/base revalidation. Do not infer that the original plan's other facts were atomically checked. |
| Update Git ref (PATCH git/refs) | GitHub REST with force:false enforces **fast-forward**, not a documented expected-old-head argument | This is **not a generic atomic CAS**. Re-fetch exact head, build candidate single-parent commit from that head, restrict branch and protected/main targets, serialize writer where required, demand fast-forward, read back actual ref/commit, and document the residual race. Require stronger channel where an atomic expected-old-head condition is materially necessary. |
| Issue/PR metadata PATCH and comments | Read-before-write and post-readback available; no universal atomic conditional old-value check established by this design | Weakly guarded: use exclusive owner/serialized mutation or scope narrowly, detect intervening state, never claim serializable compare-and-swap. For uncertain effects, reconcile receipt before retry. |
| Generated artifact ZIP/files | Existing #384/#465 data-only checks, exact path/digest/max-size, trusted runner/caller/source/run, protected/default branch denial | Reuse the existing operation-specific helpers without expanding their accepted target sets or claiming artifact hash alone authorizes writes. |
| Provider execution / deployment | External side-effects and computed runner capacity differ from GitHub repo reads | Per-effect Human/security gate, independent provider/runner identity/ack proof; no generic automatic deployment or Private compute admission. |

Sources: [Git refs REST](https://docs.github.com/en/rest/git/refs), [PR merge REST](https://docs.github.com/en/rest/pulls/pulls), #384 accepted writeback. A read immediately before PATCH reduces—but does not necessarily eliminate—the time-of-check/time-of-use race. **Do not call all target classes CAS-capable** or convert `force:false` into an atomic expected-value predicate in documentation/tests.

## 4. Proposed outcome taxonomy and mapping

| Generic outcome | Meaning | Existing adapter caveat |
| --- | --- | --- |
| COMMITTED | Verified allowed effect and required postconditions | Must inspect authenticated target output/receipt, not infer from command request accepted or runner success alone |
| NO_OP | Same desired state was already verified; no side effects | Requires actual current-state observation and idempotency proof |
| REJECTED | Invalid/untrusted source or policy/input disallowed | A skipped workflow job is a guard refusal, not proof of operation success |
| STALE | Observed target/ref/CI/claim snapshot no longer matches | No automatic stale-plan replay; fresh read and replan |
| UNKNOWN_RECONCILE | Timeout or ambiguous external result | Read/lookup by request and run ID first; no blind duplicate mutation |
| VERIFY_FAILED | Effect possibly ran but final conditions not proved | Preserve evidence, stop/contain and evaluate bounded compensating/revert PR |
| HUMAN_GATE | Actually required named Human/security step missing | No conditional approval inferred from user-submitted comment or G1 ADMITTED state |

The generic taxonomy is a **projection** of existing operation-specific native statuses. Do NOT rewrite existing #384/#465 receipt enums in place or make a generic result discard their richer distinctions.

## 5. Capability classes and approval model

- READ_DATA: ordinary authenticated metadata access; no repository mutation; guard privacy and external compute/cost.
- READ_EXECUTE: code/test/build/benchmark using a runner; token can be read-only, yet PR-origin code and compute resource are separately risk-classified.
- REVERSIBLE_EFFECT: narrowly bounded Issue edits / scratch branch mutation / safe PR merge with reviewed actual effects and recovery evidence; applicable self-review and existing per-effect permissions may suffice under #439.
- PRIVILEGED_EFFECT: action/permission/secret/source/safety-boundary mutation, arbitrary external execution, private-data exposure, or difficult-to-reverse destructive change. Separate explicit Human/security gates and distinct reviewers if actually justified.
- RELEASE_EFFECT: external publishing/deploy/release; explicit user confirmation even where underlying Git operation seems reversible.

Review and Human approval are different questions: do not make the generic v0 design secretly relax existing G1 `write -> NEEDS_HUMAN`; if v2 approval policy is later adopted, update/review G1 independently with backward compatibility, grounded in #439 and a named effectful pilot. A provider/model self-review is never a distinct-system independent review.

## 6. Integration interfaces, not code ownership transfer

- #413 ingress/G1 may emit an **untrusted request** with a trusted catalog action ID, then invoke the shared planner/guard. Continue direct installed GitHub API for already supported simple edits; Issue-comment ingress only for specifically missing actions and fully reviewed commands.
- #465 R1 read-only authenticated preview remains the operation-specific planner for artifact writeback. An adapter may translate its actual source-provenance/ZIP/target/dry-run report into generic PreflightEvidence, without modifying its verification algorithm or exposing a write-capable transport. The shared v0 planner must never bypass archive-specific checks.
- #474 writer remains the **sole** effectful testapp owner if independently accepted. An adapter may translate a verified writer receipt into generic EffectReceipt. **No #487 dependency is allowed to block or unblock #474's existing protection/Human/reviewer gate**; do not merge or activate it from a generic contract.
- execution-coordinator remains the unique agent claim and lease service. For workflows that operate on an agent-owned work item, the effect gate queries a fresh coordinator fence; for ordinary direct GitHub API operations, do not fabricate coordinator claims.
- Repository-local trusted source/CI/policy and any immutable JO Caller pin remain authoritative. Always version adapter contracts; historical accepted runtime remains backward compatible.

## 7. Roadmap and independent acceptance

**A0 — LIVE inventory COMPLETE:** #487にowner、interface、merged/unmerged SHA、危険なAPI意味論を記録済み。#465/#474のコードは変更しない。

**A1 — 仕様書のみ：** この非稼働仕様を独立docs PRで公開し、exact-head Review・既存Required CIを通す。#413 G1・#439との整合を確認。変更範囲は新規仕様文書だけで、trigger・権限は有効化しない。

**A2 — 別タスク、offline-only：** 信頼済みparser・provenance・validatorをimportし、generic plan/outcomeの**表示用adapter**を構築する。writerを複製しない。テストは偽actor/caller、stale SHA、別target、JSON重複key、予期しないwrite、無署名plan、権限誤分類、競合/再試行、HEAD/CAS不足、timeout。READMEに合否を記録。通信・live書込なし。

**A3 — ownerとの非干渉確認後：** #465の受入済みartifact previewからread-only evidence adapterを1件、独立受入された#474 native writer receiptからoutcome adapterを1件。古いR1の上書きや、#474の特権書込経路を有効化したとみなすことは禁止。

**A4 — 別途許可された実操作：** 接続済みGitHub APIで可能な影響の小さい具体的Public effectを選び、read→plan→実行直前の権限/状態再取得→限定effect→readback→reconcileと負例・replayを実証。対象がPR/head/refかIssueかに応じて原子的更新保証を評価する。HOLD中の#474で試験書込しない。

**A5 — 必要なPublic範囲だけopt-in展開：** 単一dispatcher workflowが本当に有効か検証し、command毎のworkflow乱立とjob別最小権限の両方を考慮する。

**A6 — Private・特権操作：** runner/課金/認可の現行実証と対象を特定したHuman承認がある場合のみ。A0〜A5で目的達成なら**STOP**。

**段階の独立性：** A1は**非稼働仕様の受入だけ**。汎用executor、共通認可token、GitHub-hosted Private runner、allowlist拡大、複数repoの特権writerは承認されない。次の段階はlive owner・実装・証拠を確認して個別判断する。

## 8. Required negative / failure-mode matrix

以下の14ケースを区別してfail-closed検証する。正常入力の成功だけでは受入しない。

1. Issueコメント/manifestが自称するactorとGitHub認証actorが異なる、runner環境偽造、owner Issue取り違え。
2. 未登録action・対象外resource、任意shell/ref/workflow、壊れたJSON・重複key。
3. 信頼済みcatalog/workflow SHAが変更、repo・PR・source identity不一致。
4. live GETのないpreflight、弱いHEAD証明、事前read省略要求。
5. 同じplan文面でもrepo/SHA/run・attempt/recipe/body bytes/actorが異なるreplay。
6. 計画後のPR HEAD/対象branch/CI変化、coordinator lease失効。
7. Tokenには広い権限があるが実操作が許可済みeffect/path集合を超える。
8. PR由来ZIP/artifactの重複・追加path、link/traversal、zip bomb、digest不一致。writer権限で中のコードを実行しない。
9. workflow `SKIPPED`、API受付、exit 0、未監査artifactを偽の成功として扱う。
10. effect実行後のtimeout・receipt不明を、未検証の成功や盲目的再書込に変える。
11. Private/特権callerの実runner・security capabilityを未確認のまま通す。
12. 同じGit refへの複数writer・異なる子commit、`force:false`のfast-forwardを原子的expected-old-ref CASと混同。
13. 別agentがcoordinator claim/leaseを保持中なのに#487に第二の所有権を作る。
14. Feature flag/catalog v2移行時に既存JO/G1 v1のfail-closed意味を変える。

## 9. Design decision / global replan

**Preferred:** Policy/contract as shared **thin semantic layer**; operation-specific trusted planner and effect executor remain in their owners; native GitHub API/direct operations FIRST. Reuse proven source as dependencies rather than wholesale extracting or relocating #465 writer. A0+A1 can finish safely now. A2+ are conditioned on true integration value and actual acceptance evidence. No second generic task engine.
