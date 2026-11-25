# 統一取得マッパー v1

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
- 結果はsource owner・query signature・観測日時・各repoのsource status/理由/版/観測単位/再検証要否を保持。全履歴/全source完全性・実行許可を主張しない。現時点でcursor、永続cache、汎用任意filterは未対応。未対応条件を無視しない。
- 代表のgithub.issue/github.issue_commentは既存GitHubReaderを注入。生本文・token等の属性は返答許可しない。KAEP原典検証、Index保存済みカタログ、Archive保存済み編集の実adapterはそれぞれの正本と権限境界を保つ。
- 共通UTC解析・Reader引数検証を再利用。別repoは同一の検証済みdevflow commitを固定したcheckoutから `devflow_mapped_read` をimportする（既存PYTHONPATHまたは信頼済みホストのimport path、コピー・新規package公開・依存追加不要）。共通packageは `tools` に依存せず、別repo固有の `tools` と共存する。GitHub live adapterはdevflowの既存Reader側に残す。認可範囲はtrusted callerの明示集合、repo文字列は構文のみ検査しowner固定と混同しない。共通契約・標準CLIの受入は #1144 を参照。既存Consumerとの同等性は各適用ownerで検証する。既存全repo適用は受入条件にしない。

## 共通利用入口

固定した検証済みdevflow checkoutを作業ディレクトリとし、既存CLIを別processで呼ぶ。Python packageのimportを必要としないGitHub取得用入口。外部repoのローカルadapterは固有名packageを直接importする。

```sh
python -m tools.devflow_read_cli mapped-read --request-file /absolute/path/request.json --allowed-repository kinoko34077/devflow
```

- `--allowed-repository` は信頼済みローカル呼出側が指定（複数回可）。要求JSONから認可集合を生成しない。既存GitHubReaderの環境認証・GETのみ。要求側でURL/credentialを指定できない。新規公開MCP/サービス/認証変更なし。
- JSONは既存CLIの100,000文字上限・重複キー拒否規則を使用。異常入力/全BLOCKEDはexit 2、限定・部分読取はexit 0でcoverageを必ず確認。stdoutはJSON、既存の有限reason_codeによる秘匿診断。実運用の版選択・既存Consumer接続は別受入。

## 同一バッチの取得再利用

既存CLIのrequest-fileまたはPythonの `read_mapped_batch` へ `{"schema_version":"mapped-read-batch.v1","requests":[<mapped-read.v1>,...]}` を渡す（requestsの各要素は通常要求）。同一の信頼済みregistry・認証reader・許可repo集合を持つ一回の明示batch内でのみ、ownerが `batch_reusable=True` を明示したdatasetの成功観測を再利用する。取得キーはdataset、repo、日時境界、filters、budgetの一致。response.fields/limitはキーから除外し、毎要求で検証・投影する。既定値の省略と明記は保守的に別キー。異なるrepo/条件・部分/失敗・不足属性・別batchは再取得。新規永続cache・他process共有なし。

結果は `mapped-read-batch-result.v1`、入力順のresults、全体status、source_reads（source呼出数、GET数そのものではない）、reused_observations。各repoのsource_observed_atは元取得終了時刻を保持し、reused_observationとobserved_new_read_unitsで再利用を明示する。取得失敗で実GET数を観測できない場合はread_unitsを完全な通信計測とみなさない。単一要求の形式は維持。個別の契約拒否は固定コードINVALID_MAPPED_REQUESTで局所化する。全BLOCKEDはCLI exit2、部分はexit0。共通観測は原子的snapshot・最新状態・原典再検証の代替ではない。

## 内部GitHub native query・ページ進行

`devflow_mapped_read.github_pages` は既存Reader/KAEPのIssue・コメントnative取得を共通化する。信頼済みsource ownerは `RepositoryIssueQuery` へrepository/kind/state/sort/direction/native_since/per_pageを宣言し、既存認証付きGET callbackを `iter_list_pages` へ注入する。Linkのnextが明示される場合はその値を使い、観測不能なら短ページを終了/fullを継続候補とする。ページ予算到達時にhas_nextを保持し、途中停止は追加GETを行わない。native sinceはAPI引数そのもので、半開区間・重複・identity/actor・原典検証を置換しない。M1のoverlap/古い下限fallbackは既存Readerに残す。KAEPの既存gh経路・上限・error/locator/原典照合は保持。内部raw行は既存trusted process内のみ、公開CLIの許可属性を増やさない。IndexのLink経路への接続は #50 の代表検証で行う。

## 宣言的な内部全ページ取得（#1154 R2）

`read_linked_rows(plan.path, get_page, per_page=plan.per_page, max_pages=既存の予算)` は明示的なLinkヘッダーを返す既存GET経路向けの全ページ取得入口。GET callbackは既存transportの `(rows, Link文字列)` を返す（Linkなしは空文字列）。任意のLink URLへアクセスせず、宣言したpathの連番だけを使用。nextが残る予算到達や途中の読取失敗では正常な全件結果を返さない。Linkによるページ終了は原子的snapshot/全source完全性の保証ではない。公開CLIの許可属性は変更しない。

Issue Index等の信頼済みローカル処理は、既存の検証済みdevflow固定checkoutを `PYTHONPATH` または既存のimport path設定で参照し、`RepositoryIssueQuery` と `read_linked_rows` を直接利用する。既存のrepo探索・認証・retry・body分類・保存境界はそのownerに残す。新規依存配布、個別loader、別HTTP実装は不要。固定版の選択は共通ホスト設定側で行い、利用先コードに個別の版文字列を埋め込まない。SourceMapは保存済み履歴/索引の意味・許可属性の登録にそのまま利用し、別schemaを新設しない。各consumerの実運用切替は個別受入による。

ページ単位の既存利用者は `iter_linked_pages` を利用する。同じLink判定・予算・異常処理を `read_linked_rows` も利用し、別ループを実装しない。iteratorを完全に消費してnextが残る予算に到達した場合は例外。途中で停止した結果は全件として扱わない。
