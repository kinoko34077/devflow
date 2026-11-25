# 統一取得マッパー v1（#1144、内部契約受入済み・CLI候補）

固有名の標準ライブラリのみのPython package `devflow_mapped_read` が共通契約の唯一の実装。devflow側の `tools.mapped_github_read` は既存Reader接続を所有。公開API、認証、保存、既存Consumerを変更しない。共通化はこの一箇所で行い、各機構は対応する時刻・条件・許可属性・原典検証を所有するadapterを登録する。

```json
{
  "schema_version": "mapped-read.v1",
  "time": {"field": "github.updated_at", "from_inclusive": "2026-11-20T00:00:00Z", "to_exclusive": "2026-11-21T00:00:00Z"},
  "target": {"dataset": "github.issue", "repositories": ["kinoko34077/devflow"], "filters": {"state": "all"}},
  "response": {"fields": ["id", "number", "updated_at"], "limit": 100},
  "budget": {"per_page": 100, "max_pages": 3}
}
```

- trusted callerがSourceMapと許可repository範囲を供給。要求は登録済みdataset、明示repo、時刻意味、許可属性のみ選択でき、実行コード/URL/credentialを選べない。時刻はUTC半開区間、source固有精度はadapterで検査。個別時刻がない索引は日時条件を拒否。
- `read_mapped` は共通入力・owner固有条件を取得前検証、登録された読取をrepo単位で実行、許可属性だけを返す。既知のGitHub読取失敗・欠損/JSON不正の選択属性は該当repoのBLOCKEDに局所化し、そのrepoの不正なprefixは返さない。GitHub adapterはmetadataの型を検証し、任意のネストデータを通さない。全BLOCKEDと部分取得と限定読取を区別。response.limitは返却数のみ制御、GET予算ではない。
- 結果はsource owner・query signature・観測日時・各repoのsource status/理由/版/観測単位/再検証要否を保持。全履歴/全source完全性・実行許可を主張しない。現時点でcursor、cache、汎用任意filterは未対応。未対応条件を無視しない。
- 代表のgithub.issue/github.issue_commentは既存GitHubReaderを注入。生本文・token等の属性は返答許可しない。KAEP原典検証、Index保存済みカタログ、Archive保存済み編集の実adapterはそれぞれの正本と権限境界を保つ。
- 共通UTC解析・Reader引数検証を再利用。別repoは同一の検証済みdevflow commitを固定したcheckoutから `devflow_mapped_read` をimportする（既存PYTHONPATHまたは信頼済みホストのimport path、コピー・新規package公開・依存追加不要）。共通packageは `tools` に依存せず、別repo固有の `tools` と共存する。GitHub live adapterはdevflowの既存Reader側に残す。認可範囲はtrusted callerの明示集合、repo文字列は構文のみ検査しowner固定と混同しない。今後の受入は実入口・実データ・共有経路/版固定・既存Consumerとの同等性。既存全repo適用は受入条件にしない。

## 共通利用入口（C3候補）

固定した検証済みdevflow checkoutを作業ディレクトリとし、既存CLIを別processで呼ぶ。Python packageのimportを必要としないGitHub取得用入口。外部repoのローカルadapterは固有名packageを直接importする。

```sh
python -m tools.devflow_read_cli mapped-read --request-file /absolute/path/request.json --allowed-repository kinoko34077/devflow
```

- `--allowed-repository` は信頼済みローカル呼出側が指定（複数回可）。要求JSONから認可集合を生成しない。既存GitHubReaderの環境認証・GETのみ。要求側でURL/credentialを指定できない。新規公開MCP/サービス/認証変更なし。
- JSONは既存CLIの100,000文字上限・重複キー拒否規則を使用。異常入力/全BLOCKEDはexit 2、限定・部分読取はexit 0でcoverageを必ず確認。stdoutはJSON、既存の有限reason_codeによる秘匿診断。実運用の版選択・既存Consumer接続は別受入。
