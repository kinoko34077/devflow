# devflow-test

GitHubを開発状態の正本として使い、ChatGPTで監査・整理、Codexで実装する運用を試すためのテストリポジトリ。

## 管理対象

- `docs/spec/` — 現在有効な仕様
- `docs/decisions/` — 重要な仕様変更・設計判断
- `.devflow/CURRENT_STATE.yaml` — 現在の進捗・次アクション
- GitHub Issues — 作業単位・監査結果・実装指示
- Pull Requests — 実装差分と再監査単位

チャット履歴そのものを正本にせず、現在有効な状態をGitHub側から再取得できることを目的とする。
