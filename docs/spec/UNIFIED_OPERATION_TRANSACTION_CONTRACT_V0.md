# 統一操作トランザクション契約 v0 — 事前読取・限定変更・結果検証

**状態：提案段階・非稼働の横断操作設計**（2026-10-12）。**担当正本：** [devflow #487](https://github.com/kinoko34077/devflow/issues/487). この文書は稼働中の依頼振分API、実行権限、承認証拠ではなく、各リポジトリの契約を上書きしない。共通設計方針はユーザー承認済みだが、実際の変更の有効化には既存の技術・安全性・人間承認条件を別途満たす必要がある。

## 0. 既存契約と責務（参照索引）

| 正本 | 受入範囲と維持する境界 |
| --- | --- |
| [#413](https://github.com/kinoko34077/devflow/issues/413) G1 | オフラインのG1案と、公開リポジトリの所有者に限定した読み取り専用コメント操作2件を受入済み。依頼受付・固定操作カタログ・初期分類を担当。**Issueコメントを認可として扱わない。** 入力形式と操作IDだけを共有し、任意シェルや任意ワークフロー起動へ拡張しない。 |
| [#439](https://github.com/kinoko34077/devflow/issues/439) 審査・人間承認 | 受入済み。実際の変更対象・保護条件・不可逆性で審査を判断。G1 v1の**書込→`NEEDS_HUMAN`**は、別途審査したv2へ正式移行するまで維持する。 |
| [#384](https://github.com/kinoko34077/devflow/issues/384)／[JO #300](https://github.com/kinoko34077/japanese-orthography/issues/300) | S0〜S5の単一JO試験を受入済み。生成側の読取ジョブと特権書込処理を分離し、実行・呼出元・目録の認証、限定パス、強制しない更新、書込後検証・再実行制御を維持。**JOの固定SHA・稼働経路を変更しない。** |
| [#465](https://github.com/kinoko34077/devflow/issues/465)／[PR #470](https://github.com/kinoko34077/devflow/pull/470) | R1はmain `ebd20bb76d38a1c18b85f730a0a96753c02390e7`に統合済み。固定生成手順、実行者・呼出元の認証GET、ZIP・目録、読み取り専用の事前確認と**休止中の書込接続処理**を所有。既存実装を再利用し、無断で再実装・有効化しない。 |
| [#474](https://github.com/kinoko34077/devflow/issues/474)／[PR #475](https://github.com/kinoko34077/devflow/pull/475) | 当時のtestapp書込機能は**保留**。対象ブランチの保護・PR限定・独立した最終安全審査・実際の再実行と取り消しの証拠が固有条件。#487から保留を解除しない。後続の状態は所有Issueで確認する。 |
| [execution-coordinator](https://github.com/kinoko34077/execution-coordinator)／[Control #107](https://github.com/kinoko34077/devflow/issues/107) | エージェントの占有権・有効期限・世代・競合防止の唯一の管理元。必要な場合だけ最新の占有条件を確認し、第二の作業待ち行列や占有データベースを作らない。 |
| 各リポジトリの所有Issue・PR | 資源・HEAD、CI・レビュー、ジョブ権限、許可された変更・復旧の詳細正本。devflowは共通用語だけを管理する。 |

## 1. 基本原則と処理順序

**すべての状態変更は、実際の読み取り専用の観測と計画の検証を経てから実行しなければならない。** これは処理の意味上の順序であり、軽微なIssue・PRの情報更新に別のGitHub Actionsジョブを必須とするものではない。低リスクな変更には対象を限定したGET・差分・検証で足りる。一方、未信頼コードや生成物、特権操作では、読み取り専用の生成・計画処理と書込権限を持つ処理を分離する。書込側は、**事前観測とは独立して実行直前の対象状態・権限を再取得する。**

観測・計画の成功だけでは、書込権限、依頼者の本人性、状態の鮮度、実行中タスクの占有権、変更の成立は証明できない。ハッシュは検証済みの原本との一致を示すだけであり、未信頼のmanifestやIssueコメントだけでは認証できない。読み取り専用ジョブでも悪意あるコードの実行や計算費用が発生し得るため、実行環境と外部出力を別途評価する。

### 処理の6段階（必ずしも独立した6プロセスではない）

1. **対象確定：** レビュー済みの変更不能な操作カタログから版付き操作を選び、実行者・呼出元・ソースと対象の同一性を検証する。入力文の自己申告を証拠にしない。
2. **観測（読取）：** 最小限の信頼できる読取経路で、対象、権限、ブランチ保護、PR・CI・レビュー、必要な所有者・競合、現行版・HEADを取得する。
3. **計画（読取）：** 許可済み操作・変更差分・固定パスや項目・上限・安全な復元可能性・信頼条件を検証する。**実行を認可しない**計画と根拠・来歴、観測状態の識別情報を出力する。
4. **許可判定（読取）：** 人間の承認・レビュー要否、実行者の権限、必要時の調整機構の占有検証、計画版・固定ソース・現在の対象を独立に確認する。証拠が不足すれば拒否する。
5. **変更実行：** 操作ごとの限定書込処理が最新状態を再取得し、API固有の条件付き更新・競合制御・上限を適用する。特権書込環境で未信頼PR・生成物のコードを実行しない。権限が広くても、変更対象を審査済みの資源・項目・パスに限定する。
6. **結果検証・整合（読取）：** 実際の変更後状態、差分・PR状態、受入済みソース・CI、外部への作用を確認し、範囲を限定した検証記録を残す。結果が不明なら、**再試行・再修正より先に読み取り専用の照合**を行う。

各依頼には有限の重複排除キーと対象・版の範囲を定める。ただし、キーだけで重複実行は防げない。実行の所有者が既存の永続化・直列化機構で再実行を制御し、独立に認証した実行ID・試行回数と結果の証拠を照合する。

## 2. 独立した三つのデータ契約（信頼の引継ぎ禁止）

**OperationDefinition（信頼済み操作定義）：** 版付き操作ID、所有コンポーネント・処理担当、固定された処理基盤とレビュー済み実行物・ファイルSHA、対象リポジトリ・資源種別、読取権限、許可された変更・パス・項目、対象の競合判定と保証水準、ソース・呼出元・実行者の認証条件、資源上限・期待する変更後状態、重複実行防止方式、補償・復旧分類、受入済み方針に沿った人間承認・レビュー判定を含む。依頼者に任意のURL・シェル・ワークフローファイル・実行モジュール・トークン・参照先・新操作名を選ばせない。Issue・PR入力ではなく、変更不能なレビュー済みソースから取得する。

**PreflightEvidence（事前検証の証拠・認可効力なし）：** 依頼ID、スキーマ・操作定義の版と信頼済みカタログのSHA、正規化した対象ID、独立認証した観測の来歴（実行者、GitHub実行ID・試行回数、検証済みワークフロー・呼出元SHAなど）、対応時の観測版・PR HEAD/base/head・ETag、限定された変更差分・目的、読み取り・検証結果、依存・CI・レビュー状態、時刻・鮮度区分・ダイジェストを含む。認証情報・非公開内容を秘匿し、計画段階で実行可能な権限証票を発行しない。

**EffectReceipt（変更結果の検証記録）：** 検証済み依頼ID・定義ID、認証済み書込者・ソース・実行ID/試行回数、対象の厳密な変更前後の識別情報、許可された変更と実際のコミット・項目差分、結果状態、検証証拠、封じ込め・ロールバック、再実行への参照、記録先の所有Issueを含む。計画の`PASS`やコマンドの終了コード0だけで完了としない。

安全性に関わる必須項目の不足・余分な項目は拒否する。実行者や保存用manifestの自己申告、単なる時刻を、GitHubで独立認証した証拠に代用しない。データのハッシュと認証済みの来歴を区別する。再実行を別対象へ転用されないよう、正規化ハッシュにはスキーマ・版と正確な対象を含める。

## 3. API別の競合・鮮度保証

| GitHubで変更する対象 | 確認済みの仕組み | 保証範囲と実行条件 |
| --- | --- | --- |
| **PRマージ** | GitHub RESTのマージAPIは指定したPR HEAD SHAを照合し、不一致を拒否する。 | 実際にサーバーが照合するHEADを指定し、必須CI・レビュー・対象/baseを再検証する。計画に含むその他の条件まで原子的に検証されたとは扱わない。 |
| **Git参照の更新（PATCH git/refs）** | `force:false`が保証するのは**早送り更新**。期待する旧HEADとの原子的比較条件は文書化されていない。 | **一般的な原子的CASではない。** 正確なHEADを再取得→そのHEADを単独の親とするコミットを生成→許可ブランチ・保護/main拒否→必要な書込直列化→早送り更新→実際の参照・コミット再取得。残る競合を明記し、厳密な旧HEAD一致が不可欠ならより強い更新手段を使う。 |
| **Issue・PRの情報更新／コメント** | 更新前GETと事後再取得は可能だが、任意の旧値を原子的に照合する共通機構は未確認。 | 排他所有者・更新直列化または変更範囲制限で競合を抑え、途中の状態変化を検出する。原子的な更新保証を宣言しない。結果不明時は再試行前に検証記録を照合。 |
| **生成物ZIP・ファイル** | #384/#465のデータ専用検査：固定パス・ダイジェスト・最大サイズ、信頼済み実行環境・呼出元・ソース・実行ID、保護/既定ブランチの拒否。 | 既存の操作専用検証機構を再利用。対象範囲を勝手に拡大せず、生成物のハッシュだけで書込を認可しない。 |
| **外部サービス実行・公開** | 外部への実作用と計算資源の利用はGitHubのリポジトリ情報読取とは別。 | 操作別の人間・安全性承認、サービス/実行環境の本人性と応答確認を要する。一般的な自動公開や非公開計算処理を認可しない。 |

根拠：[Git参照REST](https://docs.github.com/en/rest/git/refs)、[PRマージREST](https://docs.github.com/en/rest/pulls/pulls)、#384の書戻し受入記録。変更直前のGETも、確認時点と変更時点の競合を完全には消せない。**全対象をCAS対応と呼んだり、`force:false`を旧値一致の原子的更新として扱ったりしない。**

## 4. 共通の結果分類と既存実装への対応

| 結果 | 意味・必須の対応 |
| --- | --- |
| **COMMITTED** | 許可された変更と必要な事後条件を、認証済みの対象・検証記録から確認済み。依頼受付や実行環境の成功だけでは不足。 |
| **NO_OP** | 目標状態を実際に再取得し、副作用がなく重複実行を防止できていると確認済み。 |
| **REJECTED** | 不正なソース、方針・入力違反で拒否。ワークフローのスキップは成功ではなく、処理の拒否。 |
| **STALE** | 対象・Git参照・CI・占有状態が観測後に変化。旧計画を自動再利用せず、再取得して計画を作り直す。 |
| **UNKNOWN_RECONCILE** | 時間切れや外部処理の結果不明。依頼ID・実行IDで照合してから次の処理を決定し、盲目的な二重更新をしない。 |
| **VERIFY_FAILED** | 変更が実行された可能性はあるが事後条件を証明できない。証拠を保持して停止・封じ込めし、必要なら限定した補償や取り消しPRを検討する。 |
| **HUMAN_GATE** | 必須の明示的人間承認・安全性確認が不足。ユーザー投稿コメントやG1の`ADMITTED`を承認とみなさない。 |

この結果分類は、**既存の操作別結果を共通表示するためのもの**。#384/#465固有の結果値を直接置き換えず、個別の細かい区別を失わせない。

## 5. 能力分類・承認条件

| 分類 | 境界 |
| --- | --- |
| **READ_DATA** | 認証済みmetadataのread。repo変更はしないが、privacy/外部compute費用は別途検査。 |
| **READ_EXECUTE** | test/build/benchmarkなどの計算実行。tokenがread-onlyでもPR由来codeとrunner資源の危険を評価。 |
| **REVERSIBLE_EFFECT** | 限定Issue編集、scratch branch変更、安全なPR merge等。実際の変更と復旧根拠を審査し、#439上必要なreviewと既存権限を満たす場合のみ。独立reviewが不要な場合はself-review可。 |
| **PRIVILEGED_EFFECT** | workflow/権限/secret/security境界、任意外部実行、Privateデータ露出、復旧困難な破壊。個別Human/security gateと必要な独立reviewを要する。 |
| **RELEASE_EFFECT** | 外部公開・deploy・release。Git操作自体が復元可能でも明示ユーザー承認が必要。 |

**ReviewとHuman承認は独立判定。** G1 v1のwrite→`NEEDS_HUMAN`をv0設計だけで緩和しない。v2移行には#439に従うG1個別review・互換性確認・指定effectのpilotが必要。同じmodel/providerのself-reviewは別systemの独立reviewではない。

## 6. 接続先（既存実装の所有権は移さない）

- **#413 G1:** trusted catalog ID付きの**未信頼request**だけをshared planner/guardへ渡す。既存の単純GitHub API操作は直接実行優先。Issue comment入口は未対応かつ個別review済み固定commandに限る。
- **#465:** 受入済みread-only artifact previewの実source/provenance/ZIP/targetから`PreflightEvidence`へ変換。固有の検証算法を変更せず、writerを公開しない。
- **#474:** 独立受入済みのnative writer receiptだけを`EffectReceipt`へ変換。#487を#474の既存保護・Human/Review gateの成立/解除条件にしない。
- **execution-coordinator:** agent所有の仕事だけfresh fenceを照合。通常の直接GitHub API操作へ架空のclaimを要求しない。
- **repository-local:** source/CI/policyとJO固定pinが優先。adapterはversion付きとし、歴史的受入版の互換性を守る。

## 7. 実施順序と段階別の受入

**A0 — 現行棚卸し完了：** #487にowner、interface、merged/unmerged SHA、危険なAPI意味論を記録済み。#465/#474のコードは変更しない。

**A1 — 仕様書のみ：** この非稼働仕様を独立docs PRで公開し、exact-head Review・既存Required CIを通す。#413 G1・#439との整合を確認。変更範囲は新規仕様文書だけで、trigger・権限は有効化しない。

**A2 — 別タスク・通信なし：** 信頼済みparser・provenance・validatorをimportし、generic plan/outcomeの**表示用adapter**を構築する。writerを複製しない。テストは偽actor/caller、stale SHA、別target、JSON重複key、予期しないwrite、無署名plan、権限誤分類、競合/再試行、HEAD/CAS不足、timeout。READMEに合否を記録。通信・live書込なし。

**A3 — ownerとの非干渉確認後：** #465の受入済みartifact previewからread-only evidence adapterを1件、独立受入された#474 native writer receiptからoutcome adapterを1件。古いR1の上書きや、#474の特権書込経路を有効化したとみなすことは禁止。

**A4 — 別途許可された実操作：** 接続済みGitHub APIで可能な影響の小さい具体的Public effectを選び、read→plan→実行直前の権限/状態再取得→限定effect→readback→reconcileと負例・replayを実証。対象がPR/head/refかIssueかに応じて原子的更新保証を評価する。HOLD中の#474で試験書込しない。

**A5 — 必要な公開対象だけに任意導入：** 単一dispatcher workflowが本当に有効か検証し、command毎のworkflow乱立とjob別最小権限の両方を考慮する。

**A6 — 非公開・特権操作：** runner/課金/認可の現行実証と対象を特定したHuman承認がある場合のみ。A0〜A5で目的達成なら**STOP**。

**段階の独立性：** A1は**非稼働仕様の受入だけ**。汎用executor、共通認可token、GitHub-hosted Private runner、allowlist拡大、複数repoの特権writerは承認されない。次の段階はlive owner・実装・証拠を確認して個別判断する。

## 8. 必須の異常系・失敗時検証

以下の14ケースを区別してfail-closed検証する。正常入力の成功だけでは受入しない。

1. Issueコメント/manifestが自称するactorとGitHub認証actorが異なる、runner環境偽造、owner Issue取り違え。
2. 未登録action・対象外resource、任意shell/ref/workflow、壊れたJSON・重複key。
3. 信頼済みcatalog/workflow SHAが変更、repo・PR・source identity不一致。
4. live GETのないpreflight、弱いHEAD証明、事前read省略要求。
5. 同じplan文面でもrepo/SHA/run・attempt/recipe/body bytes/actorが異なるreplay。
6. 計画後のPR HEAD/対象branch/CI変化、coordinator lease失効。
7. Tokenには広い権限があるが実操作が許可済みeffect/path集合を超える。
8. PR由来ZIP/artifactの重複・追加path、link/traversal、zip bomb、digest不一致。writer権限で中のコードを実行しない。
9. workflow `SKIPPED`、API受付、exit 0、未監査artifactを偽の成功として扱う。
10. effect実行後のtimeout・receipt不明を、未検証の成功や盲目的再書込に変える。
11. Private/特権callerの実runner・security capabilityを未確認のまま通す。
12. 同じGit refへの複数writer・異なる子commit、`force:false`のfast-forwardを原子的expected-old-ref CASと混同。
13. 別agentがcoordinator claim/leaseを保持中なのに#487に第二の所有権を作る。
14. Feature flag/catalog v2移行時に既存JO/G1 v1のfail-closed意味を変える。

## 9. 設計判断と全体方針

**共通化するのは必要最小限の意味・契約だけ。** 操作固有の信頼済み計画処理と変更実行処理は各担当正本に残し、既存のGitHub APIによる直接操作を優先する。#465の書込処理を一括移設・再実装せず、検証済み実装を依存先として再利用する。A0・A1は安全に終了できる範囲であり、A2以降は実際の統合効果と受入証拠によって進行可否を判断する。第二の汎用タスク実行基盤は作らない。
