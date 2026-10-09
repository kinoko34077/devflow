# 検証済み生成物の書戻し v1 — 安全運用・監査Runbook（受入前草案）

**正本:** devflow #384、設計契約 \`docs/spec/GENERATED_ARTIFACT_WRITEBACK_V1.md\`。  
**対象:** single repo Pilot \`kinoko34077/japanese-orthography#300\`。  
**現状:** S3実装審査中。**本書の存在はwriterの有効化・Review承認・Pilot成功・S4/S5完了を意味しない。**  
**派生:** 各repository・各chatへの段階導入は別Issue devflow#386であり、今回のPilot承認を引き継がない。

## 1. 受入条件と安全境界

1. 対象repo/recipe/actor/生成pathを信頼済みコード・固定設定に限定。初期対象は \`japanese-orthography\` の \`jo-orthography-accounting@1\` と \`data/reports/orthography-v2-source-accounting.json\` の1ファイルのみ。別repo/別recipeは別承認。
2. 信頼済みdefault branchから明示的に起動された \`workflow_dispatch\` に限る。fork/PR起点の権限付き自動トリガーなし。対象branchは専用 \`artifact/devflow384/\` prefix内の単独open PR、exact expected commit SHA一致、main/default以外、保護/rulesets状態をGitHub APIで確認できること。
3. generator jobは \`permissions: contents:read\`（secretsなし）。PR branchへcheckoutし、固定recipeの生成・検証を行うことはこのjobにのみ許容。アーティファクトはすべて低信頼データとして扱う。
4. writer jobのみ承認済みの \`contents:write\` を利用。生成repo sourceのcheckout/build/install/script実行は禁止。writerヘルパは**受入済みdevflow SHA**を固定参照する。未merge・未review branchのコードを権限付きjobへロードしない。\`actions:read\` によるrun metadata検証を行う場合、read権限の有効性を実測する。
5. producer manifestの \`actor\`、\`source_sha\`、\`producer_run_id\`、\`workflow_ref\` は自己申告であり、独立認証にならない。writerはGitHub Actions REST APIからrun/workflow情報を取得し、first-party workflow contextのrun ID、attempt、workflow SHA、actor、default branch、workflow pathとの**厳密一致**を確認してからmanifestと照合する。
6. ZIP: 原bytes/SHA256/サイズ/ファイル数/圧縮率・symlink/実行可能mode・重複/未知/省略path・\`.github/\`/parent traversal等を拒否。targetの既存Git treeをpath要素ごと観測し、blob \`100644\` 以外と不正な親を拒否。差分は固定pathのみ、意図しない削除なし。
7. Git commitのparentはexpected HEADに限定。更新前に再照会し、更新時は \`force:false\`。成功後に再照会し、新HEADと記録が一致すること。動いた場合は**新たなHuman-accepted admissionなしに再試行しない**。同一run/manifest、単一parent、正確なtarget bytes＋差分の裏付けがある場合だけ \`NO_OP_REPLAY\`。
8. \`GITHUB_TOKEN\`を用いた通常のpushだけではrequired PR CIを起動できない。承認済みの明示的な検証経路で**新しいexact HEAD**にcheckoutしてUbuntu/Windows正式checkを実行し、runログ・実際にテストしたSHA・結果をIssueへ永続化する。\`repository_dispatch\` は \`contents:write\` のみで起動可能だが **runのCheckがdefault-branch SHAへ付く可能性**があるため、required PR checkが新HEADに付いたものとしては扱わず、正式merge gateの条件を別途確認する。\`workflow_dispatch\` REST経由には \`actions:write\` が必要となり、未承認なら実行しない。
9. source PR codeやarchiveが悪意あるものとして無条件実行しない設計と、trusted workflow編集者への権限昇格を含めて独立セキュリティReviewで確認する。秘匿情報をログへ出さない。

## 1A. S3のtrusted SHA確立とPilot順序（S3/S4循環依存の解消案・独立Review/受入待ち）

### 循環依存の原因
現行の「S3出口にlive Pilot成功が必須」かつ「writerは受入済みdevflow SHAのみをロード」かつ「devflowへのmergeをS4で初めて行う」は、三条件を同時に満たせない。未mergeの権限付きコードを実行してPilotを先行させる方法、またはPilot未成功を成功と扱う方法は**採用しない**。

### 段階を区別する
- **S3.4 — code security gate（未受入）:** 当該最終コードの統合PRのexact HEAD／base・完全なdiff・Required CI・正式な独立レビュー・未解決finding・job permission/actor/runner境界・現行の関連Issueをゼロから再監査する。GPTとClaudeの各担当差分への別Reviewは維持するが、**両者が実装した統合全体には両者以外の独立したセキュリティReviewer**が必要。特に#387のB1未修正の中間HEADを合格させない。成功してもPilot受入ではない。
- **S3.5 — trusted-code bootstrap merge（特例・未許可）:** S3.4の全gateに加え、**security-sensitiveな前倒しの統合mergeについて対象・SHA・復旧方法を明示したHuman承認**がある場合に限り、B1修正済みの統合コードを**一つの原子的なPR merge**でdevflow default branchに反映する。#385/#390/#387/#391を順次mainへmergeして、途中で権限付きworkflowの未修正版が有効なmainを作ってはならない。merge前にPR/base HEADを再照合し、差分14ファイル等の観測を記録し、post-mainのRequired checksを当該main SHAで確認する。チェックがFAILならPilotへ進まずrevert PR等の復旧を判断する。これは「trusted codeのbootstrap受入」であり、**S3/S4の機能・Pilot完了ではない**。
- **S3.6 — bounded Pilot:** 受入済みmain上の**正確なcommit SHA**だけをreusable workflowとtrusted helperに使用。Pilot対象repoがJO一件、recipeが`jo-orthography-accounting@1`、生成ファイルが`data/reports/orthography-v2-source-accounting.json` 1件であることを実行時に再確認。対象側callerは**別PRで独立レビューを経た後**、安全に有効化されたdefault branchでのみ`workflow_dispatch`実行可能。過去に拒否された特権workflow入口の作成を別tool/経路へ切り替えて回避しない。限定job権限の明示許可を超えたら停止。最初にdry-run、次に非force write、exact replay、競合拒否、不正入力拒否、rollback、writer HEADのreadback、新HEADの正規Ubuntu/Windows Required CIを実証する。初回scratch PRの意図的stale CI失敗は成功証拠に流用しない。
- **S3出口 — operational Pilot gate:** 本節と§2のlive Pilot・不正入力・権限・復旧・CI・記録を全件満たして初めてS3をGREENとする。bootstrap merge完了だけの場合、Cursorは従来どおり`S3_SINGLE_REPO_PILOT`に留める。
- **S4 — final acceptance / reconciliation gate:** §3に沿い、新たなmainの受入済みSHA／Pilot成果／正規CI／独立Review／merge履歴と、bootstrap後に変更があった場合の別PRの安全なmergeとpost-main checksを再監査する。追加変更がなければbootstrap mergeを唯一のcode mergeとして承認記録を照合し、同じコードを二重にmergeしない。S4はbootstrap mergeによって自動GREENとしない。全gate完了後にだけS5文書・Control同期へ進む。

### Bootstrap mergeに関する停止・復旧
1. S3.4の独立レビューが無い、現行HEADのreview-readinessがFAIL、B1が統合最終treeに残る、Humanの特例承認が無い場合は**S3.5に進まない**。
2. bootstrap mergeしてもJO側のcallerを導入するまではPilotの`workflow_dispatch`は存在しない。devflow側は単体で`workflow_call`入口を公開し得るため、merge前に**同じリポジトリ／他リポジトリから予期せず権限付きjobが起動できないこと**と、caller repo identity/actor/recipe/path allowlistの拒否を独立監査する。
3. bootstrap後のmain CI/security観測が失敗、意図しないwriteが観測された、あるいはreviewed SHAと実行中のhelperが不一致なら、特権Pilotを停止し、revocation/close/revert PR等の復旧と再レビューへ戻す。default branchのforce/rewriteは禁止。
4. 許可済みスコープは単一JO Pilotのwriter job`contents:write`とread用`actions:read`、`pull-requests:read`まで。`actions:write`、PAT、GitHub App、secrets、settings/rulesets/protection変更、他repoの有効化は別Human gateである。
5. 本節は**受入前の仕様変更案**として別PRでレビューし、devflow#384の正式なphase-order決定と必要なHuman承認を得るまでは、既存§1–§3の安全境界を緩和しない。

## 2. S3 → S4：毎回ゼロベース監査

対象を固定せずに古いcheckpointを再利用しない。S3のexitで、次の項目を**現行正本から新規照合**し、合否・evidence URL・未解決findingをIssueに記録する。

| 監査軸 | 必須の具体的証拠 | 判定 |
| --- | --- | --- |
| 正本/Scope | devflow \`AGENTS.md\`、Control #16、#384、Pilot #300、衝突する#291/#210/PR #296のlive状態 | 未確認ならHOLD |
| 共有コード | producer packager、admission/manifest、writer、static policy、pin済みworkflow/callerのPR exact HEAD | 未実装ならHOLD |
| job権限 | read jobにwrite token/secretなし、writerにPR-code execute/installなし、tokenは当該jobのみ | 欠けたらHOLD |
| attacker negative | fork、偽run/actor/recipe/branch/source、未許可path、ZIP bomb、symlink/submodule、race/replay、変更file外混入 | 検証不足ならHOLD |
| 生きたPilot | 専用PR branch、実write/no-op/競合拒否、非force、新HEAD readback、rollback実証、事後清掃 | 未実施ならHOLD |
| CI/正式Review | exact-headの必須checkと独立のwriter security Reviewが成功、blockingなし | 不足ならHOLD |
| Human gate | 日本語で指定された単一repoの\`contents:write\`のみ、別permission/settings変更なし | 範囲超過ならHOLD |
| 操作記録 | manifest SHA、run ID/attempt、source/head、commit、CI runs、Review、障害時再開位置 | 欠けたらHOLD |

S3 exitがHOLDの場合、S4を「完了」とは表記しない。進捗Cursorは最初の未完了checkpointに留める。

## 3. S4：独立レビューとmerge gate

1. S3 exit auditを再読した上で、PR exact HEAD、base HEAD、diff/変更ファイル一覧、GitHub Required CI（同一SHA）、formal Review（実装者と異なるsystem/model）、未解決review threads、workflow権限/credential/branch protectionを**再取得**。
2. 重大な指摘が1つでもあれば、PR commitを修正しexact-head CIと別担当Reviewを繰り返す。**旧HEADでGREENは現在のGREENではない**。
3. GitHub上のReviewer-Provenanceは実レビュー提出者自身が訂正する。実装者がClaude等のReviewerを偽装して機械判定を通さない。
4. 全gate GREEN、条件付き承認範囲内、衝突なし、変更対象が安全にrevert可能な場合のみ安全なmerge方法を使用する。main直接commit、force/history rewrite、deploy/release、shared secrets/settings変更は禁止。
5. mergeしたmainのexact SHAを確認し、post-main CIとPilot side effectsを確認する。証拠のない成功は認めない。

## 4. S4 → S5：新規開始監査

- **S3:** 実writer/CAS/replay/negative/rollback/CI証拠を集めたか。
- **S4:** merged PR/merge commit、formal Review、review-readiness、merge時のexpected base、新main HEAD、post-main checksをlive照合したか。
- **Permission:** job-scoped write付与が対象Pilot以外へ波及していないか、削除すべき一時grant/workflowが残っていないか。
- **Scope:** #291/#210/PR #296 とdeploy/Pages/Phase5/6を無変更に保っているか。
- **Recovery:** 障害時のfirst unfinishedと最後の成功runがIssue/Task Cursorから再構築可能か。
- いずれか不明なら **S5 ACCEPTANCE はHOLD** し、未検証の成功を記録しない。

## 5. 障害分類・停止・復旧

| 症状 | 保全する根拠 | 対処 |
| --- | --- | --- |
| 生成/検証失敗 | producer run、固定recipe/version、source SHA、stderr要約 | 書込jobを起動しない。PR source問題はownerへ戻す |
| provenance mismatch | runner run ID、run metadata、workflow SHA、manifest SHA、actor | すべて拒否。manifestを信頼側として書き換えない |
| ZIP/path/mode fail | path、digest、mode、limits（tokenやraw bytesを漏らさない） | 不正パスをallowlistに追加せず停止 |
| expected HEAD競合 | old SHA、新しいlive SHA、PR diff | 非force CASを拒否。新たな正式admissionへ切り直す |
| commit objects生成後refが拒否 | 作成済みcommit SHA、未更新target HEAD | orphan Git objectsは参照されない。強制pushしない |
| ref成功後CI未実行/失敗 | 新HEAD、commit、run ID、required checkの対象SHA | mergeせずHOLD、別権限ゲートなしで明示verify可能な経路を選ぶ |
| artifact/driverが停止 | #384/#300 Durable Progressと唯一のTask Cursor | 完了単位を再実装しない。current HEADを再読して必要最小の再開 |
| Pilot撤回 | PRと最後の書込commit SHA、元source/生成物ハッシュ | 共有historyをrebase/forceしない。未mergeならPRを閉じるか、別revert commitで戻す |

## 6. S5で更新する正本（受入が実際に成立した場合のみ）

- devflow#384: 完了したS0–S5、exact accepted HEAD / run / Review、権限境界、残件、final first-unfinishedまたはCOMPLETE。
- devflow Control #16: 受入済みの共通機能版と初期adoption \`PILOT\`、残る#386 roll-out gate。
- japanese-orthography#300および関連Control #180: Pilot実証run/commit/rollback/permission cleanupとowner判定。
- \`docs/spec/GENERATED_ARTIFACT_WRITEBACK_V1.md\`: 観測した現実の動作、受入版schema/API、運用上の例外と残る制限を反映。
- PRとSession/Task Cursor: SUCCESS と失敗の両方の実証、最終Review/CI、正しいユーザー承認範囲を復元可能にする。

**結論:** 「コードテストが成功した」「単一Pilotが成功した」「全repositoriyで使える」「S5 ACCEPTED」は別状態であり、段階ごとに独立した根拠が必要。

## 7. S3.3 実装（共通workflow・CLI・caller雛形）— 独立Review待ち

- 共通 `workflow_call`: `.github/workflows/generated-artifact-writeback.yml`。top-level `permissions: {}`。
  - `produce` job: `contents: read` のみ、secretsなし、`persist-credentials: false`。固定recipe（`tools/generated_artifact_pilot.py` の `RECIPE_NPM_SCRIPT`）だけを `npm run` し、出力は低信頼dataとしてrun限定artifactへ。
  - `write` job: `contents: write` + `actions: read` + `pull-requests: read`（後2者はrun/PR観測用のread）。target repoのcheckout・npm・node・artifact実行なし。devflow helperは caller が `uses:` で固定した同一SHAを資格情報なしで取得し、`rev-parse` で一致検証。
- Writer認証（#387 review F1の解消）: `workflow_sha` はJO mainのHEADで変動するため静的pinしない。runner context + `GET /actions/runs/{id}` + `GET /actions/workflows/{id}` の厳密一致に加え、**`workflow_sha` 時点のcaller内容**を取得し、`uses:` pinと `devflow_sha:` 入力が同一SHAで各1回、`workflow_dispatch` のみ、secrets/`run:`/他trigger無しを確認してから、run固有の `producer_workflow_ref` を導出する。
- caller雛形: `docs/operations/templates/verified-artifacts-pilot.yml`（devflowでは非稼働）。JO導入は独立security Review合格後、レビュー済みSHAで `<DEVFLOW_SHA>` を2箇所置換し、JO側の通常PR/Review経由で行う。
- 新HEADのexact CI: JO `Verify` は `pull_request` トリガー。`GITHUB_TOKEN` pushでは起動しないため、`actions:write` 無しでは **Humanによるscratch PRのclose/reopen等のPRイベント** が正当経路。これはHuman操作として記録する。
