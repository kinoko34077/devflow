# devflow-test

GitHubを開発状態の正本として使い、監査・実装・再監査をIssue / branch / Pull Request上で追跡する運用を試すためのテストリポジトリ。

実装主体は固定しない。ChatGPTからGitHubを直接編集しても、Codexや別の実装者を使っても、同じIssue / PRの状態と履歴を参照できることを前提とする。

## 正本の分担

- `docs/spec/` — 現在有効な仕様
- `docs/decisions/` — 後続判断へ影響する重要な仕様変更・設計判断
- `.devflow/WORKFLOW.yaml` — 状態遷移と運用ルールの定義
- GitHub Issues — 作業単位、Work Order、監査結果、現在の作業状態
- Pull Requests — 実装差分、検証結果、再監査、レビュー状態
- Git commits — 変更の実体と時系列

チャット履歴そのものは正本にしない。チャットで決まった内容のうち、後続作業へ必要なものだけを仕様、Decision、Issue、PRへ移す。

## 基本フロー

`NEW → NEEDS_AUDIT → AUDITED → WORK_ORDER_READY → READY_FOR_IMPLEMENTATION → IMPLEMENTING → AWAITING_REVIEW → VERIFIED → DONE`

例外状態は `BLOCKED`、`SPEC_CHANGED`、`NEEDS_REAUDIT` とする。

## 状態管理の原則

個別Issueの現在状態をリポジトリ内の別ファイルへ重複記録しない。個別作業の状態・次アクション・監査記録はIssue / PRを参照する。

`.devflow/WORKFLOW.yaml` は個別タスクの状態表ではなく、ワークフローそのものの定義だけを保持する。

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
