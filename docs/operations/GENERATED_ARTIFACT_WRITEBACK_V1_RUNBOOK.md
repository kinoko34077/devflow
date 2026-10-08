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
