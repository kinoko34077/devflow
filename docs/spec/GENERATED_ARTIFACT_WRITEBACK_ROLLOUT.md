# 検証済み生成物の段階的な複数リポジトリ導入 — R1制御契約（提案）

> Status: **DESIGN DRAFT / NO WRITER ENABLED**（2026-10-12）
>
> Owner: [devflow #465](https://github.com/kinoko34077/devflow/issues/465) / rollout parent [#386](https://github.com/kinoko34077/devflow/issues/386)。
> 受入済みv1の正本は [#384](https://github.com/kinoko34077/devflow/issues/384) と [生成物書戻し仕様](GENERATED_ARTIFACT_WRITEBACK_V1.md)。
> この草案は権限付与、稼働許可、deploy/publicationを伴わない。

## 1. 問題と非対象

JO単一Pilotの受入済み共通実装 `f886877e7110f2499125ecc6e07294798c33fe93` は変更しない。
当該SHAの `.github/workflows/generated-artifact-writeback.yml` / `tools/generated_artifact_pilot.py` は、対象repository、caller、`generate:orthography-accounting`、JO検証script、`artifact/devflow384/`、許可1ファイル、1MiB上限を固定するため、任意のmanaged repositoryを受け付けない。既存v1を「fleet-ready」と呼ばない。

目的は**安全な固定recipeを個別に登録してGitHubネイティブの書戻しを実行すること**であり、汎用のshell runner、自由なファイル転送、チャットモデルへのtokenやbinaryの中継ではない。
execution-coordinatorのclaim/lease/fencing、release、Pages/Cloudflare deploy、credential管理は非対象。

## 2. 段階と権限

| Gate | 内容 | 許可条件 |
|---|---|---|
| R1 Design | 固定registry、API入力、違反拒否、候補選定、実装設計 | 本Draft/Issueの検討のみ。writer起動不可 |
| R2 Read-only | レシピ別のgenerate・validate・packager、静的negative test | `contents:read` のみ、secretなし。生成物をGitへ書込まない |
| R3 Trusted code | 新規共有workflow/helperへの独立security review + HEAD固定CI | 現在のJO SHAとは別に審査。権限付きmain有効化は明示Human gate |
| R4 Per-repo Pilot | 個別owner/recipe/path/PR branchを固定してdry-runと限定write | repo/job毎のHuman approvalと実permissions / ruleset観測必須 |
| R5 Acceptance | exact write HEAD CI、NO_OP_REPLAY、競合拒否、rollback、cleanup | それぞれのownerが受入決定。別repoへ横滑りさせない |
| R6 Fleet | 独立repo2件とチャット環境2種類、disable/rollback | 新たなfleet-wide可否の明示判断。自動一括有効化しない |

`contents:write`を使うjob、shared credential、token、settings、外部publicationは、R1設計承認や汎用の「段階導入」指示から自動的に許可されない。

## 3. 静的なTarget Recipe Registry

登録値は**review済みtrusted SHAのコードまたは定数データ**として配布し、producer artifact/PR head/comment/チャット文面を登録元にしない。プロトコル上、**run中に任意registryをネット取得しない**。各entryは最低限次を持つ。

| 分類 | 固定する値 |
|---|---|
| Target | GitHub repository full name、既定branch、forbidden branch、`artifact/<id>/`固定接頭辞 |
| Admission | 許可actor、default-branch上の固定Caller path、signed-by-GitHub実run/attempt/workflow_sha、open same-repo PR、exact expected SHA |
| Recipe | ID/version、fixed generator entry、必要なら固定Node/Python version、source lockの形式、dependency取得条件 |
| Outputs | 正確なpathの非glob集合、max file/count/total/archive/ratio、mode/regular-file制約、必要なnotice/hash |
| Validation | 固定test/checkコマンド、expected output hashesの判定方法、postwrite exact-head CIの既存正規入口 |
| Recovery | 明示的なdry-run、forward-only rollback、scratch close、認証されたreceipt replay / status reporting |

安全なtrusted固定値は、runtime入力 `repository`、`recipe_id` だけで選択する。未登録の組合せは拒否し、任意の `script`、`command`、`path`、`limit`、`runner`、`workflow`、`secret` をCaller引数として受け付けない。固定値の更新には新たなレビュー済みdevflow SHAを要する。変更済みSHAへの追従を `@main` で行わない。

**入口分離:** 新しい受入済みshared workflow/helperをJO既存Pilotと別名にし、古いJO Callerの `uses`／`devflow_sha` は変更しない。新機能のcaller実装はrepoごとに1件だけ固定し、workflow_dispatch起点以外、fork PR、push、issue_comment等による権限付き自動起動を禁止。choice UIだけを信頼せずjob-level exact-mode allowlistで拒否する。

## 4. 信頼とデータの流れ

```text
default branch固定Caller（入力: recipe_id, target_branch, expected_head, mode）
  -> trusted registryによるtarget/recipe admission（不適合は拒否）
  -> [PRODUCER] target PR exact SHA checkout / read-only / no secrets
       固定recipe generate -> 固定tests -> manifest + ZIP（すべて低信頼）
  -> [WRITER] 独立したtrusted SHAのみcheckout / target sourceは実行しない
       first-party run+attempt+actor+workflow identity再認証
       Caller contentとpinを正確に照合
       manifest・archiveのbytes/digest/path/mode/size/出典照合
       exact PR branch HEAD + ruleset/保護/default拒否
       parent固定commit -> non-force CAS -> readback / receipt
  -> exact writer HEADのCIを別途確認 -> review -> rollback/cleanup
```

GitHubのrun上の `head_sha` と、check jobが実際にcheckoutする書込HEADを混同しない。特に `GITHUB_TOKEN` のPR branch更新は通常のCIを自動起動しないため、明示的な正規検証経路が必要。実CI対象SHAの証明ができない場合、実writeが成功していてもPilotは未受入とする。

writerはmanifestをauthorityに昇格せず、GitHub RESTとtrusted registryから完全に再導出する。入力不明・ref移動・保存結果不明・replay receipt不一致は**fail-closed**。更新成功後に検証や同一receipt再観測が失敗したときは、書込済みという事実を保持し、成功と偽らずSTOP/復旧へ進む。強制push禁止。

## 5. 初期候補・導入順

1. [IDS-Composit #11](https://github.com/kinoko34077/IDS-Composit/issues/11)：`known:merge` で `data/known/generated/known-index-v0.2.json` と `data/known/reports/known-index-v0.2.json` を生成。入力3種類のsource artifactは固定source/provenanceを保つ。2026-10-12のGitHub Contents読取で、**merged JSON = 12,932,054 bytes、対応report = 5,341,134 bytes、合計 = 18,273,188 bytes**と判明（実データはファイル別Git blob）。生成scriptはこの2 pathを同時に出力するため、片側だけを受入対象にせず、source一致とoutput検証を確認して**原子的な2-path候補**として評価する。CHISE入力は6,130,537 bytesでありmerged JSONとは区別。size limitは実生成と容量安全証拠に基づき別途固定し、JO 1MiB上限を暗黙再利用しない。GitHub APIでは公開repo rulesets=空配列を観測したがmain protection取得はpermission不足403、**protection状態はUNVERIFIED**。main pushはPages公開を誘発するため、merge/deployのHuman gateを維持。
2. `kinotch-api`：`build:text-snapshot` は複数の生成ファイルを出力するが、GitHub Contentsで確認した `rules.generated.mjs` は21,427 bytes、`metadata.generated.mjs` は511 bytes、`text-transform.iife.js` は10,922 bytes。通常のGitHub Contents/Git Data APIで十分処理可能な規模なので**Wave2確定から除外し、導入便益は未成立**。Node要求も26.10.xと既存JO workflow Node22が異なる。source lock・auth#9に影響する拡張を行わない。
3. `standby-display`：`kinotch-api`ソースから2 clientとsha256 2件を同期するが、主要ファイルは約10.7KB・6.6KBで通常API更新が可能。cross-repo source lockとmainのProduction/Pages公開境界も増えるため**書戻しPilotとしては後順位**。
4. `txt-auto-replace` は大容量binary辞書を保有するが、第三者由来圧縮辞書はrepoで決定的再生成された成果物と未証明。既存再分類scriptにmachine固有Downloads絶対pathがあり、現在のままGitHub Actions recipeにできない。**第二Pilotには不採用**。その他repoも大容量で再生成可能な**Git管理対象**の正確なartifactが検証できるまで未登録。研究snapshot、秘密情報、ユーザー入力、通常のdistや一時実行ログを自動的に許可しない。

## 6. 自動テスト・受入基準

- Registry: unknown repo/recipe/version、CLI文字列混入、出力path追加、metadata源がPRデータ、source SHA不一致、曖昧な複数entry、size上限違反を全て拒否。
- Auth: 別actor、fork、PR comment、wrong workflow/caller、run ID/attempt/source ref偽装、reviewed pin不一致、workflow trigger変更、default/protected branch、no open same-repo PRは拒否。
- Data: ZIP重複/未知/欠落、path traversal、symlink/submodule、executable bit、digest不一致、ZIP爆弾、破損manifest、巨大archiveを拒否。
- Update: moved expected HEAD、parallel writer、unknown update result、readback不一致、wrong receipt replayを拒否。NO_OPはfresh NO_OPと同一receipt NO_OP_REPLAYを混同しない。
- Execution: source jobはwrite/secretsなし、privileged writerはtarget code/ZIP codeを実行しない。rollbackはforward-only。実write後のexact-head CI+Reviewを証明。
- Regression: JO既存受入pinの動作とstatic/CI testsは保持。新たなrepoへのトリガーや権限継承が観測された場合は不受入。

### 記録

実run ID/attempt、source/write HEAD、manifest checksum、commit parent/readback、正式CIの**checkout SHA**、レビュー、負例、rollback、decisionをrepo-owning Issueへ保存。devflow #465は共通実装、#386は横断受入のまとめだけを管理。

**現在のfirst unfinished:** `R1_STATIC_REGISTRY_DESIGN_REVIEW`。本ファイルの作成やPR作成によって実装・権限・Pilot成功・fleet受入は成立しない。
