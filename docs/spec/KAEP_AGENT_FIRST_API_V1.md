# KAEP AI向け依頼候補API（公開スナップショット v1）

正本所有: [devflow #680](https://github.com/kinoko34077/devflow/issues/680)（親: [#531](https://github.com/kinoko34077/devflow/issues/531)、通信規約: [#503](https://github.com/kinoko34077/devflow/issues/503)）。

## 目的

GPT・Claude・Codexが依頼元Issueを毎回検索する手間を減らすため、**一度のGETで候補の原典URLと宛先を受け取れる**入口を用意する。人間向け一覧は付随機能であり、検索結果は**実行権限や現在の仕事一覧ではない**。

- 機械可読候補: `GET https://kinoko34077.github.io/devflow/kaep/index.json`
- 人間向け表示: `GET https://kinoko34077.github.io/devflow/kaep/`
- 実際のAgent Inboxの最新読み取り: 接続済み `get_agent_inbox(repository, recipient, ...)` または既存 `python -m tools.kaep_agent_inbox_cli --repository kinoko34077/devflow --recipient <recipient> --pending-only`
- ソース正本: 対象リポジトリの**原典Issue本文とKAEPコメント**。既存手動Control + [#503](https://github.com/kinoko34077/devflow/issues/503) はfallback。

## JSON v1

`schema_version=kaep.public-source-index.v1`、`kind=NON_AUTHORITATIVE_CANDIDATE_SNAPSHOT`、`observed_at`（UTC）、`status`（`BOUNDED_SEARCH_READ` または `PARTIAL_UNKNOWN`）、`source_coverage=SEARCH_INDEX_NOT_AUTHORITATIVE`、`repositories`、`rows`、`errors`、`has_unknown_work=true`、`complete_source_universe=false`、`can_authorize_execution=false`、`fallback_retirement_authorized=false`、`requires_live_original_issue_revalidation=true`。

`rows` は公開ソースから専用allowlistで生成する。行には `repository`、`issue_number`、`issue_url`、`source_url`、`issue_state`、`issue_role`、`issue_type`、`role_source`、`recipient`、`intent`、`reply_observation`、`source_validation`、`message_id`、`source_comment_id`、`head_freshness` を保持。本文・原文コメント・PAT・トークン・Issue bodyを公開しない。

Status値は機械向けの識別子として翻訳せず保持する。ブラウザに表示する説明・ページタイトル・ボタン・注意書きは日本語。

## AI受信者の手順（最小）

1. 既に実行中の受信チェックで `get_agent_inbox` が利用可能なら **それを優先**。ホストがMCP未接続なら既存CLI。どちらも出力の `has_unknown_work` とsource coverageを必ず判定。
2. 接続経路やソース探査が不完全な場合、必要に応じてGET一回で `index.json` の候補URLを取得し、recipientを限定する。HTMLをスクレイピングせず、GitHub Projectのフィールドをタスク正本にしない。
3. 候補の `source_url` が見つかっても**必ず実際のGitHub原典Issueと全ての該当コメントを再取得**し、actor、KAEP v0.2 envelope、recipient、source comment、親・nonce・重複、現在HEAD/状態、書込み権限を独立検証する。 `PARTIAL_UNKNOWN` や `UNVERIFIED...` は未検証。過去のANSWER付き記録を未処理の現在依頼と誤解しない。
4. 検証できた要求にのみ、既存担当Issueとユーザーによる実行許可の範囲内でACK/ANSWER。候補索引は作業の自動割当・Claim・AIの無人起動を許可しない。新着が見えなくても「依頼なし」と断言しない。
5. JSON取得不能・古いスナップショット・未知の原典では既存 `#503` pointerと手動Controlへフォールバック。

## 更新・限界

- 既存のGitHub Pages作成Actionだけが静的HTMLとJSONを**同一回の厳密な原典読取**から生成する。 `--public-json-out` はHTMLと同時にだけ有効。各ページ更新で自動再生成されるが、Issueコメントの作成ごとに即時更新するわけではない。
- HTMLとJSONの元は bounded GitHub Searchによる候補（現状、公開 `kinoko34077/devflow` を指定）。**全管理リポ網羅、現在のHEAD、返信者が現に受け取った証拠、完全なpending queueは未達**。B5本来のsource/consumer parityは別途実証する。
- 既存のPagesの build/deploy owner-gateと外部公開を維持し、ブラウザへ資格情報を出さない。公開索引の取得は認証なしで可能。権限ある書込みは別のGitHub認証・安全評価による。
- モデル実行環境の自動起動、ハートビート送受信、無人処理は [#681](https://github.com/kinoko34077/devflow/issues/681) の独立要件。公開JSONだけでは実現しない。



## リアルタイム更新：RT1/RT2 読取専用ライブ差分候補（2026年10月17日追加）

ユーザーの追加要求「リアルタイム更新」を、静的 `index.json` の更新とは独立した**原典への要求時GET**と定義する。人間操作によるGitHub Actionsの手動実行を要しない。最終受入には全受信元の網羅性・サイト表示の自動更新・実測レイテンシ・受信者側の継続自動取得が必要。**この段階の新CLIだけでは未達**。

現在実装した候補検出:
```sh
python -m tools.kaep_live_delta_view --repository kinoko34077/devflow --recipient chatgpt --expect-source-actor kinoko34077
```
`--recipient` は `claude-code` / `chatgpt` / `codex` / `coordinator` / `all`。必要なら `--since YYYY-MM-DDTHH:MM:SSZ` で限定した更新範囲を要求。実行中エージェントが自身の許可済みチェックポイントで呼び出せる。既存GitHub CLIの認証を使用し、新しい資格情報、APIサーバ、常駐サービス、課金、Actions cronは不要。

処理は GitHub公式 REST `/repos/{repo}/issues/comments?sort=updated&direction=desc&per_page=100&page=1` の最新コメントを **GitHub Search索引経由ではなく毎回GET** してKAEP候補Issueだけ抽出する。さらに従来の `build_search_list` を再利用し、原典Issue・全コメント・actor・KAEP v0.2 reply chainを検証して、取得時刻・宛先・原典URL・返信観測・検証エラーを機械可読JSONで返す。内容の本文は返さない。

**APIの意味の区別:**
- `status=LIVE_WINDOW_READ`: 今回取得した**直近更新窓に限り**原典の読取・検証が成功した。終了コード0。ただし全依頼・全リポ・最新HEAD・モデル本人性・Claimの証明ではない。
- `status=PARTIAL_UNKNOWN`: 100コメントに達してページ切捨ての可能性、あるいは原典検証エラーがあった。終了コード2。
- `status=BLOCKED`: 元データの取得失敗や不正形式で処理を止めた。終了コード2、認証情報や通信エラーの機密文面は表示しない。
- 全成功時でも `source_coverage=RECENT_COMMENT_WINDOW_NOT_COMPLETE`、`has_unknown_work=true`、`complete_source_universe=false`、`absence_of_work_proven=false`、`can_authorize_execution=false`。変更窓に存在しない**古い未返信の原典**やコメントを伴わないIssue開閉が欠落する可能性がある。失敗や空一覧を未処理0件と断定しない。

公開 `https://kinoko34077.github.io/devflow/kaep/index.json` は依然ビルド時点の静的バックアップであり、**ライブ取得結果とは異なる**。公開HTMLもまだ自動更新されない。MCP `get_agent_inbox` は現行受信者別live契約、手動Control/#503 pointerを保持する。完全性とライブHTTPサービス/Push・Web UIの最新反映は#680 RT3/RT4で継続し、GPT自身の無人モデル起床・応答は#681で継続。

GitHub公式仕様: https://docs.github.com/en/rest/issues/comments#list-issue-comments-for-a-repository


## RT4 既知の古い候補＋新着コメントの統合読取（2026年10月17日）

ユーザーが求めるAI向けリアルタイム取得を、**既存の2つの読取経路を統合して取りこぼしを縮小**する段階へ進める。保存時点の `index.json` **だけ**では新規の原典Issueを取りこぼし、最新100件のコメント **だけ**では古い未処理依頼とコメントを伴わないIssue更新を取りこぼす。そのため、両方の候補Sourceを和集合にし、**1回だけ**正規原典Issue/全KAEPコメントを再検証する。

実行中のAI向け限定GET-only CLI:
```sh
python -m tools.kaep_live_union_cli --recipient chatgpt
```
`--recipient` は既存の `chatgpt` / `codex` / `claude-code` / `coordinator` に限定。`--since` で最新の更新窓を限定可能（古い未処理候補は公開索引を通じて別途継続確認）。最新候補の発見は GitHub repository Issue-comments updated descのAPIで行い、新規候補のactor・KAEP妥当性は **原典Issue全コメントを再取得した上で**既存 `build_search_list` / strict codec により確認。未検証本文を公開APIに出さない。

出力 `kaep.live-union-check.v0.1` には、`status`、`snapshot_age_seconds`、`recent_comments_observed`、`source_issue_count`、`new_unindexed_source_issues`、`new_in_originals`、`state_or_reply_changes_from_snapshot`、`cached_rows_not_verified_live`、原典リンク＋明示的な部分不明を含む。既存索引の原典Issueはコメントが最新窓にない場合も取得されるので、閉鎖などIssue本文側の状態変化も検証可能。

受入範囲の区別:
- `BOUNDED_UNION_READ`: 今回和集合に含めた原典Issueでの検証が成立。**現在の全件網羅や未処理ゼロではない**。終了0。
- `PARTIAL_UNKNOWN`: もとの索引がPARTIAL、コメント窓上限・原典不正/取得失敗・索引原典未照合等。終了2。
- `BLOCKED`: index/REST自体または入力が読めない。終了2、機密情報は表示しない。
- `has_unknown_work=true`、`complete_source_universe=false`、`absence_of_work_proven=false`、`recipient_pickup_proven=false`、`can_authorize_execution=false` は常に維持。

**残余:** キャッシュにも直近更新窓にもない正当な原典や他の管理対象リポジトリ、GitHub側のAPIレート制限、厳密な秒単位通知SLA、ブラウザ実機でのライブ動作、完全なHTTP Agent API、実際に新規REQUEST→ACK→ANSWERが発生した陽性実測、無人モデル起床はいずれも未達。#531 B5、#503と手動Control、F10 #681を維持。新たなHost、cron、公開権限、認証、費用を増やさない。

## RT4 追跡可能な候補Issue診断（限定公開メタデータ）

統合したライブ検出の中で、**指定された受信者の有効なKAEP rootが0件**でも、候補Issueの発見は保存する。 `source_candidates` は最大40件のリストで、正規の `issue_url`・`origin`（保存済み / 直近コメント / 両方）・`matching_recipient_roots`・`source_observation`・`grants_work_authority=false` のみを出力する。未検証コメント本文やユーザー提供リンクを返さない。

`source_observation` は `ACCEPTED_RECIPIENT_ROOTS`、`NO_ACCEPTED_RECIPIENT_ROOT_OBSERVED`、`SOURCE_VALIDATION_UNKNOWN` を区別する。**0件という観測結果は、該当Issueまたはリポジトリに未処理依頼が存在しないことを意味しない**。後続AIは、必要に応じて原典Issueを独立再検証し、正しい宛先であることを確認する。候補への自動ACK、実行権限移譲、Claim変更はしない。

この拡張は [devflow #680](https://github.com/kinoko34077/devflow/issues/680) の実GitHub一回限りの監査で、Codex向け「新しい候補Issue 1件 / 厳格に合致するCodex root 0件」が確認されたことへの診断改善である。全ソース網羅、真の動的HTTP API、Safari動作、無人モデルの起動は別途未達。


## RT4-S2 明示リポジトリの限定原典取得（2026-10-17）

公開 `index.json` は現状 devflow 中心のキャッシュであり、他の管理対象リポジトリの原典依頼を網羅しない。既存 `kaep_live_union_cli` に、操作者が **対象リポのlive Controlを別途確認した場合だけ** 選ぶ `--additional-repository` を導入。読み取るリポ数はキャッシュ掲載分と合わせて最大3、canonical `kinoko34077/<repo>` のみ、重複指定は拒否する。指定がなければ以前の動作を維持。

```sh
python -m tools.kaep_live_union_cli --recipient chatgpt --additional-repository kinoko34077/execution-coordinator
```

公開JSON自体・既存Pages・GitHub Projectは更新せず、追加対象は要求時GET-onlyで直近100コメントから候補Issueを探し、**既存と同一**の厳密な原典Issue全コメント再読込・KAEP codec・actor/recipient/reply検証に一度だけ通す。全リポ横断の自動発見・認証/Claim/実行・Agent wakeは導入しない。 `repositories_checked` と `explicit_additional_repositories` で範囲を機械可読とし、`repository_scope_proven_complete=false` を保持。

追加対象に古い未処理rootが存在しても直近更新窓に出ない場合は**検出不能**であり、これは「依頼なし」の証明にはならない。各repoの100件上限・全体40 Issue上限・未知/部分状態・#503/manual Control fallbackを維持。検索/原典/recipient/head/実Consumerの全網羅と動的サーバ・Safari確認は未受入。

## 全公開リポ横断のKAEPコメント位置探索（候補限定、2026-10-17）

ユーザーの「リポを指定せず全公開リポからKAEP該当箇所の `リポ#Issue@コメントID` だけ寄越す」要件に対し、**受信・作業権限を持たない別の発見専用CLI** を提供する。既存3リポ/40原典上限の `kaep_live_union_cli` を無制限に拡張しない。

```sh
python -m tools.kaep_public_locator_cli --format lines
python -m tools.kaep_public_locator_cli --format json --max-comment-pages 50 --max-api-calls 600
```

既存の `gh api` 読取のみを用い、公式REST `GET /users/kinoko34077/repos?type=owner&per_page=100&page=N` でユーザー所有の公開リポジトリを自動列挙。返却の `private=false`・実所有者 `kinoko34077`・正規repo名を検証し、他人所有・privateを採用しない。各公開リポで `GET /repos/kinoko34077/<repo>/issues/comments?sort=created&direction=desc&per_page=100&page=N` をページ送りし、**先頭が正確にKAEP v0.2マーカーのコメントだけ**の原典位置を返す。IssueコメントとPR会話コメントが対象であり、本文・prompt・タイトル・アクセストークンを出力しない。例 `execution-coordinator#142@6222272385`。JSONは公式GitHub原典URL、repo、Issue番号、comment IDとstrict未検証フラグのみ。

探索範囲は全公開リポを目標とするが、ページ/API回数/最大候補数には有限上限がある。既定は公開リポ一覧最大3ページ、コメント40ページ/リポ、API最大350回、候補最大5000。上限・異常・通信失敗・途中更新では `PARTIAL_UNKNOWN` と `incomplete_scopes` に未読リポ/次ページ・固定理由コードを表示。走査が一応読み切れても新着競合・Issue本文だけの記録・別owner・private・現在HEAD・モデル本人性を保証しないため、常時 `complete_source_universe=false`、`has_unknown_work=true`、`absence_of_work_proven=false`、`can_authorize_execution=false`。

**重要:** KAEPマーカーは未検証の単なる発見条件。悪意ある第三者による同型コメントも候補に入るため、REQUEST/ACK/ANSWERと断定不可。必要な原典だけ既存のstrict codec、コメント全履歴、actor、宛先、返信、現在HEAD、Controlと権限を再検証。旧Inbox、#503/manual Controlは維持。この発見CLIは公開JSONを更新せず、サーバ・タイマー・Push・無人GPTモデル起動を提供しない。今回はIssue本文にしか出てこないKAEP言及、通常本文中の単語出現は走査対象外と明示する。拡張する場合は別途要件化し、検索索引由来の偽完全性を持ち込まない。

追記：実GitHub 40公開リポ限定走査で8リポがページ上限に達したため、新着を先に取りこぼさないようIssueコメントの走査を **created desc（新着先）** に変更。上限までに古いページを読み切らなければ未走査として `PARTIAL_UNKNOWN` を維持。今回の変更は取得順のみで、受信者に作業権限を与えない。

公開40リポの実取得では39リポを20ページまでで読み切り、`devflow`のみ21〜29ページが残存した。後続の公式GETでは21〜28ページが各100件、29ページが87件、30ページが空で、21〜29ページのKAEPマーカー追加0件。通常起動でこの規模を含めるため、既定のコメントページ上限を40へ更新した。API総回数上限350・最大ページ100・`PARTIAL_UNKNOWN` は維持。ページ移動を伴う新着等の非原子的な全件性は保証しない。記録: [devflow #680](https://github.com/kinoko34077/devflow/issues/680)。
