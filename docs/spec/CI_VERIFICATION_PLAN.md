# CI共通検証判定 — R1初期契約

Owner: [devflow #1121](https://github.com/kinoko34077/devflow/issues/1121)。状態: R1初期実装候補。CI省略の実運用は未接続。上位規則は [運用Manual §5.2/6](../operations/AGENT_OPERATING_MANUAL.md) 。本書は共通判定の技術契約のみを所有する。

## 責務
必要な保証と、現在有効な同等証拠の差だけを追加検証する。MCP・CLI・Workflowは同じ `tools.ci_verification_plan.assess_verification` を参照する構造とし、別実装しない。今回は純粋判定を先行。既存のReview、Goal Plan、metadata validator、GitHub取得、release gateは各ownerのまま。信頼済み取得・要求生成・実行への接続はR2/R3。自己申告の証拠は採用しない。

## 入出力
- Requirement = repository + guarantee + identity（保証を変える全入力の識別値）。identityは保証ごとにownerが定義し、完全性をcollector/adapterが保証。固定次元数・全repo共通の環境値を要求しない。codeなら実候補tree、検証定義、環境、依存等。metadataなら対象本文・validator等。外部状態なら対象・鮮度。意味のある変更だけが再検証を要する。
- Observation = 同じRequirement、現在の試行のoutcome、原典参照、証拠期限（時刻で失効しない場合のみNone）。認証・対象/実tree・実ジョブ・試行・鮮度の確定はcollector責務。古い失敗とその後の成功を同時にcurrentとして渡さない。不完全な取得から完全な証拠集合を捏造しない。
- Decision = action、reason、必要時証拠参照。純粋判定、書込/ネットワーク/保存/認証なし。

| 結果 | 意味 |
|---|---|
| HOLD | 要求の同定/判定時刻が不明。当該保証を省略せず、回復・代替を検討 |
| WAIT | 現在の同等試行がqueued/in_progress。二重起動回避候補。成功ではない |
| RUN | 有効同等証拠なし、または現在の証拠が非成功・矛盾・参照欠落 |
| REUSE_CANDIDATE | 全入力同等、現在の成功証拠あり、期限内。承認済みconsumerで適用可否を別確認 |

異なるrepo/保証/identityは流用しない。期限切れと時刻不明の証拠は使わない。現行の同等試行が進行中なら完了を観測し再判定。進行中を成功扱いしない。現在の失敗/取消/skipped/未知を成功として扱わない。新しい実base・統合候補・テスト・環境・依存が変化した場合は該当保証を再検証。native必須checkの失敗、正式Review、実環境/公開/不可逆操作、安全・権限条件はこの判定で解除できない。判定器だけでは証拠の真正性やidentity完全性を証明できない。

## 初回検証と非目標
`tests/test_ci_verification_plan.py` の代表同等tree・metadata独立・全入力差異・別repo/保証・非成功・進行中・矛盾・期限境界・欠落。GitHubのRequired workflowと既存MCP gateは変更しない。効果計測はR4で実際のjob起動数、runner job秒、判定overheadを比較する。今回は追加DB・認証・API・固定tool数・互換移行・個別repo適用なし。
