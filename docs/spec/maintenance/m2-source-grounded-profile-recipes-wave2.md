# SMC M2 実ソース別監査プロファイル Wave 2 — 7 managed repositories

Owner: [devflow #588](https://github.com/kinoko34077/devflow/issues/588)。現行M2判定規則は [先行5リポ](m2-source-grounded-profile-recipes.md) および [12 Lens rubric](multi-angle-audit-coverage-v1.md) と同じ。これは**候補仕様**であり、実監査・監査完了・新規PILOT採用・実行供給・権限変更を意味しない。

2026-10-16に **各Repository Control（live）と実README/仕様/Current State/関連コードを読取確認**した。観測したファイルblobは末尾に示す。Sourceファイルの内容はその観測時点のものであり、以後のmain/branch、リリース/実機状態を代替しない。

## 1. 観測した7リポと参照先の切分け

| Repository / Control | 読取正本と監査対象の構造 | 注意すべきリスク/本件で未証明の事項 |
| --- | --- | --- |
| [dev_agent / #15](https://github.com/kinoko34077/devflow/issues/15) | **v2開発の正本は `v2/bootstrap`**。そのrefの[README](https://github.com/kinoko34077/dev_agent/blob/v2/bootstrap/README.md)、[Current State](https://github.com/kinoko34077/dev_agent/blob/v2/bootstrap/docs/CURRENT_STATE.md)、[Integration Hardening](https://github.com/kinoko34077/dev_agent/blob/v2/bootstrap/spec/v2/INTEGRATION_HARDENING.md)。Provider/Controller/StateStore/Queue/Budget/ToolRuntime/Gate/Recoveryを分離。既定`main`のREADMEは旧v1資料。 | ControlのRisk MEDIUMは旧ブランチとの差・credential/financial/effect権限を格下げしない。Phase8の実Provider資格/正式供給は未受入で、読取だけでGate解除不可 |
| [gesture-ime / #301](https://github.com/kinoko34077/devflow/issues/301) | [README](https://github.com/kinoko34077/gesture-ime/blob/main/README.md)、[spec入口](https://github.com/kinoko34077/gesture-ime/blob/main/spec/README.md)、[Profile v3 schema](https://github.com/kinoko34077/gesture-ime/blob/main/spec/profile/gesture-ime.profile.v3.schema.json)、[v1歴史仕様](https://github.com/kinoko34077/gesture-ime/blob/main/spec/PLATFORM_COMMON.md)。共通Rust Profile v3 semanticsとiOS/Android adapters、ユーザ入力・設定反映・実キーボードの境界を分離。 | v3 authorityはIssues #43→#69→#95の明示supersession。旧v1文書を製品正本と誤認しない。iOS実機の設定/ジェスチャ反映はhosted CIとは別 |
| [SynTrail-LM / #12](https://github.com/kinoko34077/devflow/issues/12) | [README](https://github.com/kinoko34077/SynTrail-LM/blob/main/README.md)、[仕様Index](https://github.com/kinoko34077/SynTrail-LM/blob/main/docs/spec/00_INDEX.md)、[Current State](https://github.com/kinoko34077/SynTrail-LM/blob/main/CURRENT_STATE.md)。Rustモデル、チャンク/Relation、STM v1-v4・JSON・SQLite、Trainer/GUI、学習評価の区分。 | 履歴/会話SQLiteとモデルSTMは独立、メモリ負荷1GiB境界、壊れたsnapshotからactiveモデルを保護する必要あり。DEEP Control記録を各Lensの網羅と混同しない |
| [map-data-semi-automation / #404](https://github.com/kinoko34077/devflow/issues/404) | [README](https://github.com/kinoko34077/map-data-semi-automation/blob/main/README.md)、[HDS観測仕様](https://github.com/kinoko34077/map-data-semi-automation/blob/main/docs/spec/HDS_FORMAT_v0_1.md)。DBT/EXP/MDB、HDS binary、Excel/CSV、Windows Access ODBC/OLEDB/PowerShell、local_dataを分離。 | HDSは逆解析仮説であり正式完全フォーマットではない。顧客実データはGit対象外、書込前dry-run/バックアップ・lock確認必須。実資料と版の来歴は未確定の部分がある |
| [gpt-supervisor / #168](https://github.com/kinoko34077/devflow/issues/168) | [README](https://github.com/kinoko34077/gpt-supervisor/blob/main/README.md)、[E2E Run Policy](https://github.com/kinoko34077/gpt-supervisor/blob/main/docs/E2E_RUN_POLICY.md)。Chromium拡張：state machine、DOM adapter、target identity、composer input、send/retry、bounded terminal/observability。 | 異チャットへの誤送信、同一会話のstale viewを起点とする誤送信、認証E2Eは高危険境界。実ターゲットIDや認証profileを監査ログへ再掲しない。#16には人間許可・実環境Gateがあり、この提案では操作しない |
| [microtone-piano / #26](https://github.com/kinoko34077/devflow/issues/26) | [README](https://github.com/kinoko34077/microtone-piano/blob/main/README.md)、[Audio Context lifecycle](https://github.com/kinoko34077/microtone-piano/blob/main/src/core/audioContextLifecycle.ts)、[AudioEngine](https://github.com/kinoko34077/microtone-piano/blob/main/src/core/audio.ts)、[IndexedDB storage](https://github.com/kinoko34077/microtone-piano/blob/main/src/core/storage.ts)。React/Vite PWA、Web Audio、音程・音源・鍵盤、保存/プリセット/設定。 | iOS Safari audio startupの既存受入は歴史として尊重。ただし現行SHAで全端末/全pitchを証明するものではない。未知・無効frequency、storage拒否、PWA旧cacheの残存を分離 |
| [MViser / #138](https://github.com/kinoko34077/devflow/issues/138) | [README](https://github.com/kinoko34077/MViser/blob/main/README.md)、[SPEC](https://github.com/kinoko34077/MViser/blob/main/project/docs/SPEC.md)、[Current State](https://github.com/kinoko34077/MViser/blob/main/project/docs/CURRENT_STATE.md)。YAML→timeline→SceneState→Pillow→FFmpeg/PNG、GUI/sounddevice、AviUtl/AE handoffを分離。 | 以前のgui-basic評価は実際7.528秒の観測を1秒扱いした監査harness誤り。修正版のWindows再走・AviUtl/L-SMASH実機は未受入。GUI/hostedテストを物理合格としない |

## 2. M2候補：検査単位、Lensと真正な受入根拠

| Repo / scope | Lens（既存IDを再利用） | STANDARD監査で必要な観測・負例 | DEEP追加時にだけ確認 | 除外/不合格にする誤推論 |
| --- | --- | --- | --- | --- |
| dev_agent / v2 `runtime/state/scheduler` | `state-integrity-concurrency`, `reliability-recovery`, `correctness`, `error-handling` | 実 `v2/bootstrap` HEADでcheckpoint→crash→resume、idempotency、transactional tool intent、lease期限・claim競合、reconciliation_requiredをfakeで再現。exact inputs/outcomes/SQLite stateを記録 | 干渉する複数workerのrace、disk crash fault injection、legacy v1との正本ref混同の否定 | `main` のv1起動手順/文書をv2の実装監査としてcreditしない |
| dev_agent / Provider/Budget/Gate/ToolRuntime | `security`, `dependency-external-assumptions`, `resource-management`, `test-quality` | 権限/承認未取得の金融・外部書込・credential操作を拒否、reused approval/hash変造拒否、Provider 401/403/429/timeoutを区別し予算未確認なら閉じる。公開しないfake token/影響を限定したfixtureで証明 | 外部Provider本番認定と課金境界は専用owner・Human Gate後に別実証。OSプロセス隔離とresource exhaustionは独立に測る | 無課金fake CIやcatalog existenceから正式Phase8 Provider供給・デプロイ可を推定しない |
| gesture-ime / Profile v3 common Rust | `spec-implementation-drift`, `correctness`, `edge-cases`, `test-quality` | #95 frozen authority、v3 schema、Rust runtime・conformance corpusを対応付ける。無効/巨大Board、未存在ref、Gesture8、hold/macro/action、キャンセルと再読込の正負例を固定 | Swift/Kotlin/WASM上で同じProfile入出力・イベント列に対する結果parity | v1 `PLATFORM_COMMON.md`の互換説明で現行v3を上書きしない |
| gesture-ime / platform delivery & UX | `reliability-recovery`, `state-integrity-concurrency`, `observability`, `error-handling` | iOS Keyboard Extension/host設定のatomic profile反映、application restart/focus/permission revocation、undo/hold/gesture表示、失敗時再利用可能な状態を実機で確認。Device/build/hashを証拠化 | Androidとの入力/遅延/端末寿命差、OS lifecycleストレスを追加 | unsigned IPA成功、CI build、Web demo成功だけから物理iOS端末の設定反映を認定しない |
| SynTrail-LM / model state persistence | `state-integrity-concurrency`, `reliability-recovery`, `correctness`, `edge-cases` | STM v1-v4/JSON/SQLite/bincodeの後方互換、invalid identity reference/cycle、入出力境界・encoded/decoded限度、原子的保存失敗、拒否時active ModelState/DocumentState不変を故障注入で検証 | fuzz/property + huge model/resource envelope, GUI live load/save競合 | 「DEEP監査済み」の一語で各保存形式・新しいHEADを網羅済みと推論しない |
| SynTrail-LM / trainer/learning/UI | `correctness`, `resource-management`, `test-quality`, `observability` | 4/8/16/32反復の停止・dpc測定の計算法、dataset fingerprint付きPause/Resume Saved、失敗時ErrorPaused、History DBとModel DB分離を固定入力で実証 | 大規模corpus記憶/速度・統計的評価、closed/forced terminationでの状態可用性 | dpcの単一数値から自然言語理解・一般化成立を自動判定しない |
| map-data-semi-automation / read-only format analysis | `correctness`, `spec-implementation-drift`, `dependency-external-assumptions`, `test-quality` | HDS実バイトと版/取得経緯の一致、ID候補と座標/クラス境界、DBT/MDB間の対応は独立な実ファイルhash/fixture・反例付きで確認。未知offsetはUNKNOWNのまま | 真正同世代複数資料で復元率/誤検出を集計 | 110 byte間隔や一部SSymbol offset仮説を全HDSに一般化しない |
| map-data-semi-automation / HDS/MDB mutation | `state-integrity-concurrency`, `reliability-recovery`, `security`, `error-handling` | 事前dry-run/copy backup、MDB lock、plan→write実体照合、部分失敗・abortの元ファイル維持、顧客名/個人情報のログ除外。**synthetic作業コピーでのみ**試験 | Windows実ODB/OLEDB・Excel導線・原子的復旧を専用ownerの正当な許可で実証 | 実顧客MDBへの書込やprivate解析ファイルのGit公開を監査テストとして行わない |
| gpt-supervisor / fixed target + composer | `security`, `state-integrity-concurrency`, `correctness`, `reliability-recovery` | fixture/mock UI上で対象IDとProject/タイトル、別チャット遷移、stale/unknown view、手動composer文字列、二重SEND、ack/retry上限を再現。送信前後状態の観測証拠 | 実認証E2Eは既存#16 owner・明示Human Gate・専用回復手順・現実のページ証拠に限定 | ChatGPT conversation identity一致からlatest-head freshnessを推測したり、別チャット探索・自動ARMを行わない |
| gpt-supervisor / state & diagnostic | `error-handling`, `observability`, `resource-management`, `lifecycle-consistency` | idle/grace/working/DONE/NEED_USER/HALTED、DOM不明時fail-closed、処理回数/稼働時間上限、sanitize log、タスク#16/#17順序をテスト | Chrome更新等のexternal DOM変動は新たに同意されたE2Eで確認 | mock PASSを認証実send成功やユーザー同意の代わりにしない |
| microtone-piano / AudioContext & tuning | `correctness`, `edge-cases`, `reliability-recovery`, `resource-management` | finiteかつ>0Hz frequency contract、正負invalid/range、AudioContext suspended/interrupted→resume→running、失敗時明示状態と再試行、max polyphony/voice cleanupをブラウザ別に検査 | 実iOS Safari background/lock/resumeと長時間voice/CPU/latency | Web Audio API mock、1回の過去Safari PASSから現行全機能合格を推定しない |
| microtone-piano / IndexedDB & PWA | `state-integrity-concurrency`, `error-handling`, `security`, `dependency-external-assumptions` | プリセット validation、save/read/deleteのtransaction失敗、IndexedDB権限拒否、standard/user IDs優先、PWA cache旧asset/stale binary扱い。ページ操作と出力を含む根拠 | IndexedDB version migration、offline起動・異なるiOS/Android safari/chrome実機 | IndexedDB書込失敗から永続化成功と誤表示したり、旧cacheを最新公開と判断しない |
| MViser / YAML→scene→video | `correctness`, `edge-cases`, `security`, `test-quality` | 固定BPM/offset/frame換算、12EDO/微分音ChordSpec、ルビ/字幕、PNG/MP4/透過出力のfixture parity。プロジェクト外ファイル参照、ファイル名/path traversal、CP932/JSX escaping負例 | サンプル素材でFFmpeg実render再現と画質/フレーム同期を測定 | schema/spec PASSだけで実映像・全フォント・全editor import可と認定しない |
| MViser / GUI audio/editor handoff | `reliability-recovery`, `observability`, `resource-management`, `spec-implementation-drift` | 実elapsed timeに基づくgui-basic/game?監査時刻、音声/無音fallback、seek/stop状態、actual wall-clockとFPS、AviUtl .exo/ProRes .mov→L-SMASH/AE import。owner #41/#42/#45の実機証拠を分離 | owner Windows/AviUtl系物理試験・ドロップフレーム/リソース上限 | 旧7.528s traceを1sと誤解した単位換算、CI-onlyから物理合格を主張しない |

## 3. 優先度・除外・監査Depthの扱い

1. 実装に伴うリスクは**リポControl全体のMEDIUM/HIGHとcomponent固有の副作用危険度を別軸**で評価する。dev_agent ToolRuntime/Financial、gpt-supervisor実認証send、顧客DB書込は特にHuman/credential/data境界を持つ。ドキュメントから`risk_override`の数値を推定確定しない。
2. `CONTROL`はControl/Issue/PR/CIの整合。ここにある`STANDARD`/ `DEEP`は**実際に完了したそのscope+Lensだけ**。必須の正負試験、source SHA、外部依存鮮度、run evidence Issueと出力原本がそろわなければ`NOT_RUN/UNKNOWN/INSUFFICIENT_EVIDENCE`。
3. 本表に載らない残りの共通Lensは**除外されていない**。必要ならrepo-local ownerが`not applicable`理由と具体的非対象条件を記録して初めて除外できる。`security`をリポ全体から黙示除外しない。
4. `dev_agent`は例外的にdefault `main` と現行 `v2/bootstrap` が異なる。候補作成・selector・実行後recordは対象refとコードSHAを固定し、通常のdefault-ref導入処理でcurrent v2 coverageと誤判定しない。repo-local `.devflow/maintenance.yaml`は今回新設しない。
5. `map-data-semi-automation`のlocal dataおよび`gpt-supervisor`認証会話の正確なID、private auth/sessionを公共の監査レポートへ転写しない。表は作業条件を示すのみ。対象実動作は実施していない。
6. 各repoの正本・ownerに競合する作業を開始しない。監査候補の採用は既存3 PILOTの真のM5証拠、repo-local owner Issue、カタログschema/CI/formal Review、最新sourceとリスク分類、段階許可を条件とする。第四repoの機械的自動供給は依然`HOLD`。

## 4. 計測する検出価値とM2残部

採用後に比較する単位は`repository × scope × Lens × Depth × fingerprint`。各単位で**実行者、検査系統、positive/negative evidence、findingの真偽、重複、再現性、source drift、必要コスト、観測漏れ**を収集する。モデルの提案を実監査の成績に数えない。

これで先行5 + 本7 = **重複しない12管理リポのsource-grounded設計候補**。ただし管理対象全リポのsource inventory完了・実カタログ採用・稼働・監査実施は**未完了**。残部は最新の対象Control一覧を基に同じ方法で区切り、全体数は観測時刻を固定して再算定する。

## 5. 読取した実ファイル識別（blob SHAの先頭8桁）

- dev_agent `v2/bootstrap`: README `4bb5c4f5`, docs/CURRENT_STATE `c55dc52b`, spec/v2/INTEGRATION_HARDENING `a8633d20`。default main旧README `87b288b5`。
- gesture-ime: README `dbd5b678`, spec/README `1f788524`, v3 schema `65ae3db4`, PLATFORM_COMMON `d3271c43`。
- SynTrail-LM: README `14e3a22f`, CURRENT_STATE `418d69d1`, docs/current/CURRENT_STATE `33ed6124`, docs/spec/00_INDEX `a4a918d0`。
- map-data-semi-automation: README `e40c0356`, HDS_FORMAT `2f21699f`。
- gpt-supervisor: README `7502df8b`, E2E_RUN_POLICY `152d3f01`。
- microtone-piano: README `3b5b23a5`, AudioContext lifecycle `0949dd07`, AudioEngine `157d4ba5`, IndexedDB storage `e3205c95`。
- MViser: README `c9844027`, AGENTS `55c0193c`, SPEC `1c562ea1`, Current State `c1fbcce9`。

Blob識別は局所ファイル読取の来歴であり、**全ファイルが単一コミットの同時snapshotだった証明ではない**。併走する更新は次のowner作業時に新鮮さを再検証する。
