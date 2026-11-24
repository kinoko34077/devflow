# 共通GitHub読取契約（M1 初期実装候補）

Owner: [#1129](https://github.com/kinoko34077/devflow/issues/1129) / 親 [#1128](https://github.com/kinoko34077/devflow/issues/1128) 。状態：初期基盤 #1131 統合済み、過去期間の改善は #1132 のPR候補。

既存 `tools.devflow_mcp_core.GitHubReader.read_updated_range` はGitHub RESTの現在のIssue・repoコメントを更新日時で有限読取する内部入口。既存の認証・GET transportを再利用し、公開MCP/CLIや既存Consumerを変更しない。用途別mapper/返答フィールド選択・Archive接続・再利用cacheは後続の独立受入。

- 入力：repository、kind=issue|issue_comment、UTC秒精度のfrom/to（任意、半開区間）、issue state（issueのみ、既定all）、per_page 1–100、max_pages 1–40（既定3）。
- GitHub native sinceは同値を含む実観測がある。開始境界の1秒前（epoch下限でクランプ）を保守的な重複として渡し、返却updated_atで正確な半開区間を抽出。終了日時指定時は更新日時昇順、未指定時は従来の降順。PR一覧混入をIssueとして扱わない。repoコメントにはPR会話コメントも含み得る。
- 返却：内部原典items、実際に読んだページ数、範囲、状態、理由コード。短いページまたは順序異常・重複のない全ページ内で終了日時以上を観測した場合に停止する。`page_exhausted` と `upper_bound_reached` は別の停止理由。いずれも `BOUNDED_WINDOW_READ` は非原子的観測で、完全なsource universe・編集履歴・作業権限を意味しない。
- ページ上限、ID重複、観測順序逆転はPARTIAL_UNKNOWN。ページ移動・削除等による見逃しをすべて検出できるわけではない。異常行・日時・repo不一致・通信失敗は例外とし空の成功にしない。結果は内部専用で外部公開・永続化しない。
- 読取の終了と保存ACK/増分watermarkは別。本機能は状態・カーソルを書き換えない。既存のKAEP strict検証やArchive保存検証を置換しない。
- 検証: `python -m unittest tests.test_devflow_updated_range` と既存MCP Reader回帰。実GitHub観測・CI・独立Reviewを別途確認。
