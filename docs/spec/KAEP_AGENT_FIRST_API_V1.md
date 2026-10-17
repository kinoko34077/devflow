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
