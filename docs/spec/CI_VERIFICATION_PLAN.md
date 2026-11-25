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

## GitHub原典の初期取得（R1）
`tools.ci_github_evidence` は既存 `GitHubReader` に追加した固定GET入口を利用し、別認証・transport・汎用mapperを作らない。任意URLを受け取らない。#1144の共通マッパーは別owner。現行MCP/CLI公開入口とrelease gateは未変更。

- `read_pr_verification(reader, repository, number)`：PR原典の番号・repo・head/baseを照合し、現行PR本文を既存owner metadata validatorで直接再判定（低コストなので過去のmetadata成功をキャッシュしない）。本文等の入力digestを表示する。openのsynthetic mergeはcommitとbase/headの両親を確認し、mergedの実commitと区別する。候補取得不能でもmetadata結果を保持する。現在の候補treeは**テスト済みtreeではない**。
- `read_run_verification(reader, repository, run_id)`：native runのrepo/workflow/attempt/head/eventとlatest jobsを取得し、runを再読して変化を検出。jobのrun/attempt/head/idを照合。過去attemptのjobはlatest一覧に実在する場合に限り観測対象とする。異なるjob IDを持つ同名matrixを拒否しない。単一ページの不足・欠落・不正はPARTIALであり、完全な集合を推測しない。
- native結果には共通コアを使うが保証は**当該run/jobの結果**に限る。REUSE_CANDIDATEは当該原典結果の再利用候補であって、別候補のテスト省略ではない。PR runのhead_sha/head_commitはhead branchで、実checkout・統合treeとは限らない（実PR #1143 run45507523861のpull_requestsは空）。mainでも任意workflowが実際にcheckoutした対象はrun情報だけでは証明できない。tested_treeはnull、code_equivalenceはUNKNOWNのまま。既存失敗/Review/native gateを解除しない。
- 観測は原子的でない。実行直前には必要なsource revalidationを行う。R1残存/R3で信頼できる実checkout・検証定義・実解決依存・環境の証拠を最小限記録する契約を実証する。高価なログ走査や無条件再実行を前提にしない。native run/job観測と実コード保証の意味を混同しない。


## 実行証拠の結合（R1）

`read_execution_verification` は既存native run/job観測を利用する内部入口。特定のコード実行保証に限り、`ExecutionInputs` で実checkoutのtree SHA、検証定義、実解決環境、実解決依存、適用policyの各SHA-256を比較する。metadata等の別保証にこの次元を強制しない。ハッシュ対象と正規化は保証ownerの信頼済み収集契約が定める（この入口はハッシュから実行内容を推定しない）。

- `TrustedExecutionReceipt` は保護された収集側が実際のテスト対象・入力・実行時環境と証拠鮮度を計測・認証して渡す内部型。型や自己申告のhash自体は真正性を証明しない。未信頼PRコードが生成したartifact・stdout・任意JSONをreceiptとして採用しない。公開CLI/MCP受付・真正receipt生成・永続化はこの段階では未接続。
- repo/guarantee、run ID・workflow ID/path/event/head、最新job一覧上のjob ID/name/attemptを照合する。jobの実checkout SHAは既存GitHubReaderのcommit GETでtreeを再確認。PR event headのtreeをtested_treeへ転記しない。欠落・不一致・不正・部分観測はUNKNOWN/HOLDで当該保証の省略不可。
- 正常結合後のみtested_treeを返し、既存 `assess_verification` で要求の全入力と観測・現在結果・期限を比較する。現行workflow/jobの非成功は成功証拠にならず、期限切れやidentity差はRUN。REUSE_CANDIDATEは既存gateの解除ではない。原典再検証が必要。
- 本段階のfixtureは信頼済み収集側を模擬し、結合と同等判定のみ実証する。実GitHub runに真正receiptがない場合は従来通りtested_tree未知。次に保護された実行主体による測定・証拠配送・認証の実証を行う。既存MCP専用release gate、CI実行、権限、公開、保存、consumerは変更しない。


## 固定供給候補のnative証拠（R1・Base #66接続）

初回の承認済み固定版供給に一般的なコード等価性・全consumer展開を前提としない。保護されたpolicy側で選択済みの固定repo/ID、channel、policy revision、commit、branch、workflow ID/path、必須job名を `FixedSourceRequirement` に渡す。既存 `GitHubReader` のexact workflow push照会と `read_run_verification` の最新job・run再照合を使用し、対象runの一意性、repo/head repo ID、head/branch/workflow/event、成功・必須jobの一意な成功、commit treeを確認する。

`NATIVE_SOURCE_CANDIDATE` は指定固定版のnative成功と供給元treeの観測結果だけを表す。実行済みtreeは推定せず `tested_tree=null`、`can_authorize_execution=false`。取得不能・曖昧・drift・欠落はUNKNOWN、非成功はNOT_SUCCESSFUL。正規policyの真正性、pin/チャネル採否、host保護、供給物検証、実行許可・offline承認は別責務。公開JSON/MCP/CLIからpolicyを受け取らない。既存専用MCP release managerの実運用gateは変更しない。初回供給後の自動候補選択や実行証拠の測定/認証は別受入。


## 保護host固定承認resolver（R1・非稼働候補）

`tools/reference_host_policy.py` は既存 `FixedSourceRequirement` / `read_fixed_source_verification` と Base #76/#77 の `ResolveApproved(repository,channel,policyRevision,pin)` を接続する一つのhost専用入口。別のCI判定・Git供給・cache・公開MCPは追加しない。

- 保護host ownerが承認したUTF-8 TOMLの**実bytes SHA-256**をpolicy revisionとする。host側が絶対pathと期待digestを固定する。requestのrevisionはそのdigestと一致する必要がある。policyの採否・実行主体・path・digest・resolver実装をconsumerに選ばせない。
- `schema_version=1`、`[[sources]]` の各項目は repository、repository_id、channel、commit、tree_sha、branch、workflow_id、workflow_path、required_jobs。repo/channelごとに固定承認版一つ。pin省略はpolicyの固定版、明示pinは完全一致だけ。policyの未知項目・重複・不正・digest不一致・対象外をGET前に拒否。64KiBは設定読み取り時の資源上限であってsource件数の固定ではない。
- native evidenceは毎回既存入口で確認し、policyのtreeと照合する。成功時のみ `RESOLVED` と既存Base resolverの repository/repository_id/channel/policy_revision/commit/mode=CURRENT を返す。source_ref/tree_shaは診断素材、実行済みtreeではない。失敗は非zero終了かつmodeなし。OFFLINEへの自動降格、未承認版の探索・承認・昇格はしない。
- 保護済みprofileから、固定されたPython 3.11以上・絶対script pathを `-I -B` で呼ぶ。host設定の `--host-policy` と `--approved-digest` はconsumer requestの値で上書きしない。残り `--repository --channel --policy-revision --pin` のみ既存resolver引数。JSON/終了値はこの保護された呼出経路内で確認し、任意の外部JSON/stdoutを真正承認として採用しない。引数でdigestを指定できること自体は真正性・権限の証明ではない。
- 初回の明示固定版承認を一般CI等価性の完成まで遅延させない。将来の承認済み自動選択policyは別途受入する。既存保護manager・profile/credential/ACL・consumer・workflow・CI省略は未変更。試験policyは本番承認ではなく、実運用に用いるpolicy、信頼anchor、host配置/実行主体の保護、失効・差替え管理は独立Reviewと必要Human gateの対象。
