# devflow-test

GitHubを開発状態の正本として使い、監査・実装・再監査をIssue / branch / Pull Request上で追跡する運用を試験し、現在は横断開発管理のCurrent State Hubとして運用するリポジトリ。

実装主体は固定しない。ChatGPTからGitHubを直接編集しても、Codexや別の実装者を使っても、同じIssue / PRの状態と履歴を参照できることを前提とする。

## Cross-repository role

このRepositoryは、複数Repositoryを横断するCurrent State Hubである。

GitHub Projectは表示・俯瞰用の派生層であり、live operational stateの正本ではない。Projectを読めない実行環境でも、このRepositoryから作業を継続できることを要件とする。

### Read order

1. `docs/spec/CROSS_REPOSITORY_DEVELOPMENT_CONTROL.md`
2. `.devflow/WORKFLOW.yaml`
3. 関連するopen Repository Control Issue / 横断Issue
4. 対象RepositoryのCURRENT_STATE / Issues / PRs / specs

個別Repositoryの詳細仕様や実装状態をここへ複製せず、横断的に必要な現在状態・次Action・参照先だけを保持する。

## 正本の分担

- `docs/spec/` — 現在有効な横断仕様
- `docs/decisions/` — 後続判断へ影響する重要な仕様変更・設計判断
- `.devflow/WORKFLOW.yaml` — 状態遷移・Repository State・運用ルールの定義
- GitHub Issues — Work Order、Repository Control、横断案件、監査結果、現在の作業状態
- Pull Requests — 実装差分、検証結果、再監査、レビュー状態
- Git commits — 変更の実体と時系列
- 各個別Repository — そのRepository固有の仕様、CURRENT_STATE、Issue / PR、コード
- GitHub Project — 上記正本から自動反映する表示・俯瞰層

チャット履歴そのものは正本にしない。チャットで決まった内容のうち、後続作業へ必要なものだけを仕様、Decision、Issue、PRへ移す。

## 基本フロー

新規の作業状態は以下を使用する。

`NEEDS_AUDIT → AUDITED → WORK_ORDER_READY → READY_FOR_IMPLEMENTATION → IMPLEMENTING → AWAITING_REVIEW → DONE`

必要に応じて `BLOCKED`、`NEEDS_REAUDIT`、`PARKED` へ遷移する。

旧E2Eで使用した `NEW`、`VERIFIED`、`SPEC_CHANGED` は履歴互換として読み取るが、新規作業の標準状態には使用しない。

## 状態管理の原則

個別Issueの現在状態をリポジトリ内の別ファイルへ重複記録しない。個別作業の状態・次アクション・監査記録はIssue / PRを参照する。

`.devflow/WORKFLOW.yaml` は個別タスクの状態表ではなく、ワークフローそのものの定義だけを保持する。

各管理対象Repositoryにはdevflow上で1件のRepository Control Issueを持ち、横断管理に必要な最小限の状態と参照先だけを記録する。

## Work Order

実装開始前に、Issue上で最低限以下を固定する。

- Objective
- Scope
- Acceptance criteria
- Non-goals
- Verification
- Audit base
- Related specs / decisions

テンプレートは `.github/ISSUE_TEMPLATE/work-order.md` を使用する。

Repository Controlには `.github/ISSUE_TEMPLATE/repository-control.md` を使用する。
