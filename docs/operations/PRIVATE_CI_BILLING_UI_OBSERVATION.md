# 個人GitHub課金画面の読み取り専用観測（#752）

## 目的と証拠

ActionsのREST使用量集計ではPublic割引と個人Compute同梱枠を分離できない場合がある。既存 `private_ci_billing_readonly.py`、job launch分類、LocalBillingObservationStoreは変更しない。本機能はログイン済みChromeの個人Settings→Billing and licensing→Overview→Actions、Budgets and alertsの表示を読み取り、別の観測証拠として同じ型のJSONを返す。課金、設定、Claim、Private executor、Checks書戻し、実ジョブ起動には作用しない。個人課金値はPublicリポジトリ、公開CIログに格納しない。

## 呼出し

Windows対話ユーザーの既存Chrome（GitHubログイン済み）で、同じディレクトリに `private_ci_billing_ui.py` と `private_ci_billing_ui.ps1` を配置する。依存はPython 3.10+とWindows PowerShell/UI Automation。管理者実行、認証情報取得、新規ブラウザプロファイル、リモートデバッグポートは不要。

- 最新値直接取得: `python -m tools.private_ci_billing_ui --account OWNER --cache PRIVATE_PATH`
- 既存の認証済み非公開経路から渡されたキャッシュの確認: `python -m tools.private_ci_billing_ui --account OWNER --cache PRIVATE_PATH --read-cache --status-only`
- 固定内容のJSON要求: `python -m tools.private_ci_billing_ui --account OWNER --cache PRIVATE_PATH --serve-request REQUEST_JSON --status-only`
- 非公開同期フォルダの固定依頼マーカー（次節）: `python -m tools.private_ci_billing_ui --account OWNER --cache PRIVATE_PATH --serve-marker-dir PRIVATE_DIR --status-only`

CLI出力はJSON。観測成功0、失敗2。キャッシュはUTC当月、12時間以内のみ有効。失敗した新観測はUNKNOWNとして上書きし、以前の値を最新成功と偽らない。UI言語/表示構造、Chrome対話セッション、アカウントまたはURL照合、権限、同期等が不成立ならUNKNOWN。ブラウザ表示値の目的上、grossとActions個別金額の更新タイミング差を勝手に合算・修正しない。

## 非公開同期の要求/応答

既存認証で書き込みを許可された所有者限定のフォルダを使用（共有権限・新たな認証は付与しない）。公開repoを依頼・生データの保存先にしない。固定マーカーを1ファイル用意し、非公開コネクタから既存ファイルを `billing-request-YYYYMMDDTHHMMSSZ-<32桁小文字hex>.request` にリネームする。日時はUTC、要求期限30分。ファイル内容を開かず、固定名の操作だけを受け付ける。idleファイル名は `billing-request-idle.request`。同一マーカーの重複、期限切れ、不明な操作は処理しない。
対話PCで既に認められた固定の実行入口から `--serve-marker-dir` を呼ぶと、その1件のみ観測し、明示された非公開出力JSONに同じrequest_idを返す。依頼から読み返したJSONのrequest_idを照合する。応答を読んだ後、固定マーカーをidleに戻してよい。キャッシュの上書き/同期でDriveファイルIDが変わり得るため、出力ファイルは指定フォルダの固定名で再検索する。マーカーと結果には実行権限がなく、任意コマンド、URL、他アカウント、資格情報、実行ファイルを指定できない。

対話ホスト以外のCIは承認済み経路から配布された結果の検査のみ可能。GitHub-hosted ActionsのGITHUB_TOKENまたは新規secretで個人課金ページへアクセスできると仮定しない。CIでは金額の出力・アーティファクト公開を避ける。Private Actions停止時にもホスト側観測はActionsに依存しない。

## 判定契約

- INCLUDED_COMPUTE_AT_OR_ABOVE_LIMIT_AND_BUDGET_BLOCKED: 表示上Compute使用が同梱枠以上、個人Actions予算のUsage blocked表示あり。
- INCLUDED_COMPUTE_AT_OR_ABOVE_LIMIT: 表示上Computeが同梱枠以上だが予算の明示停止は確認できない。
- WITHIN_INCLUDED_COMPUTE: 表示上Computeが同梱枠未満。追加予算の停止表示と独立に判定し、特定ジョブ実行可能とは断定しない。
- UNKNOWN: 不完全、期限超過、不一致、観測不能。実ジョブの起動拒否証拠にも代替実行許可にも変換しない。
すべて verified_for_dispatch=false。金額はUSDの10進文字列、時刻はUTC、請求月と証拠種別を保持。Secrets/cookies/raw DOMは保存しない。
