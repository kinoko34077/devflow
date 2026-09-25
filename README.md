# devflow

KiNoTch.の複数Repositoryを横断して、監査・Current State・Work Order・Issue / branch / Pull Request・再監査を追跡する開発管理Hub。

> **Agent / GPT entry point:** [`AGENTS.md`](AGENTS.md)
>
> Managed repositoryで作業を始める場合、まず`AGENTS.md`を読み、対象の`[REPO] <repository>` Control Issueから対象repo自身の正本へ入る。

現在のGitHub repository identityは、管理者によるrename完了までは`kinoko34077/devflow-test`。運用名とrename後の正式repository名は`kinoko34077/devflow`とする。renameが実際に確認されるまでは、旧identityがまだ存在することを隠さない。

実装主体は固定しない。ChatGPT、Codex、その他のAgent/実装者が同じGitHub上の正本・Issue・PR・検証証拠から再開できることを要件とする。

## Cross-repository role

このRepositoryは横断Current State Hubである。

GitHub Project `KiNoTch. Development Control`は表示・俯瞰用の派生層であり、live operational stateの正本ではない。Projectを読めない実行環境でも、このRepositoryと各対象Repositoryから作業を継続できることを要件とする。

## Start / read order

通常のmanaged repository作業:

1. `AGENTS.md`
2. 対象Repositoryのopen `[REPO] <repository>` Control Issue
3. Control Issueに記録された対象Repository自身の入口
4. active repo-local Issue / Work Order / PR
5. 現在タスクに必要なspec / Current State / code / tests
6. 必要時のみ横断正本・運用マニュアル

詳細:

- `docs/operations/AGENT_OPERATING_MANUAL.md` — Agentの開始・実装・handoff・再開
- `docs/operations/REPOSITORY_ISSUE_MANUAL.md` — repo-local Issue / Work Orderの役割と生命周期
- `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md` — 横断開発管理のCanonical specification
- `.devflow/WORKFLOW.yaml` — machine-readable workflow contract

個別Repositoryの詳細仕様や実装状態をdevflowへ複製せず、横断的に必要な現在状態・次Action・参照先だけを保持する。

## GitHub Project synchronization

Project custom fields are projected from canonical devflow Issues by:

- `.github/workflows/project-sync.yml`
- `scripts/project_sync.py`

Operational guide:

- `docs/project/PROJECT_SYNC.md`

The synchronizer supports Issue event sync plus manual `verify` / `reconcile`. It discovers Project/field/option/item IDs at runtime and never treats Project values as canonical state.

A normal ChatGPT environment that cannot directly read the private Project should use the machine-maintained Issue `[SYSTEM] GitHub Project Sync Health` as the primary indirect verification record. Direct Project inspection by a Project-capable agent is reserved for structural changes, API-invisible checks, machine/UI disagreement, explicit verification requirements, or user request.

Live Project access uses repository Actions secret `PROJECTS_TOKEN`. Credential creation/rotation and secret registration remain user-admin/security-sensitive actions.

## 正本の分担

- `AGENTS.md` — Agent/GPTの横断作業開始契約
- `docs/spec/` — 現在有効な横断仕様
- `docs/operations/` — 正本仕様を実運用へ落とす手順
- `docs/decisions/` — 後続判断へ影響する重要な仕様変更・設計判断
- `.devflow/WORKFLOW.yaml` — 状態遷移・権限・読取順・Repository State・運用ルールの機械可読定義
- devflow GitHub Issues — Repository Control、横断Work Order、横断案件、横断Current State
- 各個別Repository Issues — そのRepository固有の実装・調査・finding・Work Order
- Pull Requests — 実装差分、検証結果、再監査、レビュー状態
- Git commits — 変更の実体と時系列
- 各個別Repository — そのRepository固有の仕様、Current State、Issue / PR、コード、テスト
- GitHub Project — 上記正本から反映する表示・俯瞰層

チャット履歴そのものは正本にしない。後続作業へ必要な確定事項だけを適切なspec、Issue、PR、Decisionへ移す。

## 基本フロー

新規作業状態:

`NEEDS_AUDIT → AUDITED → WORK_ORDER_READY → READY_FOR_IMPLEMENTATION → IMPLEMENTING → AWAITING_REVIEW`

finiteな横断Work Orderは受入完了後`DONE`へ。長期Repository Controlは通常`AUDITED`へ戻す。必要に応じて`BLOCKED`、`NEEDS_REAUDIT`、`PARKED`を使用する。

旧E2Eの`NEW`、`VERIFIED`、`SPEC_CHANGED`は履歴互換としてのみ読む。

## 状態管理の原則

個別作業の詳細状態をdevflow Control Issueへ重複記録しない。repo-local taskは対象repo自身のIssue / PRへ置き、Control IssueにはActive Workと横断状態だけを置く。

`.devflow/WORKFLOW.yaml`は個別タスク一覧ではなく、ワークフロー定義だけを保持する。

各managed Repositoryにはdevflow上で原則1件のopen Repository Control Issueを持つ。

## Templates

- Cross-repository Work Order: `.github/ISSUE_TEMPLATE/work-order.md`
- Repository Control: `.github/ISSUE_TEMPLATE/repository-control.md`

repo-local Issueは対象repoの既存templateを優先する。templateがない場合の最低項目は`docs/operations/REPOSITORY_ISSUE_MANUAL.md`に定義する。
