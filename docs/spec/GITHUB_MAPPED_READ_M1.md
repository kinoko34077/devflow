# 共通GitHub読取契約（M1 初期実装候補）

Owner: [#1129](https://github.com/kinoko34077/devflow/issues/1129) / 親 [#1128](https://github.com/kinoko34077/devflow/issues/1128) 。状態：PR候補、受入前。

既存 `tools.devflow_mcp_core.GitHubReader.read_updated_range` はGitHub RESTの現在のIssue・repoコメントを更新日時で有限読取する内部入口。既存の認証・GET transportを再利用し、公開MCP/CLIや既存Consumerを変更しない。用途別mapper/返答フィールド選択・Archive接続・再利用cacheは後続の独立受入。

- 入力：repository、kind=issue|issue_comment、UTC秒精度のfrom/to（任意、半開区間）、issue state（issueのみ、既定all）、per_page 1–100、max_pages 1–40（既定3）。
- GitHub native sinceに開始境界の1秒前を渡し、返却updated_atで正確な半開区間を抽出。PR一覧混入をIssueとして扱わない。repoコメントにはPR会話コメントも含み得る。
- 返却：内部原典items、実際に読んだページ数、範囲、状態、理由コード。短いページを観測した場合も `BOUNDED_WINDOW_READ` は非原子的観測で、完全なsource universe・編集履歴・作業権限を意味しない。
- ページ上限、ID重複はPARTIAL_UNKNOWN。異常行・日時・repo不一致・通信失敗は例外とし空の成功にしない。結果は内部専用で外部公開・永続化しない。
- 読取の終了と保存ACK/増分watermarkは別。本機能は状態・カーソルを書き換えない。既存のKAEP strict検証やArchive保存検証を置換しない。
- 検証: `python -m unittest tests.test_devflow_updated_range` と既存MCP Reader回帰。実GitHub観測・CI・独立Reviewを別途確認。
