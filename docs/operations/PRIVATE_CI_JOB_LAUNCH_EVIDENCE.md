# Private CI ジョブ原典照合（読取専用・#752 R2）

## 目的と境界
Billing Overviewからの課金状態（#1093）と、実際のWorkflowが起動前に拒否されたかを区別する。料金表示だけをPrivateジョブの実行拒否証拠に変換しない。GitHub Actions停止時の独立executorは #541/#610、Private隔離・単一Claim・正式Checkは #639 の別受入であり、本機能は **PLAN_ONLY** まで。

既存`JobLaunchReceipt.authenticated_github_read`はcallerが設定できるboolであり、単体では認証を証明しない。本読取アダプタの真価は、許可済み本人ユーザーのGitHub認証があるホストで一回の固定GETを行い、複数の原典を一致させること。アダプタから返る`receipt`も署名済み・再利用可能な実行権限ではない。これをTrust AuthorityやClaimに昇格しない。

## 取得する固定6原典
1. `GET https://api.github.com/user`：実ログインprincipalのIDと指定オーナーの一致
2. `GET /repos/OWNER/REPO`：実Repository ID、private、Owner IDの一致
3. `GET /repos/OWNER/REPO/actions/runs/RUN_ID`：実runとRepo ID、固定HEAD、完了/失敗
4. `GET /repos/OWNER/REPO/actions/jobs/JOB_ID`：run ID、HEAD、未起動（stepなし、runner割当なし）、完了UTC時刻
5. `GET /repos/OWNER/REPO/check-runs/JOB_ID`：対応するGitHub Actions check-run、固定HEAD、失敗、注記件数
6. `GET /repos/OWNER/REPO/check-runs/JOB_ID/annotations?per_page=100&page=1`：注記件数一致、既存のGitHub課金停止文面を**ちょうど1件**確認

各項目が1つでも不明・異常なら **HOLD**。24時間を超過した実行結果は新たな現行月停止根拠としない。リダイレクト/HTTP認証不足/欠落/サイズ超過/対象不一致でもHOLD。API結果本文・注記・tokenはログと永続化データに出さない。権限の追加・トークン発行は実施しない。

## 本人ローカルでの利用
既存ユーザーの`DEVFLOW_GITHUB_TOKEN`または`GITHUB_TOKEN`が環境変数として既に提供される場合のみ、次を実行できる。

```sh
python -m tools.private_ci_authenticated_job_cli \
  --repository kinoko34077/REPO \
  --run-id RUN_ID --job-id JOB_ID --head HEAD_SHA
```

コマンドライン引数にtokenを渡さない。Tokenが無い場合は新たなログイン処理をせずHOLDで停止。出力は`status/action/reason/requests_attempted/verified_for_dispatch`の安全なJSONのみ（成功でも`verified_for_dispatch=false`）。同じ手順はPythonの`observe_github_job_launch_once`で呼び出せるが、呼出元のTrustは外部で確認する。

2026-11-22に既存認証済み本人PCの`gh api`から **過去実例** `kinotch-default-canary` Run 39373919107 / Job 118467669219 に関するRepo/Run/Job/Check/Annotationsの対応と失敗文面を実照合した。過去のジョブは24時間を超えているので、現在の月次ブロックを新設する根拠には使わない。ライブで直近失敗が存在しない状況では、実運用の新しい月次Blockを勝手に生成しない。

## 非対応・受入後続
本機能はAPIを読取るのみで、新規Actions起動、Hosted再試行、Private code、既設PC task変更、認証管理、支払額、Check書込み、月次flagの設定やClaim切替を行わない。R2の信頼できる月次persistent flag / first-request single-flight / Gateway executor admissionは未受入のままとする。既存データモデルの`authenticated_github_read=True`を使用者が手作りする可能性は残るため、システム全体の実行権限判定に当該boolを単独利用しない。
