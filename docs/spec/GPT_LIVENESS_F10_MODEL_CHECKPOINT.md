# F10：GPTのアクティブターンでのPING選択と応答（安全境界）

正本：[devflow #681](https://github.com/kinoko34077/devflow/issues/681)、親仕様 [#516](https://github.com/kinoko34077/devflow/issues/516)、通信 [#503](https://github.com/kinoko34077/devflow/issues/503)。

## 目的・非対象

GPTモデルが**実際に稼働中の自身のターン内で**未回答PINGを読取り、nonce/コメントIDを明示選択してからKAEPの相関ANSWERを発行する。既存 `tools.gpt_liveness_mailbox`、KAEP codec、F4 issue enrollment、既存 `send_reply` とGitHub原典readbackを再利用する。

スケジューラ、GitHub Actionsからの自動PING発行、停止中ChatGPT会話の起床、外部ホスト、token/permission/Claim、有料Provider、実配信は**本変更の対象外**。特に外部サイドカーが自動返信してもGPTが処理した証拠にはしない。GitHub actorだけでモデル本人性・元チャットの継続性を暗号学的に証明しない。

## GPTが稼働中のときの2段階チェックポイント

1. モデルターンから、認可済みのGitHub read環境で、実際の対象 `repository` と `issue` を指定して **READ ONLY** 呼出しを行う：

   ```sh
   python -m tools.gpt_liveness_mailbox --repository kinoko34077/devflow --issue 554
   ```

   これは**例示**の旧F8E #554（登録無効/期限切れ）であり、現行のPINGを取得したり再有効化したりする指示ではない。新規の有効登録が別のOwning Issueへ正式に設定されるまで自動返信は実行されない。

2. 返った `MAILBOX_CHECKED` の `unanswered_pings` から、GPTが対象PINGについて `comment_id`, `nonce`, `session_id`, `turn_id`, `expires_at` を**自身で照合**し、処理モード・現在のcheckpoint・必要なら有限のlong-running期限を決定する。 `nonce` は既存の公開Challenge上の相関子であり、認証資格情報ではない。対象がない・欠落している・期限切れなら返信しない。

3. GPT自身が正当な最新Challengeを選んだ**後だけ**、同じターンの許可されたツール呼出しで `--respond --checkpoint ... --reply-to-comment-id ID --reply-to-nonce NONCE` を指定する。検証だけなら `--send` は省略。GitHubへのPOST+readbackが必要で承認範囲内のときだけ `--send` を明示追加する。スクリプトは直前に原典Issue・全コメントを再取得し、最も新しい未回答PINGとの ID/nonce、登録期限、session/turn、既存回答を再確認し、不一致なら `PING_SELECTION_STALE_OR_MISMATCHED` 等でブロックする。

4. `SENT_AND_READ_BACK` は承認されたモデルターンのツール呼出しにより特定PINGへのGitHub返信が登録・再読込された**通信証拠**。出力の `model_selection_observed_in_tool_arguments=true` は**呼出し時の明示選択**を示すだけで、自動モデル起動・本人性保証ではない。下位証拠のラベル `MODEL_TOOL_RESPONSE_OBSERVED` と暗号学的独立証明は別に扱う。

## Fail closed / 再現テスト

モデルターンの `--respond` と実際に読んだ `comment_id`＋32桁 `nonce` の全てが揃わなければ返信不可。最新PINGが変化した場合、旧PINGの指定を**自動的に新PINGへ振替えない**。回答済・ターン更新・期限切れ・誤宛先・GitHub原典未確認でも返信不可。読取だけではIssueを書き換えず、誤検出によるClaim失効・代替AIへの作業移管はしない。

`tests/test_gpt_liveness_f10_model_selection.py` に positive dry-run/simulated explicit send、未選択・異nonce/別コメント・新PING競合・ターン変更・回答済・期限超過・デフォルトGET-onlyを固定する。定常的5分PING・無人のChatGPT実行環境・本人性を伴う実受信・費用上限と失効管理の全受入は引き続き #681 H3/H4。

