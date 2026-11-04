# 検証済み生成物の書戻し v1 — 安全運用・監査Runbook

**適用範囲:** 単一JO Pilotの安全境界と運用手順。親[devflow #384](https://github.com/kinoko34077/devflow/issues/384)・子[#415](https://github.com/kinoko34077/devflow/issues/415)・JO owner[#300](https://github.com/kinoko34077/japanese-orthography/issues/300)が受入判定の正本。**S0–S5は#384でCOMPLETE / ACCEPTED**（S3 [親記録](https://github.com/kinoko34077/devflow/issues/384#issuecomment-6106230186)、S4 [親記録](https://github.com/kinoko34077/devflow/issues/384#issuecomment-6106251550)、S5 [最終受入](https://github.com/kinoko34077/devflow/issues/384#issuecomment-6106565389)、[PR #429](https://github.com/kinoko34077/devflow/pull/429) / post-main Required [#38120459183](https://github.com/kinoko34077/devflow/actions/runs/38120459183) SUCCESS）。受入範囲は元の単一JO Pilotであり、他repoへのrolloutは[#386](https://github.com/kinoko34077/devflow/issues/386)が別に管理しNO_GO。以下の受入前草案は履歴として保持する。  
**trusted devflow pin:** `f886877e7110f2499125ecc6e07294798c33fe93`。JO CallerはこのSHAを`uses`／`devflow_sha`へ両方固定し、devflow mainへの別案件コミットで自動更新しない。

## 実証済みの安全運用と再開条件（2026-10-11）

1. **通常起動:** JO main Callerの手動`workflow_dispatch`、`mode=dry-run|write`、対象PR branch・正確な`expected_head`を指定。実行対象は許可レシピとJSON1件に限定し、repo/actor/branch/PR/保護状態をGitHub APIで再認証する。想定外のmodeはCaller job-level allowlistでSKIPPEDとなる。SKIPPEDは**受入成功の証拠ではない**。
2. **権限分離:** produceはreadのみ・secretsなし、固定recipe生成物を検証してZIP+manifestへ梱包する。writerのみ`contents:write`、`actions:read`、`pull-requests:read`。writerは未信頼のZIPやJO sourceのコードを実行せず、認証したfirst-party run/attempt＋Caller SHA/pin＋ZIP/path/mode/digestを検証する。
3. **更新と競合:** 1 open same-repo PR＋expected HEAD、未保護scratch branchでCAS更新。commit parentはexpected HEAD、`force:false`、事後readback必須。競合/不明結果は停止し、新たな受入なしで再実行しない。
4. **同一receiptの重複防止:** 受入専用`write-replay-test`は一時的な限定モードで実証を終えた。Run [#38072681245](https://github.com/kinoko34077/japanese-orthography/actions/runs/38072681245)は初回`COMMITTED`→同一runner/run/attempt/manifestで2回目`NO_OP_REPLAY`、追加書込0。**恒常Callerには同モードを残さない**。[PR #308](https://github.com/kinoko34077/japanese-orthography/pull/308)でUI選択肢とAPI経由のジョブ起動可能性をともに除去済み。
5. **exact writer HEADのテスト:** token書込は通常のPR CIを自動起動しない。またPRイベントの通常checkoutは仮想マージになる場合がある。受入では一時的read-only手動[Verify #38078533001](https://github.com/kinoko34077/japanese-orthography/actions/runs/38078533001)のpilot-head両OSがwriter commit`87557afe9d3585252c94cf5352515943323dd708`を直接checkoutし、SHA assert→全check→Ubuntu buildを成功させた。GitHub run自体のhead SHA（手動起動元main）とは区別。通常運用で必要な場合も、権限変更なく**実際のcheckout SHA**で必要CIを判定する。
6. **rollbackと清掃:** 非強制復旧commit`ce4042b9868141f5b0736b1063a22a2748d721c5`の親はwriter commitのみ、変更JSON1件で元blobへ復元。scratch PR#304は未統合Close。臨時Verify入口は[PR #307](https://github.com/kinoko34077/japanese-orthography/pull/307)で旧blobへ完全復元し、postmain [#38113279718](https://github.com/kinoko34077/japanese-orthography/actions/runs/38113279718) Ubuntu/Windows成功。Callerの一時Replayモード撤去後のmain CI [#38116891632](https://github.com/kinoko34077/japanese-orthography/actions/runs/38116891632) SUCCESSは#384 S3 Exitの受入済み証拠であり、未完了ゲートではない。
7. **負例と制約:** fork/偽run/actor/recipe/source/ZIP path・symlink・submodule・ZIP bomb・stale HEAD/race/replayの負例はdevflow全862 tests中の87 unit/staticで検証し、旧stale HEAD拒否Run [#37976552219](https://github.com/kinoko34077/japanese-orthography/actions/runs/37976552219)で実際のfail-closedも検証済み。Unit/staticの成功を、危険な特権live payload投入の成功と偽らない。ほかのrepoやrecipeへの展開・credential・settings・deploy等は別Human gate。
8. **完了判定:** 初期PilotのS3 ExitはJO Owner #300とdevflow #415のrun/commit/review/CI/rollback/清掃の全根拠を読み直してから親#384へ記録。S4は独立Review・統合済コードのexact SHAとpostmain CI・権限境界を新規監査。S5は受入条件が揃ってから仕様、Runbook、両Control、3つのIssue/Cursorへ確定情報だけを反映。S3成功とS4／S5は独立の状態であり、一般展開#386は自動受入しない。

---

## 受入前草案の整理：歴史的判断と現行運用の境界

以下は**S2〜S3設計時点の検討内容**のうち、現行の運用手順と重複しない原因・採否・停止条件を統合した記録。**S3/S4/S5が未受入という当時の表現は失効**している。現行の受入、正しい実行方法、最終SHAと個別の証拠は本書冒頭、および[親#384](https://github.com/kinoko34077/devflow/issues/384)・[子#415](https://github.com/kinoko34077/devflow/issues/415)・[JO #300](https://github.com/kinoko34077/japanese-orthography/issues/300)に従う。旧版全文は本ファイルのGit履歴（修正前blob `478eda4dbfb01e3fca14a2b95159ab9089552657`）に保持する。他repo展開は[別owner #386](https://github.com/kinoko34077/devflow/issues/386)であり、自動受入しない。

### 1. 当時の設計問題と採用境界

**信頼済みSHAとPilotの循環依存：** S3の終了条件には実Pilotが必要だが、権限付きwriterは「mainへ受入済みのコードSHA」しか読み込めず、当初のS4 merge待ちでは両条件を同時に満たせなかった。**未レビューのPRブランチをwriterにロードして先にPilotを通す案、Pilot未実施を成功とみなす案は不採用。** 当時の解決案は、最終統合差分のセキュリティレビュー・Required CI・実装者以外の独立レビューと明示Human承認を前提に、修正版を原子的にbootstrap mergeした後、固定main SHAで限定Pilotを実施し、S4を改めて最終監査する段階分離。途中の脆弱なmainを作る#385/#390/#387/#391の逐次mergeは不可。bootstrap mergeだけではS3/S4/S5の受入にならない。実際の最終採否と完了証拠は#384の受入記録が優先する。

**許可された唯一の当初Pilot：** `kinoko34077/japanese-orthography#300`のrecipe `jo-orthography-accounting@1`、生成対象 `data/reports/orthography-v2-source-accounting.json` 1件。対象はfirst-partyのdefault branchで明示的に起動する`workflow_dispatch`と、`artifact/devflow384/`内の未保護scratch branch上の単一open PR、exact expected HEAD。別repo/recipe/path、fork/PR起点の権限付き自動実行、`actions:write`、PAT/GitHub App、settings/rulesets/protection変更、secrets、外部公開は別承認であり、このPilotには含まれない。

### 2. 信頼境界と停止条件（重複仕様を一元化）

| 境界 | 受入済み設計の必要条件・拒否条件 |
| --- | --- |
| **生成側** | `produce`は`contents:read`のみ、secretなし・checkout時`persist-credentials:false`。固定recipeの生成/検証だけ許容し、ZIP/manifestは全面的に**低信頼入力**。 |
| **書込側** | `write`だけが`contents:write`、`actions:read`、`pull-requests:read`をjob単位で使用。対象repoのPRコードcheckout、`npm`/build/install/scriptの実行は禁止。共有helperとworkflowはJO Callerの`uses`／`devflow_sha`が示す**同じ受入済みdevflow SHA**のみ。非レビューHEADや中間のB1問題を持つtreeは不可。 |
| **run由来の認証** | manifest中の`actor/source_sha/producer_run_id/workflow_ref`は自己申告。GitHub RESTのrun/workflow、実際のrunner context、run ID/attempt、actor、default branch、workflow pathと一致させる。変動する`workflow_sha`を静的pinせず、**当該workflow SHA時点のCallerの内容**から`uses`と`devflow_sha`が各1個・同一SHA、`workflow_dispatch`以外のtrigger・`secrets`・`run:`なしを検証し、run固有`producer_workflow_ref`を導く。 |
| **アーカイブ/パス** | ZIP原bytes・SHA256・size・count・compression ratio・symlink/exec mode・重複/未知/不足path・parent traversal・`.github/`などの不許可pathを拒否。既存Git treeの各親要素とblob `100644`を検査し、固定path以外・不意の削除を禁止。 |
| **書込み競合/再実行** | commit parentはexact expected HEAD、事前再取得、`force:false`でCAS、事後HEADと差分のreadbackが必須。競合・結果不明は停止して新たなadmissionへ戻す。同一runner/run/attempt/manifest・単一parent・正確なbytesを照合できたときだけ`NO_OP_REPLAY`。新HEADへ追随するforce pushは禁止。 |
| **CI/レビュー** | GitHub `GITHUB_TOKEN` pushだけではPR CIは自動起動しない。PRイベントcheckoutの仮想merge SHAと、writerの**実際の新HEAD**を混同しない。新HEADで正規Ubuntu/Windows Required検証を明示的に行い、runと検査SHAを記録。別経路の`repository_dispatch` Checkがdefault branchに付けば新HEADのRequired通過としない。`workflow_dispatch` RESTの`actions:write`は未許可では使用不可。 |
| **独立監査** | 未解決のsecurity finding、reviewed SHAとの不一致、現行HEADのRequired失敗、Human特例承認欠落、untrusted caller/別repoからの到達、Pilot/rollback未確認はいずれも当該段階HOLD。実装者が別モデルのレビューを偽装しない。単一Pilotの承認をfleet rolloutへ拡張しない。 |

### 3. 当時のS3〜S5出口と復旧の整理

**S3段階：** trusted codeの受入と実Pilotを分ける。dry-run→non-force write→同一receipt replay（`COMMITTED→NO_OP_REPLAY`、追加書込0）→expected HEAD競合/悪意ある入力の拒否→rollback→一時PR/permission/workflow清掃→writer新HEADのexact CIまで完了して初めて限定Pilot受入。単にbootstrap mergeしただけならPilot成功とはしない。専用`write-replay-test`は受入検証後に恒常Callerから**UI選択肢とAPI起動経路の両方**を除去（JO [PR #308](https://github.com/kinoko34077/japanese-orthography/pull/308)）。実証runは冒頭を参照。

**S4段階：** 統合時点のPR/base/HEAD、変更ファイル、Required CI、正式Review、Review Readiness、未解決threads、runner/job permissions、JO Caller pinと当時の実行証拠を再取得。変更したHEADで旧review/CIを流用しない。bootstrap時点のコードから変更がなければ二重mergeしない。merge後main SHAとpost-main CIを確認。実際のS4受入済み範囲は#384正本を参照。

**S5段階：** Pilot・Review/CI・権限・cleanup・復旧証拠を最終照合してから、#384、Control #16、JO #300/Control #180、`docs/spec/GENERATED_ARTIFACT_WRITEBACK_V1.md`、Task Cursorへ**現実に成立した事実だけ**反映。#291/#210/PR #296やdeploy/Pages/Phase5/6を勝手に変更しない。機能受入と新しいrepoでの展開は別ゲート。

**異常時：** 生成/検証失敗ならwriterは起動しない。run/actor/workflow/manifest不一致やZIP/path/mode失敗は入力を信用側へ書き換えず拒否。CAS競合は新admissionに戻す。commit object作成後にref更新拒否なら未参照objectが残っても強制pushしない。ref成功後にCIが未起動・失敗ならmergeをHOLD。実行途中で止まれば#384/#300と唯一のTask Cursorから最後の受入済み単位だけを復元。撤回はPR close／新規revert commitとし、shared historyはrewriteしない。証拠としてrun ID/attempt、recipe/version、source/expected/new HEAD、manifest SHA、PR、CI、Review、差分・rollbackと未完了点を残す（secret/raw tokenを記録しない）。

### 4. 実装した入口（当時の仕様・現行pinは冒頭優先）

- 共通workflow: `.github/workflows/generated-artifact-writeback.yml`。top-level `permissions: {}`、`produce`は固定recipeを`tools/generated_artifact_pilot.py`の`RECIPE_NPM_SCRIPT`経由でのみ生成し、`write`は上記認証/ZIP/CASを担当。
- JO Caller雛形: `docs/operations/templates/verified-artifacts-pilot.yml`（devflowでは非稼働）。JO側のreviewed default branchでのみ起動する。固有の受入済み`<DEVFLOW_SHA>`を`uses`と`devflow_sha`へ固定し、意図しないpin更新を行わない。
- 初期のexact-HEAD CI確保案：`actions:write`を新たに付与せず、Humanによるscratch PRのclose/reopenなど**GitHubの本来のPRイベント**で検証。認証・権限・実行境界を別tool/迂回経路で無効化しない。

