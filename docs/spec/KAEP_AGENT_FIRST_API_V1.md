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

